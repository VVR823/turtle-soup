"""Closed model action vocabulary, not execution or human review authority."""
from typing import Annotated, Literal

from pydantic import BaseModel, ConfigDict, Field, StrictInt, TypeAdapter, field_validator, model_validator

from .. import baselines
from ..audit_events import CanonicalId, Identity
from ..question_normalization import normalize_exact_question
from ..rule_contract import Digest, FactId, PuzzleVersion, RuleVersion
from ..schemas import AnswerType
from ..task_context import TaskContext

ACTION_BYTES = 32768
Count = Annotated[StrictInt, Field(ge=0)]


class StrictAgentModel(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True, frozen=True, allow_inf_nan=False)


class AgentError(RuntimeError):
    def __init__(self, code="agent_input_invalid", status=422):
        self.code, self.status = code, status
        super().__init__(code)


def checked_model(model, value, *, max_bytes=ACTION_BYTES):
    """Every consumer revalidates; model_copy is not a validation boundary.

    Serializer failures are errors, never warnings containing private values.
    JSON duplicate keys are checked before Pydantic's otherwise permissive parser.
    """
    try:
        if isinstance(value, BaseModel):
            raw = value.model_dump_json(warnings="error")
        elif type(value) is str:
            raw = value
        elif type(value) is dict:
            raw = baselines.canonical_json(value)
        else:
            raise ValueError("Object required")
        if len(raw.encode("utf-8")) > max_bytes:
            raise ValueError("Input too large")
        body = baselines.strict_json(raw)
        if type(body) is not dict:
            raise ValueError("Object required")
        return model.model_validate_json(baselines.canonical_json(body))
    except Exception:
        raise AgentError() from None


class CandidateDraft(StrictAgentModel):
    schemaVersion: Literal[1] = 1
    type: Literal["exact_qa"] = "exact_qa"
    operation: Literal["add", "replace"]
    targetRuleDigest: Digest | None = None
    soupId: Identity
    puzzleVersion: PuzzleVersion
    baseRuleVersion: RuleVersion
    question: Annotated[str, Field(min_length=1, max_length=500)]
    normalizationVersion: Literal["exact-v1"] = "exact-v1"
    answer: AnswerType
    factIds: Annotated[tuple[FactId, ...], Field(min_length=1, max_length=32)]
    evidenceSummary: Annotated[str, Field(min_length=1, max_length=1000)]

    @field_validator("schemaVersion", mode="before")
    @classmethod
    def real_schema(cls, value):
        if type(value) is not int:
            raise ValueError("Real schema required")
        return value

    @field_validator("question", "evidenceSummary", "soupId")
    @classmethod
    def nonblank(cls, value):
        if not value.strip():
            raise ValueError("Nonblank field required")
        return value

    @model_validator(mode="after")
    def coherent(self):
        if ((self.operation == "replace") != (self.targetRuleDigest is not None)
            or len(set(self.factIds)) != len(self.factIds)):
            raise ValueError("Exact draft identity mismatch")
        normalize_exact_question(self.question)
        return self

    @property
    def canonicalQuestionKey(self):
        return normalize_exact_question(self.question)


def checked_draft(value):
    return checked_model(CandidateDraft, value)


def draft_digest(value):
    return baselines.digest(checked_draft(value).model_dump(mode="json"))


class GetTurnTraceArgs(StrictAgentModel):
    turnId: CanonicalId


class RetrieveTruthArgs(StrictAgentModel):
    soupId: Identity
    puzzleVersion: PuzzleVersion
    query: Annotated[str, Field(min_length=1, max_length=500)]

    @field_validator("query", "soupId")
    @classmethod
    def nonblank(cls, value):
        if not value.strip():
            raise ValueError("Nonblank query required")
        return value


class FindRuleConflictsArgs(StrictAgentModel):
    baseRuleVersion: RuleVersion
    draft: CandidateDraft


class RunRegressionArgs(StrictAgentModel):
    draft: CandidateDraft


class SaveCandidateRuleArgs(StrictAgentModel):
    draft: CandidateDraft
    regressionReportId: CanonicalId


class GetTurnTraceAction(StrictAgentModel):
    action: Literal["tool"]
    tool: Literal["get_turn_trace"]
    arguments: GetTurnTraceArgs


class RetrieveTruthAction(StrictAgentModel):
    action: Literal["tool"]
    tool: Literal["retrieve_truth"]
    arguments: RetrieveTruthArgs


class FindRuleConflictsAction(StrictAgentModel):
    action: Literal["tool"]
    tool: Literal["find_rule_conflicts"]
    arguments: FindRuleConflictsArgs


