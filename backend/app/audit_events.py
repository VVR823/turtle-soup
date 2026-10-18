"""Private, immutable and bounded observations; never a business authority."""
import re
from typing import Annotated, Literal, get_args

from pydantic import BaseModel, ConfigDict, Field, StrictInt, field_validator, model_validator

from .schemas import HostKind, HostSource, HostVersions, ModelErrorCode

MAX_EVENT_BYTES = 16384
AuditEventType = Literal["http_attempt", "session_created", "turn_committed", "turn_expired", "evaluation_created",
    "feedback_submitted", "feedback_reviewed", "feedback_privacy", "feedback_imported", "rule_published", "rule_suspension", "rule_rolled_back", "agent_run", "agent_step", "rule_candidate", "candidate_reviewed", "candidate_published"]
AUDIT_EVENT_TYPES = frozenset(get_args(AuditEventType))
ROUTE_TEMPLATES = frozenset({
    "unmatched", "/health", "/api/config", "/api/soups", "/api/chat", "/api/evaluate",
    "/api/session/{session_id}", "/api/session/{session_id}/turns/{request_id}",
    "/api/feedback", "/api/feedback/admin", "/api/feedback/admin/{feedback_id}/approve",
    "/api/feedback/admin/{feedback_id}/reject", "/api/feedback/admin/merge-verified",
    "/api/feedback/admin/{feedback_id}/privacy",
    "/api/feedback/admin/agent-runs", "/api/feedback/admin/agent-runs/{run_id}",
    "/api/feedback/admin/agent-runs/{run_id}/cancel",
    "/api/feedback/admin/rule-candidates/{candidate_id}",
    "/api/feedback/admin/rule-candidates/{candidate_id}/approve",
    "/api/feedback/admin/rule-candidates/{candidate_id}/reject",
    "/api/feedback/admin/rule-candidates/{candidate_id}/publish",
    "/api/feedback/admin/rule-releases/rollback",
    "/api/feedback/admin/post-publication-regressions",
    "/api/audit/admin", "/api/audit/admin/status", "/api/audit/admin/recover",
    "/api/metrics/admin", "/api/metrics/admin/export",
})
UUID_PATTERN = re.compile(r"[0-9a-f]{8}(?:-[0-9a-f]{4}){3}-[0-9a-f]{12}\Z")
CanonicalId = Annotated[str, Field(min_length=36, max_length=36,
    pattern=r"^[0-9a-f]{8}(?:-[0-9a-f]{4}){3}-[0-9a-f]{12}$")]
Count = Annotated[StrictInt, Field(ge=0)]
Identity = Annotated[str, Field(min_length=1, max_length=200)]
EvidenceId = Annotated[str, Field(min_length=1, max_length=200)]
ReasonCode = HostKind | ModelErrorCode | Literal[
    "turn_expired", "turn_reserved", "turn_replay", "legacy_unverified", "session_created",
    "session_restored", "session_ended", "evaluation_created", "http_rejected", "http_error", "disconnected",
]


class StrictAuditModel(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True, frozen=True, allow_inf_nan=False)


class TokenUsage(StrictAuditModel):
    inputTokens: Count | None = None
    outputTokens: Count | None = None
    totalTokens: Count | None = None


def normalize_usage(metadata, *, format: Literal["compatible", "injected"]):
    """Copy three known fields, never coerce values or infer missing totals.

    Implausibly huge integers are invalid metadata, not a failed legal answer.
    The signed-64-bit ceiling bounds later sums/serialization and SQLite use.
    """
    keys = {"compatible": ("prompt_tokens", "completion_tokens", "total_tokens"),
            "injected": ("input_tokens", "output_tokens", "total_tokens")}
    if format not in keys:
        raise ValueError("Unregistered usage format")
    if metadata is None:
        return TokenUsage(), "unknown"
    if type(metadata) is not dict:
        return TokenUsage(), "invalid"
    values, invalid = [], False
    for name in keys[format]:
        value = metadata.get(name)
        if value is not None and (type(value) is not int or value < 0 or value.bit_length() > 63):
            invalid, value = True, None
        values.append(value)
    usage = TokenUsage(**dict(zip(("inputTokens", "outputTokens", "totalTokens"), values)))
    status = "invalid" if invalid else "known" if all(value is not None for value in values) else "partial" if any(value is not None for value in values) else "unknown"
    return usage, status


