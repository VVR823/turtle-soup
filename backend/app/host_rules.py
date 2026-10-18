"""Conservative, source-bound decisions; retrieval/regex scores grant no truth.

This is a small supported grammar, not a general Chinese semantic parser.
Uncovered wording, references and contradictory authored rules defer to the
context-aware model. Exact authored QA is not human quality certification.
"""
from dataclasses import dataclass
import re

from .baselines import digest
from .host_evidence import build_evidence_catalog
from .question_normalization import normalize_exact_question
from .schemas import AnswerType, HostVersions, Soup


@dataclass(frozen=True, slots=True)
class RuleDecision:
    answer: AnswerType
    evidenceIds: tuple[str, ...]
    contextIndependent: bool
    scope: str
    ruleId: str


_CONDITIONAL = re.compile(r"如果|假如|假设|倘若|只要|除非|即使|一旦|无论|仅当|否则|或者|要么|"
                          r"因为|意味着|导致|所以")
_REFERENCE = re.compile(r"(?<!其)[他她它]|自己|自身|本人|前者|后者|对方|其中|某人|"
                        r"这个人|那个人|前面|刚才|之前|上述|这里|那里|这件|那件")
_CLAUSE = re.compile(r"[、，,；;]|而且|但是|并且")
_ATOM_FRAGMENT = re.compile(r"[A-Za-z0-9\u3400-\u9fff·/]+")
_NESTED_ASSERTION = re.compile(r"是|被")
_COORDINATED_TERM = re.compile(r"且|及|和|与|兼|既|又|或|并|而|但|也|同时")
_GENRE = re.compile(r"(?:(?:这|这个|这碗汤|本汤|故事|这个故事|这故事)(?:是|不是|属于)|"
                    r"(有|没有|存在|不存在))(本格|变格)(?:元素)?")
_PRESENCE = re.compile(r"(?:(?:故事|故事里|故事中|本汤|这碗汤)(?:里|中)?(?:面)?)?"
                       r"(有|没有|存在|不存在)([^，,、；;。]+?)(?:元素)?")
_COUNT = re.compile(r"(?:(?:故事|本汤|这碗汤|这个故事)(?:里|中|里面)?)"
                    r"(?:只有|仅有|一共(?:有)?|总共(?:有)?|共有|共|有)"
                    r"([0-9]+|[零一二两三四五六七八九十]+)(?:个|口)?人")


def _statement(question: str) -> str:
    text = normalize_exact_question(question)
    for tail in ("对吗", "对吧", "是吗", "吗", "么", "吧"):
        if text.endswith(tail):
            return text[:-len(tail)].rstrip()
    return text


def genre_answer(soup: Soup, question: str) -> AnswerType | None:
    if soup.genre not in {"本格", "变格"}:
        return None
    text = _statement(question)
    match = _GENRE.fullmatch(text)
    if not match:
        return None
    positive = not ("不是" in text or match[1] in {"没有", "不存在"})
    agrees = soup.genre == match[2]
    return "是" if agrees == positive else "不是"


def _presence_fact(soup: Soup, question: str):
    match = _PRESENCE.fullmatch(_statement(question))
    if not match:
        return None
    positive = match[1] in {"有", "存在"}
    matches = []
    for index, fact in enumerate(soup.truthItems or ()):
        if (fact.subject not in {"故事", "本汤", "这碗汤"} or fact.object != match[2]
                or fact.confidence != "high"):
            continue
        if fact.relation in {"有", "存在"}:
            matches.append(("是" if positive else "不是", f"truthItems[{index}]"))
        elif fact.relation in {"没有", "不存在"}:
            matches.append(("不是" if positive else "是", f"truthItems[{index}]"))
    if not matches or len({answer for answer, _ in matches}) != 1:
        return None
    return matches[0][0], tuple(path for _, path in matches)


def presence_answer(soup: Soup, question: str) -> AnswerType | None:
    match = _presence_fact(soup, question)
    return match[0] if match else None


def _number(text: str) -> int | None:
    if text.isascii() and text.isdigit():
        return int(text)
    digits = dict(zip("零一二两三四五六七八九", (0, 1, 2, 2, 3, 4, 5, 6, 7, 8, 9)))
    if text in digits:
        return digits[text]
    match = re.fullmatch(r"([一二两三四五六七八九]?)十([一二三四五六七八九]?)", text)
    if match:
        return digits.get(match[1], 1) * 10 + digits.get(match[2], 0)
    return None


def count_answer(soup: Soup, question: str) -> AnswerType | None:
    if soup.castCount is None:
        return None
    match = _COUNT.fullmatch(_statement(question))
    if not match or (number := _number(match[1])) is None:
        return None
    return "是" if number == soup.castCount else "不是"