class RunRegressionAction(StrictAgentModel):
    action: Literal["tool"]
    tool: Literal["run_regression"]
    arguments: RunRegressionArgs


class SaveCandidateRuleAction(StrictAgentModel):
    action: Literal["tool"]
    tool: Literal["save_candidate_rule"]
    arguments: SaveCandidateRuleArgs


ToolAction = Annotated[GetTurnTraceAction | RetrieveTruthAction | FindRuleConflictsAction
    | RunRegressionAction | SaveCandidateRuleAction, Field(discriminator="tool")]
_TOOL_ADAPTER = TypeAdapter(ToolAction)


class FinishAction(StrictAgentModel):
    action: Literal["finish"]
    candidateId: CanonicalId | None = None
    needsHumanReason: Annotated[str, Field(min_length=1, max_length=1000)] | None = None

    @model_validator(mode="after")
    def exactly_one(self):
        if (self.candidateId is None) == (self.needsHumanReason is None):
            raise ValueError("Exactly one finish outcome required")
        if self.needsHumanReason is not None and not self.needsHumanReason.strip():
            raise ValueError("Nonblank reason required")
        return self


class RetryCount(StrictAgentModel):
    kind: Literal["model", "tool"]
    keyDigest: Digest
    used: Annotated[StrictInt, Field(ge=0, le=1)]


class AgentManifest(StrictAgentModel):
    schemaVersion: Literal[1] = 1
    policyVersion: Literal["repair-tools-v1"] = "repair-tools-v1"
    context: TaskContext
    contextDigest: Digest
    suiteManifestDigest: Digest | None = None
    trafficClass: Literal["test", "synthetic", "real"]

    @field_validator("schemaVersion", mode="before")
    @classmethod
    def real_schema(cls, value):
        if type(value) is not int:
            raise ValueError("Real schema required")
        return value

    @model_validator(mode="after")
    def bound_context(self):
        if self.contextDigest != baselines.digest(self.context.model_dump(mode="json")):
            raise ValueError("Context proof mismatch")
        if len(self.model_dump_json(warnings="error").encode("utf-8")) > 524288:
            raise ValueError("Manifest too large")
        return self


class ExecutionIdentity(StrictAgentModel):
    """Trusted server input only. Never accepted inside a ToolAction."""
    runId: CanonicalId
    operationKey: CanonicalId
    leaseToken: CanonicalId
    seq: Annotated[StrictInt, Field(ge=0, le=9223372036854775807)]


class RegressionCaseResult(StrictAgentModel):
    caseId: CanonicalId
    suite: Literal["dev_regression", "fixed_safety"]
    passed: bool
    code: Literal["passed", "counterexample", "needs_corpus", "deadline", "truncated", "probe_failed"]

    @model_validator(mode="after")
    def actual_outcome(self):
        if self.passed != (self.code == "passed"):
            raise ValueError("Case outcome mismatch")
        return self


class RegressionReport(StrictAgentModel):
    schemaVersion: Literal[1] = 1
    reportId: CanonicalId
    runId: CanonicalId
    draftDigest: Digest
    contextDigest: Digest
    suiteManifestDigest: Digest
    puzzleVersion: PuzzleVersion
    baseRuleVersion: RuleVersion
    evidenceKind: Literal["synthetic_fixture", "deterministic_regression"]
    status: Literal["complete", "incomplete", "failed"]
    inputCaseCount: Annotated[StrictInt, Field(ge=0, le=128)]
    attemptedCaseCount: Annotated[StrictInt, Field(ge=0, le=128)]
    passedCaseCount: Annotated[StrictInt, Field(ge=0, le=128)]
    elapsedSeconds: Annotated[float, Field(ge=0)]
    truncated: bool
    cleanupConfirmed: bool
    caseResults: Annotated[tuple[RegressionCaseResult, ...], Field(max_length=128)]

    @field_validator("schemaVersion", mode="before")
    @classmethod
    def real_schema(cls, value):
        if type(value) is not int:
            raise ValueError("Real schema required")
        return value

    @model_validator(mode="after")
    def complete_denominator(self):
        if (self.attemptedCaseCount != len(self.caseResults)
            or self.passedCaseCount != sum(r.passed for r in self.caseResults)
            or self.attemptedCaseCount > self.inputCaseCount
            or len({r.caseId for r in self.caseResults}) != len(self.caseResults)):
            raise ValueError("Actual case denominator mismatch")
        if self.status == "complete" and (self.inputCaseCount == 0
            or self.passedCaseCount != self.inputCaseCount or self.truncated
            or not self.cleanupConfirmed or self.elapsedSeconds > 5.0):
            raise ValueError("Incomplete result cannot pass")
        if self.status == "failed" and not any(not r.passed for r in self.caseResults):
            raise ValueError("Failure requires a known failing result")
        if len(self.model_dump_json(warnings="error").encode("utf-8")) > ACTION_BYTES:
            raise ValueError("Report too large")
        return self