class ModelCallObservation(StrictAuditModel):
    ordinal: Annotated[StrictInt, Field(ge=1, le=2)]
    provider: Annotated[str, Field(pattern=r"^[A-Za-z0-9][A-Za-z0-9_.-]{0,63}$")] | None = None
    model: Annotated[str, Field(pattern=r"^[A-Za-z0-9][A-Za-z0-9_./:-]{0,199}$")] | None = None
    status: Literal["started", "succeeded", "failed"]
    errorCode: ModelErrorCode | None = None
    usage: TokenUsage = Field(default_factory=TokenUsage)
    usageStatus: Literal["known", "partial", "unknown", "invalid"] = "unknown"

    @field_validator("model")
    @classmethod
    def not_a_url(cls, value):
        if value and "://" in value:
            raise ValueError("Model identity cannot be a URL")
        return value

    @model_validator(mode="after")
    def consistent_observation(self):
        known = sum(value is not None for value in (self.usage.inputTokens, self.usage.outputTokens, self.usage.totalTokens))
        if ((self.usageStatus == "known" and known != 3) or (self.usageStatus == "unknown" and known != 0)
            or (self.usageStatus == "partial" and known not in (1, 2))
            or (self.status == "started" and self.usageStatus != "unknown")
            or ((self.errorCode is not None) != (self.status == "failed"))):
            raise ValueError("Model observation status and usage are inconsistent")
        return self


class AuditMetadata(StrictAuditModel):
    source: HostSource | None = None
    kind: HostKind | None = None
    charged: bool | None = None
    cacheHit: bool | None = None
    versions: HostVersions | None = None
    evidenceIds: Annotated[tuple[EvidenceId, ...], Field(max_length=128)] = ()
    evidenceCount: Count | None = None
    evidenceTruncated: bool = False
    metadataTruncated: bool = False
    reasonCode: ReasonCode | None = None
    trafficClass: Literal["test", "real", "synthetic", "legacy"] | None = None


class BusinessDetails(AuditMetadata):
    pass


class FeedbackBusinessDetails(StrictAuditModel):
    feedbackId: CanonicalId
    soupId: Identity
    rowVersion: Annotated[StrictInt, Field(ge=0, le=9223372036854775807)]
    action: Literal["submitted", "approved", "rejected", "privacy_granted", "privacy_revoked", "imported"]
    payloadDigest: Annotated[str, Field(pattern=r"^[0-9a-f]{64}$")]
    sourceState: Literal["unverified", "linked", "legacy"]
    trafficClass: Literal["test", "real", "synthetic", "legacy"]


class AgentBusinessDetails(StrictAuditModel):
    """Program metadata only, never model output, evidence text or approval."""
    runId: CanonicalId
    action: Literal["queued", "claimed", "heartbeat", "step_planned", "step_completed", "step_failed", "candidate_saved", "awaiting_review", "needs_human", "failed", "cancelled"]
    state: Literal["queued", "running", "awaiting_review", "needs_human", "failed", "cancelled"]
    rowVersion: Annotated[StrictInt, Field(ge=0, le=9223372036854775807)]
    payloadDigest: Annotated[str, Field(pattern=r"^[0-9a-f]{64}$", min_length=64, max_length=64)]
    modelAttemptsUsed: Annotated[StrictInt, Field(ge=0, le=10)]
    toolAttemptsUsed: Annotated[StrictInt, Field(ge=0, le=8)]
    trafficClass: Literal["test", "real", "synthetic"]
    operationKey: CanonicalId | None = None
    seq: Annotated[StrictInt, Field(ge=0, le=9223372036854775807)] | None = None
    candidateId: CanonicalId | None = None

    @model_validator(mode="after")
    def coherent_action(self):
        expected = self.action if self.action in {"queued", "awaiting_review", "needs_human", "failed", "cancelled"} else "running"
        if self.state != expected:
            raise ValueError("Agent action and state differ")
        if ((self.action in {"step_planned", "step_completed", "step_failed", "candidate_saved", "awaiting_review", "needs_human", "failed", "cancelled"}) != (self.operationKey is not None)
            or (self.operationKey is None) != (self.seq is None)):
            raise ValueError("Step event identity required")
        if (self.action in {"candidate_saved", "awaiting_review"}) != (self.candidateId is not None):
            raise ValueError("Candidate event identity required")
        return self


class RuleBusinessDetails(StrictAuditModel):
    operationKey: CanonicalId
    action: Literal["published"]
    fromRuleVersion: Annotated[str, Field(pattern=r"^r1:[0-9a-f]{64}$", min_length=67, max_length=67)]
    toRuleVersion: Annotated[str, Field(pattern=r"^r1:[0-9a-f]{64}$", min_length=67, max_length=67)]
    pointerVersion: Annotated[StrictInt, Field(ge=0, le=9223372036854775807)]
    soupId: Identity
    draftDigest: Annotated[str, Field(pattern=r"^[0-9a-f]{64}$", min_length=64, max_length=64)]
    candidateDigest: Annotated[str, Field(pattern=r"^[0-9a-f]{64}$", min_length=64, max_length=64)]
    regressionReportId: CanonicalId
    reportDigest: Annotated[str, Field(pattern=r"^[0-9a-f]{64}$", min_length=64, max_length=64)]
    suiteManifestDigest: Annotated[str, Field(pattern=r"^[0-9a-f]{64}$", min_length=64, max_length=64)]
    answerSupported: Literal[True]
    contextIndependent: Literal[True]
    reviewNote: Annotated[str, Field(min_length=1, max_length=1000)]
    trafficClass: Literal["test", "real", "synthetic", "legacy"]

    @field_validator("answerSupported", "contextIndependent", mode="before")
    @classmethod
    def actual_confirmation(cls, value):
        if value is not True:
            raise ValueError("Rule publication requires confirmation")
        return value


