"""Freeze checked scopes for future Agent steps; this module makes no calls."""
from typing import Annotated, Literal

from pydantic import Field, field_validator, model_validator

from . import baselines, feedback_store
from .audit_events import CanonicalId, Identity
from .feedback_contract import FeedbackError, PrivacyRecord, RowVersion, SanitizedInput, StrictFeedbackModel
from .host_evidence import build_evidence_catalog
from .rule_contract import rule_suspension_state
from .schemas import AnswerType, FeedbackSubmit, HostKind, HostResult, HostSource, HostVersions, ModelErrorCode

ToolName = Literal["get_turn_trace", "retrieve_truth", "find_rule_conflicts", "run_regression", "save_candidate_rule"]
TOOLS = frozenset({"get_turn_trace", "retrieve_truth", "find_rule_conflicts", "run_regression", "save_candidate_rule"})
Version = Annotated[str, Field(pattern=r"^[pr]1:[0-9a-f]{64}$")]
Digest = Annotated[str, Field(pattern=r"^[0-9a-f]{64}$")]


class NeedsHuman(FeedbackError):
    def __init__(self, code):
        super().__init__(code, 409)


class ScopedFact(StrictFeedbackModel):
    id: Annotated[str, Field(pattern=r"^f1:[0-9a-f]{64}$")]
    soupId: Identity
    puzzleVersion: Version
    sourcePath: Annotated[str, Field(min_length=1, max_length=200)]
    category: Literal["truth", "checkpoint", "confusion", "symbol", "metadata"]
    payload: Annotated[str, Field(min_length=1, max_length=32768)]


class ProgramDiagnostic(StrictFeedbackModel):
    kind: HostKind
    source: HostSource
    answer: AnswerType | None
    chargeable: bool
    errorCode: ModelErrorCode | None
    engineVersion: Annotated[str, Field(min_length=1, max_length=100)]
    normalizationVersion: Annotated[str, Field(min_length=1, max_length=100)]
    resultDigest: Digest

    @model_validator(mode="after")
    def coherent_program_result(self):
        HostResult(kind=self.kind, source=self.source, answer=self.answer, chargeable=self.chargeable,
            errorCode=self.errorCode, reply="Program diagnostic", versions=HostVersions(
                engineVersion=self.engineVersion, normalizationVersion=self.normalizationVersion))
        return self


class TaskContext(StrictFeedbackModel):
    schemaVersion: Literal[1] = 1
    feedbackId: CanonicalId
    sourceFeedbackVersion: RowVersion
    turnId: CanonicalId
    soupId: Identity
    observedPuzzleVersion: Version
    observedRuleVersion: Version
    baseRuleVersion: Version
    sanitizedInput: SanitizedInput
    inputDigest: Digest
    allowedTools: Annotated[tuple[ToolName, ...], Field(min_length=1, max_length=5)]
    factScope: Annotated[tuple[ScopedFact, ...], Field(min_length=1, max_length=256)]
    # Optional for old/manual pure contexts; freshly frozen linked tasks always
    # contain verified metadata. Old run manifests fail live equality rather
    # than being silently rebased or given invented diagnostics.
    programDiagnostic: ProgramDiagnostic | None = None

    @field_validator("schemaVersion", mode="before")
    @classmethod
    def real_schema_integer(cls, value):
        if type(value) is not int:
            raise ValueError("Real context schema version required")
        return value

    @model_validator(mode="after")
    def bounded_coherent_scope(self):
        if (len(set(self.allowedTools)) != len(self.allowedTools)
            or self.inputDigest != baselines.digest(self.sanitizedInput.model_dump(mode="json"))
            or any(fact.soupId != self.soupId or fact.puzzleVersion != self.observedPuzzleVersion for fact in self.factScope)
            or len(self.model_dump_json().encode()) > 262144):
            raise ValueError("Invalid frozen context scope")
        return self