def _signature(text: str) -> tuple[str, bool] | None:
    """Only exact subject/predicate with explicit binary polarity changes.

    No token similarity, substring match, subject substitution, deletion of
    qualifiers, digits, possession or arbitrary punctuation is performed.
    """
    text = _statement(text)
    if _CONDITIONAL.search(text) or _REFERENCE.search(text) or _CLAUSE.search(text):
        return None
    # A complete assertion must have a subject before the supported operator.
    # Positive recognition of an explicit subject/predicate grammar, not
    # arbitrary exact QA declared pure just because a blacklist missed it.
    # Unsupported language/subject syntax remains a normal model question.
    match = re.fullmatch(r"([A-Za-z0-9\u3400-\u9fff·/]+?)(不是|是|被)([A-Za-z0-9\u3400-\u9fff·/]+)", text)
    if not match:
        return None
    subject, operator, predicate = match.groups()
    positive = operator != "不是"
    if predicate.startswith("被") and operator in {"是", "不是"}:
        operator, predicate = "被", predicate[1:]
    if operator == "被" and predicate.endswith("的"):
        predicate = predicate[:-1]
    if not predicate:
        return None
    # One explicit assertion operator with lexical subject/object fragments.
    # An additional copula/passive inside either fragment is another assertion,
    # whatever word (or missing punctuation) connects it. Never flip its entire
    # opaque text as if it were a single proposition. Coordinated noun phrases
    # need a grammar we don't support; leave them to the model too.
    if (not _ATOM_FRAGMENT.fullmatch(subject) or not _ATOM_FRAGMENT.fullmatch(predicate)
            or _NESTED_ASSERTION.search(subject) or _NESTED_ASSERTION.search(predicate)
            or _COORDINATED_TERM.search(subject) or _COORDINATED_TERM.search(predicate)):
        return None
    # Still-a-dream is a narrow tense-free identity variant already authored;
    # don't remove 还 from arbitrary predicates or time-qualified questions.
    if subject.endswith("还") and re.fullmatch(r"星期[一二三四五六日天]还", subject):
        subject = subject[:-1]
    if predicate.startswith("真的"):
        predicate = "真" + predicate[2:]
    return subject + ("被" if operator == "被" else "是") + predicate, positive


def _flip(answer: AnswerType) -> AnswerType | None:
    return {"是": "不是", "不是": "是"}.get(answer)


def _clauses(text: str) -> list[str]:
    parts = [part.strip() for part in _CLAUSE.split(text) if part.strip()]
    # Ellipsis only for an explicit repeated identity predicate, e.g.
    # 幽灵不是真幽灵，是催眠幻象. Never invent a missing object/subject otherwise.
    previous_subject = None
    completed = []
    for part in parts:
        if part.startswith(("是", "不是")) and previous_subject:
            part = previous_subject + part
        match = re.fullmatch(r"(.+?)(?:不是|是|被)(.+)", part)
        previous_subject = match[1] if match else None
        completed.append(part)
    return completed


def question_has_static_scope(soup: Soup, question: str) -> bool:
    """Positive scope proof used BEFORE shared cache lookup and rule authority.

    Whole-story metadata explicitly names its domain. Other pure questions
    must be completely recognized assertions with explicit subjects. Authored
    exact text alone does not assert history independence.
    """
    query = _statement(question)
    if _CONDITIONAL.search(query) or _REFERENCE.search(query):
        return False
    explicit_story = re.match(r"^(?:故事(?:里|中)?|本汤|这碗汤|这个故事)", query) is not None
    if explicit_story and (genre_answer(soup, question) is not None
                           or _presence_fact(soup, question) is not None
                           or count_answer(soup, question) is not None):
        return True
    if re.search(r"我|这|那|你|您|咱", query):
        return False
    parts = _clauses(query)
    return bool(parts) and all(_signature(part) is not None for part in parts)