class RuleSuspensionDetails(StrictAuditModel):
    operationKey: CanonicalId
    ruleVersion: Annotated[str, Field(pattern=r"^r1:[0-9a-f]{64}$", min_length=67, max_length=67)]
    markerVersion: Annotated[StrictInt, Field(ge=0, le=9223372036854775807)]
    action: Literal["suspended", "resumed"]
    reason: Annotated[str, Field(min_length=1, max_length=1000)]
    trafficClass: Literal["test", "real", "synthetic", "legacy"]


class RuleRollbackDetails(StrictAuditModel):
    operationKey: CanonicalId
    fromRuleVersion: Annotated[str, Field(pattern=r"^r1:[0-9a-f]{64}$", min_length=67, max_length=67)]
    toRuleVersion: Annotated[str, Field(pattern=r"^r1:[0-9a-f]{64}$", min_length=67, max_length=67)]
    pointerVersion: Annotated[StrictInt, Field(ge=0, le=9223372036854775807)]
    blockedRuleVersion: Annotated[str, Field(pattern=r"^r1:[0-9a-f]{64}$", min_length=67, max_length=67)] | None = None
    markerVersion: Annotated[StrictInt, Field(ge=0, le=9223372036854775807)] | None = None
    reason: Annotated[str, Field(min_length=1, max_length=1000)]
    trafficClass: Literal["test", "real", "synthetic", "legacy"]

    @model_validator(mode="after")
    def coherent_block(self):
        if ((self.blockedRuleVersion is None) != (self.markerVersion is None)
            or self.blockedRuleVersion is not None and
                (self.blockedRuleVersion != self.fromRuleVersion or self.blockedRuleVersion == self.toRuleVersion)):
            raise ValueError("Rollback block and target mismatch")
        return self


class AttemptDetails(AuditMetadata):
    method: Annotated[str, Field(pattern=r"^[A-Z]{1,20}$")]
    routeTemplate: str
    statusCode: Annotated[StrictInt, Field(ge=100, le=599)] | None
    durationMs: Annotated[float, Field(ge=0)]
    outcome: Literal["success", "rejected", "error", "disconnected"]
    responseStarted: bool
    disconnected: bool
    replayed: bool = False
    modelCalls: Annotated[tuple[ModelCallObservation, ...], Field(max_length=2)] = ()
    modelCallsTruncated: bool = False
    usage: TokenUsage = Field(default_factory=TokenUsage)

    @field_validator("routeTemplate")
    @classmethod
    def registered_route(cls, value):
        if value not in ROUTE_TEMPLATES:
            raise ValueError("Only registered route templates are audit-safe")
        return value


class CandidateReviewDetails(StrictAuditModel):
    candidateId: CanonicalId
    runId: CanonicalId
    operationKey: CanonicalId
    action: Literal["approved", "rejected"]
    reviewVersion: Annotated[StrictInt, Field(ge=1, le=9223372036854775807)]
    candidateDigest: Annotated[str, Field(pattern=r"^[0-9a-f]{64}$", min_length=64, max_length=64)]
    reportDigest: Annotated[str, Field(pattern=r"^[0-9a-f]{64}$", min_length=64, max_length=64)]
    proofDigest: Annotated[str, Field(pattern=r"^[0-9a-f]{64}$", min_length=64, max_length=64)] | None
    answerSupported: Literal[True] | None
    contextIndependent: Literal[True] | None
    reviewNote: Annotated[str, Field(min_length=1, max_length=1000)]
    trafficClass: Literal["test", "real"]

    @field_validator("answerSupported", "contextIndependent", mode="before")
    @classmethod
    def real_manual_confirmation(cls, value):
        if value is not None and value is not True:
            raise ValueError("Real human confirmation required")
        return value

    @model_validator(mode="after")
    def actual_review_action(self):
        if not self.reviewNote.strip() or (self.action == "approved") != (self.answerSupported is True and self.contextIndependent is True):
            raise ValueError("Candidate review confirmation mismatch")
        if self.action == "rejected" and (self.answerSupported is not None or self.contextIndependent is not None):
            raise ValueError("Rejection is not approval")
        return self