def _freeze(conn, feedback_id, version, tools):
    row, view = feedback_store._item(conn, feedback_id)
    if row["row_version"] != version:
        raise NeedsHuman("feedback_context_stale")
    if view.status != "approved" or not view.safeForModel:
        raise NeedsHuman("feedback_permission_required")
    source = baselines.strict_json(row["source_json"])
    if type(source.get("schemaVersion")) is not int or source["schemaVersion"] != 1:
        raise NeedsHuman("feedback_context_invalid")
    if view.sourceState != "linked" or view.turnId is None:
        raise NeedsHuman("feedback_trace_required")
    privacy = source.get("privacy")
    checked_privacy = PrivacyRecord.model_validate_json(baselines.canonical_json(privacy))
    if (not checked_privacy.reviewedForPrivacy or checked_privacy.rowVersion != version
        or checked_privacy.sanitizedInput is None):
        raise NeedsHuman("feedback_permission_required")
    sanitized = checked_privacy.sanitizedInput
    request = FeedbackSubmit(soupId=view.soupId, turnId=view.turnId, question=view.question,
        hostAnswer=view.hostAnswer, expectedAnswer=view.expectedAnswer, reason=view.reason)
    actual_source, soup = feedback_store._source(conn, request)
    if {key: value for key, value in source.items() if key != "privacy"} != actual_source:
        raise NeedsHuman("feedback_context_invalid")
    turn = conn.execute("SELECT result_json FROM turns WHERE id=?", (view.turnId,)).fetchone()
    host = HostResult.model_validate_json(turn["result_json"])
    if baselines.digest(host.model_dump(mode="json")) != source["resultDigest"]:
        raise NeedsHuman("feedback_context_invalid")
    diagnostic = ProgramDiagnostic(kind=host.kind, source=host.source, answer=host.answer,
        chargeable=host.chargeable, errorCode=host.errorCode, engineVersion=host.versions.engineVersion,
        normalizationVersion=host.versions.normalizationVersion, resultDigest=source["resultDigest"])
    active = baselines.active_manifest(conn)
    if active["puzzleVersions"].get(soup.id) != source["puzzleVersion"]:
        raise NeedsHuman("feedback_puzzle_changed")
    for rule in (source["ruleVersion"], active["ruleVersion"]):
        if rule_suspension_state(conn, rule):
            raise NeedsHuman("rule_version_suspended")
    facts = tuple(ScopedFact(id=fact.id, soupId=fact.soupId, puzzleVersion=fact.puzzleVersion,
        sourcePath=fact.sourcePath, category=fact.category, payload=fact.payload)
        for fact in build_evidence_catalog(soup, source["puzzleVersion"]))
    return TaskContext(feedbackId=feedback_id, sourceFeedbackVersion=version, turnId=view.turnId, soupId=soup.id,
        observedPuzzleVersion=source["puzzleVersion"], observedRuleVersion=source["ruleVersion"], baseRuleVersion=active["ruleVersion"],
        sanitizedInput=sanitized, inputDigest=checked_privacy.inputDigest, allowedTools=tools, factScope=facts,
        programDiagnostic=diagnostic)


def freeze_task_context(feedback_id, expected_feedback_version, *, allowed_tools):
    if (type(allowed_tools) is not tuple or not allowed_tools or len(allowed_tools) > 5
        or any(tool not in TOOLS for tool in allowed_tools) or len(set(allowed_tools)) != len(allowed_tools)):
        raise NeedsHuman("feedback_tool_forbidden")
    try:
        with feedback_store._transaction(write=False) as conn:
            return _freeze(conn, feedback_id, expected_feedback_version, allowed_tools)
    except NeedsHuman:
        raise
    except Exception:
        raise NeedsHuman("feedback_context_invalid") from None


def verify_task_context(context, *, soup_id=None, turn_id=None, puzzle_version=None, base_rule_version=None, tool=None):
    try:
        checked = TaskContext.model_validate_json(context.model_dump_json())
        if (soup_id is not None and soup_id != checked.soupId or turn_id is not None and turn_id != checked.turnId
            or puzzle_version is not None and puzzle_version != checked.observedPuzzleVersion
            or base_rule_version is not None and base_rule_version != checked.baseRuleVersion
            or tool is not None and tool not in checked.allowedTools):
            raise NeedsHuman("feedback_scope_mismatch")
        with feedback_store._transaction(write=False) as conn:
            current = _freeze(conn, checked.feedbackId, checked.sourceFeedbackVersion, checked.allowedTools)
        if current != checked:
            raise NeedsHuman("feedback_context_stale")
    except NeedsHuman:
        raise
    except Exception:
        raise NeedsHuman("feedback_context_invalid") from None