def candidate_digest(draft, *, run_id, report_id, report_digest):
    # Hash identity is integrity evidence, NOT permission or a human receipt.
    try:
        run = TypeAdapter(CanonicalId).validate_python(run_id, strict=True)
        report = TypeAdapter(CanonicalId).validate_python(report_id, strict=True)
        proof = TypeAdapter(Digest).validate_python(report_digest, strict=True)
        return baselines.digest(dict(draft=checked_draft(draft).model_dump(mode="json"),
            runId=run, regressionReportId=report, reportDigest=proof))
    except Exception:
        raise AgentError() from None


class CandidateRecord(StrictAgentModel):
    schemaVersion: Literal[1] = 1
    id: CanonicalId
    runId: CanonicalId
    draft: CandidateDraft
    regressionReportId: CanonicalId
    reportDigest: Digest
    candidateDigest: Digest
    status: Literal["pending"] = "pending"
    createdAt: Annotated[float, Field(ge=0)]

    @field_validator("schemaVersion", mode="before")
    @classmethod
    def real_schema(cls, value):
        if type(value) is not int:
            raise ValueError("Real schema required")
        return value

    @model_validator(mode="after")
    def bound_body(self):
        if self.candidateDigest != candidate_digest(self.draft, run_id=self.runId,
            report_id=self.regressionReportId, report_digest=self.reportDigest):
            raise ValueError("Candidate body proof mismatch")
        if len(self.model_dump_json(warnings="error").encode("utf-8")) > ACTION_BYTES:
            raise ValueError("Candidate too large")
        return self


class AgentCheckpoint(StrictAgentModel):
    schemaVersion: Literal[1] = 1
    budgetPolicyVersion: Literal["repair-budget-v1"] = "repair-budget-v1"
    modelAttemptLimit: Literal[10] = 10
    toolAttemptLimit: Literal[8] = 8
    totalSeconds: Literal[180] = 180
    modelAttemptsUsed: Annotated[StrictInt, Field(ge=0, le=10)] = 0
    toolAttemptsUsed: Annotated[StrictInt, Field(ge=0, le=8)] = 0
    firstStartedAt: Annotated[float, Field(ge=0)] | None = None
    deadlineAt: Annotated[float, Field(ge=0)] | None = None
    retryCounts: Annotated[tuple[RetryCount, ...], Field(max_length=18)] = ()

    @field_validator("schemaVersion", "modelAttemptLimit", "toolAttemptLimit", "totalSeconds", mode="before")
    @classmethod
    def real_integer_policy(cls, value):
        if type(value) is not int:
            raise ValueError("Real integer policy required")
        return value

    @model_validator(mode="after")
    def conserved(self):
        if (self.firstStartedAt is None) != (self.deadlineAt is None):
            raise ValueError("Complete deadline required")
        if self.firstStartedAt is None:
            if self.modelAttemptsUsed or self.toolAttemptsUsed or self.retryCounts:
                raise ValueError("Unstarted budget cannot be consumed")
        elif self.deadlineAt - self.firstStartedAt != 180.0:
            raise ValueError("Deadline may not refresh")
        if len({(r.kind, r.keyDigest) for r in self.retryCounts}) != len(self.retryCounts):
            raise ValueError("Duplicate retry counter")
        for kind, used in (("model", self.modelAttemptsUsed), ("tool", self.toolAttemptsUsed)):
            if sum(r.used for r in self.retryCounts if r.kind == kind) > used:
                raise ValueError("Unaccounted retry")
        return self


def parse_tool_action(value):
    # Adapter has a different method name than BaseModel. Keep one strict
    # input/byte/warning boundary, then validate the closed discriminated union.
    class Boundary:
        model_validate_json = staticmethod(_TOOL_ADAPTER.validate_json)
    return checked_model(Boundary, value)


def parse_agent_action(value):
    try:
        raw = value.model_dump_json(warnings="error") if isinstance(value, BaseModel) else value
        if type(raw) is not str or len(raw.encode("utf-8")) > ACTION_BYTES:
            raise ValueError("Bounded JSON required")
        body = baselines.strict_json(raw)
        if type(body) is not dict:
            raise ValueError("Object required")
        return checked_model(FinishAction, body) if body.get("action") == "finish" else parse_tool_action(raw)
    except AgentError:
        raise
    except Exception:
        raise AgentError() from None