def decide_deterministic(soup: Soup, question: str, history: list[dict], *,
                         versions: HostVersions, conflict_observer=None) -> RuleDecision | None:
    puzzle_version = versions.puzzleVersion
    if puzzle_version == "unversioned":
        # Legacy internal callers get source IDs, not cache/pinned authority.
        puzzle_version = "p1:" + digest({"schemaVersion": 1, "soup": soup.model_dump(mode="json")})
    catalog = {record.sourcePath: record.id for record in build_evidence_catalog(soup, puzzle_version)}
    query = _statement(question)

    def decision(answer, paths, scope, independent=True):
        ids = tuple(sorted({catalog[path] for path in paths}))
        identity = {"policy": "guarded-v1", "question": query, "answer": answer,
                    "evidence": ids, "scope": scope, "contextIndependent": independent}
        return RuleDecision(answer, ids, independent, scope, "rule1:" + digest(identity))

    if _CONDITIONAL.search(query) or _REFERENCE.search(query):
        return None
    static_scope = question_has_static_scope(soup, question)
    # Metadata parsers are full-string grammars, never loose keyword locks.
    metadata = genre_answer(soup, question)
    if metadata is not None:
        if history and not static_scope:
            return None
        return decision(metadata, ("genre",), "metadata", static_scope)
    presence = _presence_fact(soup, question)
    if presence:
        if history and not static_scope:
            return None
        return decision(presence[0], presence[1], "metadata", static_scope)
    count = count_answer(soup, question)
    if count is not None:
        return decision(count, ("castCount",), "metadata")

    # First person exact QA can refer to a story narrator, but not a mutable
    # player/history referent. Narrow empty-history compatibility, never pure.
    narrator = "我" in query
    if narrator and (history or "我" not in soup.surface):
        return None
    if re.search(r"这|那|你|您|咱", query):
        return None
    if not narrator and not static_scope:
        return None
    bindings = []
    for index, cp in enumerate(soup.confusionPoints or ()):
        bindings.append((_statement(cp.q), cp.a, f"confusionPoints[{index}]"))
    for index, cp in enumerate(soup.checkpoints):
        # Scope belongs to the ENTIRE source, including every alias. Never
        # extract a consequent from a conditional/shared-reference source.
        if _CONDITIONAL.search(cp.key) or _REFERENCE.search(cp.key):
            continue
        answer = "是" if cp.answer is True else "不是" if cp.answer is False else "与此无关"
        path = f"checkpoints[{index}]"
        for text in (cp.key, *(cp.aliases or ())):
            statement = _statement(text)
            if _signature(statement) is not None:
                bindings.append((statement, answer, path))
        # Only a known-true conjunction licenses its component assertions.
        if (cp.answer is True and len(parts := _clauses(cp.key)) > 1
                and question_has_static_scope(soup, cp.key)):
            for part in parts:
                if _signature(part) is not None:
                    bindings.append((part, "是", path))

    def lookup(text):
        found = []
        signature = _signature(text)
        for statement, answer, path in bindings:
            if statement == text:
                found.append((answer, path))
                continue
            other = _signature(statement)
            if signature and other and signature[0] == other[0]:
                effective = answer if signature[1] == other[1] else _flip(answer)
                if effective is not None:
                    found.append((effective, path))
        if found and len({answer for answer, _ in found}) != 1 and conflict_observer is not None:
            # Preserve normal online fallback while allowing the repair
            # validator to distinguish a known contradiction from no match.
            conflict_observer(tuple(sorted({path for _, path in found})))
        if not found or len({answer for answer, _ in found}) != 1:
            return None
        return found[0][0], tuple(path for _, path in found)

    whole = lookup(query)
    if whole:
        return decision(whole[0], whole[1], "whole_question", static_scope)
    if narrator:
        return None  # no reference rewriting/aggregation for first person
    parts = _clauses(query)
    if len(parts) < 2:
        return None
    answers, paths = [], []
    for part in parts:
        match = lookup(part)
        if not match or match[0] not in {"是", "不是"}:
            return None
        answers.append(match[0])
        paths.extend(match[1])
    answer = answers[0] if len(set(answers)) == 1 else "是也不是"
    return decision(answer, paths, "all_clauses")


def checkpoint_question_expectation(soup: Soup, checkpoint_index: int, question: str,
                                    history: list[dict]) -> AnswerType | None:
    """Strict complete checkpoint relation; a mentioned atom is not a whole fact.

    Reuse the online supported grammar, but never use an evidence ID alone to
    claim that a question covered every part of its checkpoint. The scope of
    both the original source and the question must be independently complete.
    """
    if type(checkpoint_index) is not int or not 0 <= checkpoint_index < len(soup.checkpoints):
        raise ValueError("Invalid checkpoint index")
    cp = soup.checkpoints[checkpoint_index]
    if type(cp.answer) is not bool:
        return None
    try:
        if not question_has_static_scope(soup, cp.key) or not question_has_static_scope(soup, question):
            return None
        # An exact prior noun is not an explicit identity for a reference;
        # unresolved first/reflexive-person inputs remain unconfirmed.
        query_parts = _clauses(_statement(question))
        source_parts = _clauses(_statement(cp.key))
        query_signatures = [_signature(part) for part in query_parts]
        source_signatures = [_signature(part) for part in source_parts]
        if any(value is None for value in query_signatures + source_signatures):
            return None
        related = all(any(query[0] == source[0] for query in query_signatures) for source in source_signatures)
        if not related:
            for alias in cp.aliases or ():
                # Only a complete single authored assertion is an alias. Weak
                # topic strings, conditions and history references are not.
                if len(source_parts) == 1 and question_has_static_scope(soup, alias):
                    alias_sig = _signature(alias)
                    if alias_sig and any(value[0] == alias_sig[0] for value in query_signatures):
                        related = True
                        break
        if not related:
            return None
        # A false conjunction does not license its component negatives.
        if len(source_parts) > 1 and cp.answer is False:
            return None
        decision = decide_deterministic(soup, question, history, versions=HostVersions())
        if decision is None or decision.answer not in {"是", "不是"}:
            return None
        if len(query_parts) > 1 and decision.answer == "不是":
            # Denying a conjunction does not prove each component's opposite.
            # Single full opposite-polarity questions still confirm one fact.
            return None
        version = "p1:" + digest({"schemaVersion": 1, "soup": soup.model_dump(mode="json")})
        source_id = next(record.id for record in build_evidence_catalog(soup, version)
                         if record.sourcePath == f"checkpoints[{checkpoint_index}]")
        return decision.answer if source_id in decision.evidenceIds else None
    except ValueError:
        # Empty/unsupported user wording isn't a game failure or guessed fact.
        return None
