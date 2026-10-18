"""Private feedback is a player's claim, not a verified rule or permission."""
from typing import Annotated, Literal
from datetime import datetime
import math

from pydantic import BaseModel, ConfigDict, Field, StrictInt, field_validator, model_validator

from .audit_events import CanonicalId, Identity

RowVersion = Annotated[StrictInt, Field(ge=0, le=9223372036854775807)]
FeedbackId = CanonicalId
FeedbackStatus = Literal["pending", "approved", "rejected"]
SourceState = Literal["unverified", "linked", "legacy"]


class StrictFeedbackModel(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True, frozen=True, allow_inf_nan=False)


class FeedbackReview(StrictFeedbackModel):
    expectedRowVersion: RowVersion


class SanitizedInput(StrictFeedbackModel):
    question: Annotated[str, Field(min_length=1, max_length=500)]
    hostAnswer: Annotated[str, Field(min_length=1, max_length=100)]
    expectedClaim: Annotated[str, Field(min_length=1, max_length=100)]
    reason: Annotated[str, Field(max_length=2000)] | None = None


class PrivacyReview(StrictFeedbackModel):
    safeForModel: bool
    reviewedForPrivacy: bool = False
    reviewNote: Annotated[str, Field(min_length=1, max_length=1000)]
    sanitizedQuestion: Annotated[str, Field(min_length=1, max_length=500)] | None = None
    sanitizedHostAnswer: Annotated[str, Field(min_length=1, max_length=100)] | None = None
    sanitizedExpectedClaim: Annotated[str, Field(min_length=1, max_length=100)] | None = None
    sanitizedReason: Annotated[str, Field(max_length=2000)] | None = None

    @model_validator(mode="after")
    def explicit_manual_clearance(self):
        if self.safeForModel and (not self.reviewedForPrivacy or any(value is None for value in
            (self.sanitizedQuestion, self.sanitizedHostAnswer, self.sanitizedExpectedClaim))):
            raise ValueError("Manual complete privacy review required")
        return self


class PrivacyRecord(StrictFeedbackModel):
    schemaVersion: Literal[1] = 1
    reviewedForPrivacy: bool
    reviewNote: Annotated[str, Field(min_length=1, max_length=1000)]
    reviewedAt: Annotated[str, Field(min_length=1, max_length=40)]
    rowVersion: RowVersion
    sanitizedInput: SanitizedInput | None
    inputDigest: Annotated[str, Field(pattern=r"^[0-9a-f]{64}$")] | None

    @field_validator("schemaVersion", mode="before")
    @classmethod
    def integer_schema(cls, value):
        if type(value) is not int:
            raise ValueError("Real schema version required")
        return value

    @field_validator("reviewedAt")
    @classmethod
    def valid_utc_time(cls, value):
        date = datetime.fromisoformat(value.replace("Z", "+00:00"))
        if date.tzinfo is None or not math.isfinite(date.timestamp()) or date.timestamp() < 0:
            raise ValueError("Verified review timestamp required")
        return value

    @model_validator(mode="after")
    def matching_digest(self):
        from .baselines import digest
        if (self.sanitizedInput is None) != (self.inputDigest is None):
            raise ValueError("Incomplete sanitized record")
        if self.sanitizedInput is not None and self.inputDigest != digest(self.sanitizedInput.model_dump(mode="json")):
            raise ValueError("Sanitized input digest mismatch")
        return self


def feedback_required_fields_valid(value) -> bool:
    """Validity for new trust decisions, not a destructive legacy read filter."""
    return all(isinstance(getattr(value, field, None), str) and getattr(value, field).strip()
        for field in ("soupId", "question", "hostAnswer", "expectedAnswer"))


class FeedbackView(StrictFeedbackModel):
    # Historical bounded blank strings remain inspectable, but cannot be
    # approved or granted model permission. Incoming submission is stricter.
    id: FeedbackId
    ts: Annotated[str, Field(min_length=1, max_length=40)]
    soupId: Identity
    soupTitle: Annotated[str, Field(max_length=500)] | None = None
    turnId: FeedbackId | None = None
    question: Annotated[str, Field(min_length=1, max_length=500)]
    hostAnswer: Annotated[str, Field(min_length=1, max_length=100)]
    expectedAnswer: Annotated[str, Field(min_length=1, max_length=100)]
    reason: Annotated[str, Field(max_length=2000)] | None = None
    status: FeedbackStatus = "pending"
    reviewedAt: Annotated[str, Field(min_length=1, max_length=40)] | None = None
    mergedAt: None = None
    mergedAnswer: None = None
    rowVersion: RowVersion
    safeForModel: bool
    sourceState: SourceState


class FeedbackPage(StrictFeedbackModel):
    feedbacks: Annotated[tuple[FeedbackView, ...], Field(max_length=100)]
    totalInRange: Annotated[StrictInt, Field(ge=0)]
    nextCursor: Annotated[str, Field(min_length=1, max_length=512)] | None


class FeedbackError(RuntimeError):
    def __init__(self, code: str, status: int):
        self.code, self.status = code, status
        super().__init__(code)
