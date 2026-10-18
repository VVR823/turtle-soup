"""Closed human review intents, never model-supplied publication authority."""
from typing import Annotated, Literal

from pydantic import Field, field_validator, model_validator

from .audit_events import CanonicalId
from .feedback_contract import FeedbackError, RowVersion, SanitizedInput, StrictFeedbackModel
from .rule_contract import Digest, ExactTarget, FactId, PuzzleVersion, ReviewReceipt, RollbackRequest, RuleVersion
from .agents.contracts import CandidateDraft, RegressionReport, checked_model
from .agents.decision_contracts import AgentStatus
from .schemas import AnswerType
from .task_context import ProgramDiagnostic, ScopedFact


class CandidateReviewError(FeedbackError):
    def __init__(self, code="candidate_input_invalid", status=422):
        super().__init__(code, status)


class CandidateOldTarget(ExactTarget):
    question: Annotated[str, Field(min_length=1, max_length=500)]
    answer: AnswerType


class CandidateSourceMessage(StrictFeedbackModel):
    messageId: Annotated[int, Field(strict=True, ge=1, le=9223372036854775807)]
    turnId: CanonicalId
    role: Literal["user", "host"]
    content: Annotated[str, Field(min_length=1, max_length=2000)]


class CandidateSourceContext(StrictFeedbackModel):
    inputKind: Literal["stored_private_source"] = "stored_private_source"
    scope: Literal["admin_review_only"] = "admin_review_only"
    sessionId: CanonicalId
    turnId: CanonicalId
    soupId: Annotated[str, Field(min_length=1, max_length=200)]
    puzzleVersion: PuzzleVersion
    ruleVersion: RuleVersion
    originalQuestion: Annotated[str, Field(min_length=1, max_length=500)]
    originalHostAnswer: Annotated[str, Field(min_length=1, max_length=2000)]
    messages: Annotated[tuple[CandidateSourceMessage, ...], Field(max_length=100)]
    contextDigest: Digest

    @model_validator(mode="after")
    def complete_bound_context(self):
        from .baselines import digest
        ids = [message.messageId for message in self.messages]
        if (len(ids) % 2 or len(set(ids)) != len(ids) or ids != sorted(ids)
            or any(message.turnId == self.turnId for message in self.messages)
            or len({message.turnId for message in self.messages}) != len(ids) // 2
            or any((self.messages[n].role, self.messages[n + 1].role) != ("user", "host")
                or self.messages[n].turnId != self.messages[n + 1].turnId for n in range(0, len(ids), 2))
            or self.contextDigest != digest(self.model_dump(mode="json", exclude={"contextDigest"}))
            or len(self.model_dump_json().encode("utf-8")) > 131072):
            raise ValueError("Complete source-bound human context required")
        return self


class CandidateReviewMaterial(StrictFeedbackModel):
    inputKind: Literal["user_claim"] = "user_claim"
    draftKind: Literal["model_summary"] = "model_summary"
    sanitizedInput: SanitizedInput
    sourceContext: CandidateSourceContext
    programDiagnostic: ProgramDiagnostic
    draft: CandidateDraft
    factScope: Annotated[tuple[ScopedFact, ...], Field(min_length=1, max_length=256)]
    highlightedFactIds: Annotated[tuple[FactId, ...], Field(min_length=1, max_length=256)]
    oldTarget: CandidateOldTarget | None
    report: RegressionReport


CandidateBlocker = Literal["candidate_source_stale", "candidate_base_changed", "candidate_suite_changed",
    "candidate_suite_unavailable", "candidate_corpus_missing", "candidate_corpus_invalid", "candidate_detail_too_large", "candidate_terminal",
    "candidate_context_unavailable"]


class CandidateReviewDetail(StrictFeedbackModel):
    schemaVersion: Literal[1] = 1
    candidateId: CanonicalId
    runId: CanonicalId
    candidateStatus: Literal["pending", "approved", "rejected", "published"]
    reviewVersion: RowVersion
    agentStatus: AgentStatus
    activeRuleVersion: RuleVersion
    activePointerVersion: RowVersion
    proofDigest: Digest | None
    availability: Literal["ready", "historical", "stale", "unavailable"]
    blockers: Annotated[tuple[CandidateBlocker, ...], Field(max_length=6)]
    material: CandidateReviewMaterial | None
    review: "ReviewState | None"
    publishedRuleVersion: RuleVersion | None

    @field_validator("schemaVersion", mode="before")
    @classmethod
    def real_schema(cls, value):
        if type(value) is not int or value != 1:
            raise ValueError("Real detail schema required")
        return value

    @model_validator(mode="after")
    def proof_availability(self):
        if (self.agentStatus.id != self.runId or self.agentStatus.candidateId != self.candidateId
            or self.agentStatus.state != "awaiting_review"
            or (self.availability == "ready") != (self.proofDigest is not None)
            or (self.availability in {"ready", "historical"}) != (self.material is not None)
            or (self.availability == "ready") != (not self.blockers)):
            raise ValueError("Detail proof/state disagreement")
        return self


