"""Conservative host-confirmed coverage, independent of narrative unlock scores.

No I/O/model calls, display-text parsing or reconstruction claim. The store
supplies committed typed rows; each proposition still needs full source scope.
"""
from dataclasses import dataclass
import re
from typing import get_args

from .baselines import SnapshotError
from .host_evidence import validate_puzzle_snapshot
from .host_rules import checkpoint_question_expectation
from .schemas import AnswerType, HostResult, HostVersions, Soup


SCORE_VERSION = "coverage-v1"


@dataclass(frozen=True, slots=True)
class ConfirmedTurn:
    question: str
    result: HostResult
    turnId: str
    history: tuple[tuple[str, AnswerType], ...] = ()

    def __post_init__(self):
        if not isinstance(self.question, str) or not self.question.strip():
            raise ValueError("A scored turn requires its original question")
        if not isinstance(self.turnId, str) or not self.turnId:
            raise ValueError("A scored turn requires an identity")
        if (type(self.history) is not tuple or any(type(pair) is not tuple or len(pair) != 2
                or not isinstance(pair[0], str) or pair[1] not in get_args(AnswerType)
                for pair in self.history)):
            raise ValueError("Scoring history requires immutable canonical pairs")
        if not isinstance(self.result, HostResult):
            raise ValueError("A scored turn requires a typed result")
        # Frozen Pydantic objects can still be made invalid with model_copy.
        checked = HostResult.model_validate(self.result.model_dump(mode="python"))
        object.__setattr__(self, "result", checked.model_copy(deep=True))


@dataclass(frozen=True, slots=True)
class CoverageResult:
    verifiedCoverage: int
    keyPointsCovered: tuple[str, ...]
    keyPointsMissing: tuple[str, ...]
    unknownTopics: tuple[str, ...]
    plotProgress: int | None
    unlockThresholdReached: bool
    excludedLegacyCount: int
    scoreVersion: str = SCORE_VERSION


def _plot_progress(soup: Soup, turns: tuple[ConfirmedTurn, ...]) -> int | None:
    if any(turn.result.kind == "win" for turn in turns):
        return 100
    if not soup.special_scoring:
        return None
    # Deliberately retained legacy thematic policy, now only fiction progress.
    # Positive/partial canonical answers can touch a theme; irrelevant, error,
    # reminders and legacy text cannot. This is NOT factual confirmation.
    eligible = tuple(turn for turn in turns if turn.result.kind == "answer" and turn.result.chargeable
                     and turn.result.source != "legacy" and turn.result.answer != "与此无关")
    themes = soup.checkpoints
    covered = sum(any(key.lower() in turn.question.lower() for turn in eligible
                      if cp.answer is not True or turn.result.answer != "不是"
                      for key in (cp.key, *(cp.aliases or ())) if key) for cp in themes)
    raw = round(covered / len(themes) * 100) if themes else 0
    return min(100, max(70, round(raw * 1.2))) if raw >= 50 else raw


def score_confirmed_coverage(soup: Soup, turns: tuple[ConfirmedTurn, ...], *,
                             versions: HostVersions, excluded_legacy_count: int = 0) -> CoverageResult:
    if (not isinstance(versions, HostVersions) or type(turns) is not tuple
            or type(excluded_legacy_count) is not int or excluded_legacy_count < 0):
        raise ValueError("Invalid scoring inputs")
    versions = HostVersions.model_validate(versions.model_dump(mode="python"))
    validate_puzzle_snapshot(soup, versions.puzzleVersion)
    if re.fullmatch(r"r1:[a-f0-9]{64}", versions.ruleVersion) is None:
        raise SnapshotError("Scoring requires a pinned rule release")
    checked = tuple(ConfirmedTurn(turn.question, turn.result, turn.turnId, turn.history)
                    for turn in turns if isinstance(turn, ConfirmedTurn))
    if len(checked) != len(turns) or len({turn.turnId for turn in checked}) != len(checked):
        raise SnapshotError("Invalid or duplicated scored turn identity")
    for turn in checked:
        source = turn.result.versions
        if ((source.puzzleVersion, source.ruleVersion) != (versions.puzzleVersion, versions.ruleVersion)
                or source.engineVersion not in {"host-v2", "host-v3"}
                or source.normalizationVersion != "exact-v1"):
            raise SnapshotError("Scored turn source identity mismatch")
    covered = set()
    for turn in checked:
        host = turn.result
        if (host.kind != "answer" or not host.chargeable or host.source == "legacy"
                or host.answer not in {"是", "不是"} or soup.always_yes):
            continue
        history = [{"role": role, "content": content}
                   for question, answer in turn.history
                   for role, content in (("user", question), ("host", answer))]
        for index, cp in enumerate(soup.checkpoints):
            if type(cp.answer) is bool and checkpoint_question_expectation(soup, index, turn.question, history) == host.answer:
                covered.add(index)
    known = tuple(index for index, cp in enumerate(soup.checkpoints) if type(cp.answer) is bool)
    plot = _plot_progress(soup, checked)
    return CoverageResult(
        round(len(covered) / len(known) * 100) if known else 0,
        tuple(soup.checkpoints[index].key for index in known if index in covered),
        tuple(soup.checkpoints[index].key for index in known if index not in covered),
        tuple(cp.key for cp in soup.checkpoints if cp.answer == "unknown"),
        plot, (plot >= 70 if plot is not None else (len(covered) / len(known) >= .7 if known else False)),
        excluded_legacy_count,
    )
