"""Internal durable decisions, never additional public model actions."""
from typing import Annotated, Literal

from pydantic import Field, StrictInt, field_validator, model_validator

from ..audit_events import CanonicalId
from ..rule_contract import Digest
from ..schemas import ModelErrorCode
from .contracts import StrictAgentModel, ToolAction, FinishAction


class DecisionIntent(StrictAgentModel):
    schemaVersion: Literal[1] = 1
    action: Literal["model_decision"] = "model_decision"
    promptDigest: Digest
    inputDigest: Digest
    correctionOf: CanonicalId | None = None

    @field_validator("schemaVersion", mode="before")
    @classmethod
    def real_schema(cls, value):
        if type(value) is not int:
            raise ValueError("Real schema required")
        return value


class DecisionResult(StrictAgentModel):
    schemaVersion: Literal[1] = 1
    status: Literal["valid", "invalid", "unavailable", "cancelled"]
    promptDigest: Digest
    inputDigest: Digest
    action: ToolAction | FinishAction | None
    errorCode: ModelErrorCode | None

    @field_validator("schemaVersion", mode="before")
    @classmethod
    def real_schema(cls, value):
        if type(value) is not int:
            raise ValueError("Real schema required")
        return value

    @model_validator(mode="after")
    def coherent(self):
        if self.status == "valid":
            if self.action is None or self.errorCode is not None:
                raise ValueError("Valid decision requires one action, no error")
        elif self.action is not None or self.errorCode is None:
            raise ValueError("Failed decision is not a model action")
        if ((self.status == "invalid") != (self.errorCode == "model_output_invalid")
            or (self.status == "cancelled") != (self.errorCode == "model_cancelled")):
            raise ValueError("Failure status mismatch")
        return self


StopReason = Literal["source_changed", "permission_revoked", "budget_exhausted", "deadline",
    "model_output_invalid", "tool_failed", "model_unavailable", "cancellation", "shutting_down",
    "missing_corpus", "context_too_large"]


class StopIntent(StrictAgentModel):
    schemaVersion: Literal[1] = 1
    action: Literal["server_stop"] = "server_stop"
    state: Literal["needs_human", "failed", "cancelled"]
    reason: StopReason
    ownerDigest: Digest | None

    @field_validator("schemaVersion", mode="before")
    @classmethod
    def real_schema(cls, value):
        if type(value) is not int:
            raise ValueError("Real schema required")
        return value

    @model_validator(mode="after")
    def coherent(self):
        if ((self.state == "cancelled") != (self.reason == "cancellation")
            or (self.state == "cancelled" and self.ownerDigest is not None)
            or (self.ownerDigest is None and self.state != "cancelled"
                and (self.state, self.reason) != ("needs_human", "source_changed"))):
            raise ValueError("Stop authority mismatch")
        return self


class StopResult(StrictAgentModel):
    schemaVersion: Literal[1] = 1
    runId: CanonicalId
    state: Literal["needs_human", "failed", "cancelled"]
    reason: StopReason

    @field_validator("schemaVersion", mode="before")
    @classmethod
    def real_schema(cls, value):
        if type(value) is not int:
            raise ValueError("Real schema required")
        return value


class StepSummary(StrictAgentModel):
    seq: Annotated[StrictInt, Field(ge=0, le=9223372036854775807)]
    action: Literal["tool", "finish", "model_decision", "server_stop"]
    state: Literal["planned", "completed", "failed"]
    tool: Literal["get_turn_trace", "retrieve_truth", "find_rule_conflicts", "run_regression", "save_candidate_rule"] | None = None


class AgentStatus(StrictAgentModel):
    id: CanonicalId
    state: Literal["queued", "running", "awaiting_review", "needs_human", "failed", "cancelled"]
    rowVersion: Annotated[StrictInt, Field(ge=0, le=9223372036854775807)]
    modelAttemptsUsed: Annotated[StrictInt, Field(ge=0, le=10)]
    toolAttemptsUsed: Annotated[StrictInt, Field(ge=0, le=8)]
    deadlineAt: Annotated[float, Field(ge=0)] | None
    reason: StopReason | None = None
    candidateId: CanonicalId | None = None
    steps: Annotated[tuple[StepSummary, ...], Field(max_length=32)] = ()
