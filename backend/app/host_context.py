"""Bounded complete-turn context without modifying the persisted history."""
from dataclasses import dataclass


class ContextLimitError(ValueError):
    pass


@dataclass(frozen=True)
class ContextWindow:
    system: str
    user: str
    turns_included: int
    input_chars: int
    policy_version: str = "context-v1"


def build_context(*, system_prompt: str, facts_prompt: str, question: str,
                  history: list[dict], extra_instruction: str = "",
                  max_turns: int = 12, max_chars: int = 8000) -> ContextWindow:
    if type(max_turns) is not int or not 0 <= max_turns <= 12:
        raise ValueError("Context turn limit must be between 0 and 12")
    if type(max_chars) is not int or not 1 <= max_chars <= 8000:
        raise ValueError("Context character limit must be between 1 and 8000")
    pairs = []
    index = 0
    while index + 1 < len(history):
        user, host = history[index], history[index + 1]
        if user.get("role") != "user" or host.get("role") != "host":
            index += 1
            continue
        index += 2
        if any(message.get("isFreeReminder") or message.get("is_free_reminder")
               or message.get("kind") in {"reminder", "system_error", "win"}
               for message in (user, host)):
            continue
        content = user.get("content")
        answer = host.get("answer", host.get("content"))
        if not isinstance(content, str) or not content.strip() or answer not in {"是", "不是", "是也不是", "算是", "与此无关"}:
            continue
        pairs.append((content, answer))
    selected = pairs[-max_turns:] if max_turns else []

    def compose(turns):
        recent = "\n".join(f"玩家：{user}\n主持人：{answer}" for user, answer in turns) or "（无）"
        return f"{facts_prompt}\n[最近问答记录]\n{recent}\n{extra_instruction}\n[玩家的提问]{question}"

    if len(system_prompt) + len(compose([])) > max_chars:
        raise ContextLimitError("Fixed host context exceeds the input budget")
    user_prompt = compose(selected)
    while len(system_prompt) + len(user_prompt) > max_chars:
        selected = selected[1:]
        user_prompt = compose(selected)
    return ContextWindow(system_prompt, user_prompt, len(selected), len(system_prompt) + len(user_prompt))


def build_puzzle_context(*, soup, system_prompt: str, question: str,
                         history: list[dict], extra_instruction: str = "",
                         puzzle_version: str | None = None) -> ContextWindow:
    """Keep full truth; retrieve whole supplemental records only as evidence.

    Ranking never chooses the answer or rewrites facts/negation. The input is
    already the session's pinned Soup. Quality of this ranking is not assumed;
    TS-06/12 validate semantic retrieval and real-provider quality separately.
    """
    from .baselines import canonical_json
    core = (f"[当前汤的汤面]{soup.surface}\n\n"
            f"[完整汤底真相（不能向玩家透露）]\n{soup.bottom}\n")
    baseline = build_context(system_prompt=system_prompt, facts_prompt=core,
                             question=question, history=[], extra_instruction=extra_instruction)
    # Reserve room for history when present, and bound duplicate supplements.
    room = max(0, min(2000, 8000 - baseline.input_chars - (512 if history else 0)))
    if puzzle_version is not None:
        from .rag import retrieve_candidates
        selected = []
        for record in retrieve_candidates(question, soup, puzzle_version=puzzle_version):
            line = f"\n[{record.category}辅助证据 id={record.id} source={record.sourcePath}]" + record.payload
            if len(line) <= room:
                selected.append(line)
                room -= len(line)
        return build_context(system_prompt=system_prompt, facts_prompt=core + "".join(selected),
                             question=question, history=history, extra_instruction=extra_instruction)
    # Unversioned legacy callers keep complete record context without claiming
    # verified evidence IDs or deterministic/cache authority.
    lowered = question.lower()
    terms = {lowered[i:i + 2] for i in range(len(lowered) - 1)
             if lowered[i].isalnum() and lowered[i + 1].isalnum()}
    candidates = []
    for category, records in (
        ("事实", soup.truthItems or []), ("意象", soup.symbolMappings or []),
        ("易错点", soup.confusionPoints or []),
    ):
        for record in records:
            line = f"\n[{category}辅助证据]" + canonical_json(record.model_dump(mode="json", exclude_none=True))
            score = sum(term in line.lower() for term in terms)
            if score:
                candidates.append((score, len(candidates), line))
    selected = []
    for _score, _position, line in sorted(candidates, key=lambda item: (-item[0], item[1])):
        if len(line) <= room:
            selected.append(line)
            room -= len(line)
    return build_context(system_prompt=system_prompt, facts_prompt=core + "".join(selected),
                         question=question, history=history, extra_instruction=extra_instruction)