class _ReviewIntent(StrictFeedbackModel):
    operationKey: CanonicalId
    expectedReviewVersion: RowVersion


class CandidateReject(_ReviewIntent):
    reviewNote: str

    @field_validator("reviewNote")
    @classmethod
    def nonblank_note(cls, value):
        if not value.strip() or not 1 <= len(value) <= 1000:
            raise ValueError("Nonblank review note of 1–1000 characters required")
        return value


class CandidateApprove(CandidateReject):
    expectedProofDigest: Digest
    answerSupported: Literal[True]
    contextIndependent: Literal[True]

    @field_validator("answerSupported", "contextIndependent", mode="before")
    @classmethod
    def human_confirmation(cls, value):
        if value is not True:
            raise ValueError("Explicit human confirmation required")
        return value


class CandidatePublish(_ReviewIntent):
    expectedProofDigest: Digest
    expectedRuleVersion: RuleVersion
    expectedPointerVersion: RowVersion


class CandidateRollback(RollbackRequest):
    @field_validator("reason")
    @classmethod
    def nonblank_reason(cls, value):
        if not value.strip() or not 1 <= len(value) <= 1000:
            raise ValueError("Nonblank rollback reason of 1–1000 characters required")
        return value

    @model_validator(mode="after")
    def real_version_transition(self):
        if self.targetRuleVersion == self.expectedRuleVersion:
            raise ValueError("Rollback requires a different verified target version")
        return self


class _CandidateProofModel(StrictFeedbackModel):
    @field_validator("schemaVersion", mode="before", check_fields=False)
    @classmethod
    def real_proof_schema(cls, value):
        if type(value) is not int or value != 1:
            raise ValueError("Real proof schema integer required")
        return value


class AgentRunSummary(StrictFeedbackModel):
    id: CanonicalId
    feedbackId: CanonicalId
    state: Literal["queued", "running", "awaiting_review", "needs_human", "failed", "cancelled"]
    rowVersion: RowVersion
    createdAt: Annotated[float, Field(ge=0)]
    deadlineAt: Annotated[float, Field(ge=0)] | None
    modelAttemptsUsed: Annotated[int, Field(strict=True, ge=0, le=10)]
    toolAttemptsUsed: Annotated[int, Field(strict=True, ge=0, le=8)]
    candidateId: CanonicalId | None
    candidateStatus: Literal["pending", "approved", "rejected", "published"] | None

    @field_validator("createdAt", "deadlineAt", mode="before")
    @classmethod
    def real_timestamp(cls, value):
        if value is not None and type(value) not in (int, float):
            raise ValueError("Real timestamp required")
        return value

    @model_validator(mode="after")
    def summary_coherence(self):
        if ((self.candidateId is None) != (self.candidateStatus is None)
            or (self.state == "awaiting_review" and self.candidateId is None)
            or (self.candidateStatus in {"approved", "rejected", "published"} and self.state != "awaiting_review")
            or (self.state == "queued" and (self.deadlineAt is not None or self.modelAttemptsUsed
                or self.toolAttemptsUsed or self.candidateId is not None))
            or (self.state in {"running", "awaiting_review"} and self.deadlineAt is None)
            or (self.deadlineAt is not None and self.deadlineAt < self.createdAt)):
            raise ValueError("Run summary disagreement")
        return self


class AgentRunPage(_CandidateProofModel):
    schemaVersion: Literal[1] = 1
    runs: Annotated[tuple[AgentRunSummary, ...], Field(max_length=100)]
    nextCursor: Annotated[str, Field(min_length=1, max_length=512)] | None


class CandidateOperationResult(_CandidateProofModel):
    schemaVersion: Literal[1] = 1
    candidateId: CanonicalId
    operationKey: CanonicalId
    action: Literal["approved", "rejected", "published"]
    reviewVersion: Annotated[int, Field(strict=True, ge=1, le=9223372036854775807)]
    candidateStatus: Literal["approved", "rejected", "published"]
    publishedRuleVersion: RuleVersion | None = None

    @model_validator(mode="after")
    def acknowledgement(self):
        if self.action != self.candidateStatus or (self.action == "published") != (self.publishedRuleVersion is not None):
            raise ValueError("Operation acknowledgement disagreement")
        return self