class CandidatePublicationDetails(StrictAuditModel):
    candidateId: CanonicalId
    runId: CanonicalId
    operationKey: CanonicalId
    approvalOperationKey: CanonicalId
    reviewVersion: Annotated[StrictInt, Field(ge=1, le=9223372036854775807)]
    candidateDigest: Annotated[str, Field(pattern=r"^[0-9a-f]{64}$", min_length=64, max_length=64)]
    reportDigest: Annotated[str, Field(pattern=r"^[0-9a-f]{64}$", min_length=64, max_length=64)]
    proofDigest: Annotated[str, Field(pattern=r"^[0-9a-f]{64}$", min_length=64, max_length=64)]
    fromRuleVersion: Annotated[str, Field(pattern=r"^r1:[0-9a-f]{64}$", min_length=67, max_length=67)]
    toRuleVersion: Annotated[str, Field(pattern=r"^r1:[0-9a-f]{64}$", min_length=67, max_length=67)]
    pointerVersion: Annotated[StrictInt, Field(ge=1, le=9223372036854775807)]
    trafficClass: Literal["test", "real"]


EVENT_DETAIL_TYPES = {kind: BusinessDetails for kind in
    ("session_created", "turn_committed", "turn_expired", "evaluation_created")}
EVENT_DETAIL_TYPES.update({kind: FeedbackBusinessDetails for kind in
    ("feedback_submitted", "feedback_reviewed", "feedback_privacy", "feedback_imported")})
EVENT_DETAIL_TYPES["http_attempt"] = AttemptDetails
EVENT_DETAIL_TYPES["rule_published"] = RuleBusinessDetails
EVENT_DETAIL_TYPES["rule_suspension"] = RuleSuspensionDetails
EVENT_DETAIL_TYPES["rule_rolled_back"] = RuleRollbackDetails
EVENT_DETAIL_TYPES["agent_run"] = AgentBusinessDetails
EVENT_DETAIL_TYPES["agent_step"] = AgentBusinessDetails
EVENT_DETAIL_TYPES["rule_candidate"] = AgentBusinessDetails
EVENT_DETAIL_TYPES["candidate_reviewed"] = CandidateReviewDetails
EVENT_DETAIL_TYPES["candidate_published"] = CandidatePublicationDetails
FEEDBACK_EVENT_ACTIONS = {"feedback_submitted": {"submitted"}, "feedback_reviewed": {"approved", "rejected"},
    "feedback_privacy": {"privacy_granted", "privacy_revoked"}, "feedback_imported": {"imported"}}


class AuditEvent(StrictAuditModel):
    schemaVersion: Literal[1] = 1
    eventId: Identity
    eventType: AuditEventType
    requestId: Identity | None = None
    sessionId: Identity | None = None
    turnId: Identity | None = None
    runId: Identity | None = None
    createdAt: Annotated[float, Field(ge=0)]
    details: AttemptDetails | BusinessDetails | FeedbackBusinessDetails | RuleBusinessDetails | RuleSuspensionDetails | RuleRollbackDetails | AgentBusinessDetails | CandidateReviewDetails | CandidatePublicationDetails

    @field_validator("schemaVersion", mode="before")
    @classmethod
    def actual_integer_schema(cls, value):
        if type(value) is not int:
            raise ValueError("Schema version must be an integer")
        return value

    @field_validator("eventId", "requestId")
    @classmethod
    def canonical_uuid(cls, value):
        if value is not None and not UUID_PATTERN.fullmatch(value):
            raise ValueError("Audit/request identity must be canonical UUID text")
        return value

    @model_validator(mode="after")
    def bound_event(self):
        if type(self.details) is not EVENT_DETAIL_TYPES[self.eventType]:
            raise ValueError("Event type and details do not match")
        if isinstance(self.details, FeedbackBusinessDetails) and self.details.action not in FEEDBACK_EVENT_ACTIONS[self.eventType]:
            raise ValueError("Feedback action and event type do not match")
        if isinstance(self.details, AgentBusinessDetails):
            event_type = ("rule_candidate" if self.details.action == "candidate_saved" else "agent_step"
                if self.details.action in {"step_planned", "step_completed", "step_failed"} else "agent_run")
            if (self.runId != self.details.runId
                or self.eventType != event_type):
                raise ValueError("Agent event belongs to its exact run and action")
        if isinstance(self.details, (CandidateReviewDetails, CandidatePublicationDetails)) and self.runId != self.details.runId:
            raise ValueError("Candidate review event belongs to its exact run")
        if len(self.model_dump_json().encode("utf-8")) > MAX_EVENT_BYTES:
            raise ValueError("Audit event exceeds its byte budget")
        return self