class ReviewState(_CandidateProofModel):
    schemaVersion: Literal[1] = 1
    candidateId: CanonicalId
    status: Literal["approved", "rejected", "published"]
    candidateDigest: Digest
    candidateDraftDigest: Digest
    publicationDraftDigest: Digest
    reportId: CanonicalId
    reportDigest: Digest
    suiteManifestDigest: Digest
    contextDigest: Digest
    sourceFeedbackVersion: RowVersion
    targetRuleDigest: Digest | None
    proofDigest: Digest | None
    reviewReceipt: ReviewReceipt | None
    approvalOperationKey: CanonicalId | None
    reviewNote: Annotated[str, Field(min_length=1, max_length=1000)]
    reviewedAt: Annotated[float, Field(ge=0)]
    lastOperationKey: CanonicalId
    publishedRuleVersion: RuleVersion | None = None

    @model_validator(mode="after")
    def receipt_coherence(self):
        receipt = self.reviewReceipt
        if not self.reviewNote.strip() or ((receipt is None) != (self.approvalOperationKey is None)):
            raise ValueError("Closed review metadata required")
        if self.status in {"approved", "published"} and (receipt is None or self.proofDigest is None):
            raise ValueError("Real approved receipt required")
        if (self.status == "published") != (self.publishedRuleVersion is not None):
            raise ValueError("Publication history disagreement")
        if receipt is not None and (not receipt.answerSupported or not receipt.contextIndependent
            or not receipt.reviewNote.strip() or receipt.draftDigest != self.publicationDraftDigest
            or receipt.candidateDigest != self.candidateDigest or receipt.regressionReportId != self.reportId
            or receipt.reportDigest != self.reportDigest or receipt.suiteManifestDigest != self.suiteManifestDigest):
            raise ValueError("Review metadata and receipt mismatch")
        return self


class CandidateReviewIntent(_CandidateProofModel):
    schemaVersion: Literal[1] = 1
    candidateId: CanonicalId
    action: Literal["approved", "rejected", "published"]
    request: CandidateApprove | CandidateReject | CandidatePublish

    @model_validator(mode="after")
    def action_contract(self):
        expected = {"approved": CandidateApprove, "rejected": CandidateReject, "published": CandidatePublish}[self.action]
        if type(self.request) is not expected:
            raise ValueError("Intent action/request mismatch")
        return self


class CandidateOperationReceipt(_CandidateProofModel):
    schemaVersion: Literal[1] = 1
    intent: CandidateReviewIntent
    intentDigest: Digest
    state: ReviewState
    result: CandidateOperationResult

    @model_validator(mode="after")
    def bound_operation(self):
        from .baselines import digest
        intent, state, result = self.intent, self.state, self.result
        request = intent.request
        if (self.intentDigest != digest(intent.model_dump(mode="json"))
            or result.candidateId != intent.candidateId or state.candidateId != intent.candidateId
            or result.operationKey != request.operationKey or state.lastOperationKey != request.operationKey
            or result.action != intent.action or state.status != intent.action
            or result.reviewVersion != request.expectedReviewVersion + 1
            or result.publishedRuleVersion != state.publishedRuleVersion):
            raise ValueError("Operation receipt binding mismatch")
        if intent.action == "approved" and (state.approvalOperationKey != request.operationKey
            or state.proofDigest != request.expectedProofDigest or state.reviewNote != request.reviewNote
            or state.reviewReceipt.reviewNote != request.reviewNote):
            raise ValueError("Approval receipt differs from explicit intent")
        if intent.action == "rejected" and state.reviewNote != request.reviewNote:
            raise ValueError("Rejection receipt differs from explicit intent")
        if intent.action == "published" and (state.proofDigest != request.expectedProofDigest
            or state.reviewReceipt.baseRuleVersion != request.expectedRuleVersion):
            raise ValueError("Publication receipt differs from explicit intent")
        return self


def checked_candidate_request(model, value):
    """Trusted closed consumer choice, strict UTF-8 body and copied-instance check."""
    if model not in (CandidateApprove, CandidateReject, CandidatePublish, CandidateRollback):
        raise TypeError("Closed candidate request contract required")
    try:
        return checked_model(model, value, max_bytes=32768)
    except Exception:
        raise CandidateReviewError() from None


CandidateReviewDetail.model_rebuild()
