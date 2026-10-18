"""Immutable offline data contracts; proposals never supply approval authority."""
import re
from datetime import datetime
from typing import Annotated, Literal

from pydantic import BaseModel, ConfigDict, Field, StrictInt, field_validator, model_validator

from app.audit_events import CanonicalId
from app.baselines import digest, strict_json
from app.rule_contract import Digest, FactId, PuzzleVersion, RuleSnapshot
from app.schemas import AnswerType

Identity = Annotated[str, Field(min_length=1, max_length=200)]
Origin = Literal["legacy", "new_authoring", "public_synthetic"]
Visibility = Literal["private", "public_authorized"]
Split = Literal["dev", "regression", "holdout_candidate", "holdout"]


class DatasetError(ValueError):
    """Safe machine code only, never source text or an underlying exception."""

    def __init__(self, code="dataset_invalid"):
        self.code = code
        super().__init__(code)


def require_utc(value: str) -> str:
    if not re.fullmatch(r"\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}(?:\.\d{1,6})?(?:Z|\+00:00)", value):
        raise ValueError("UTC timestamp required")
    datetime.fromisoformat(value.replace("Z", "+00:00"))
    return value


class StrictDatasetModel(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True, frozen=True, allow_inf_nan=False)

    @classmethod
    def model_validate_json(cls, json_data, *args, **kwargs):
        # Pydantic accepts duplicate keys. Inspect wire bytes before JSON-mode
        # validation, which correctly accepts arrays as strict tuples.
        strict_json(json_data)
        return super().model_validate_json(json_data, *args, **kwargs)

    @field_validator("schemaVersion", mode="before", check_fields=False)
    @classmethod
    def real_schema(cls, value):
        if type(value) is not int or value != 1:
            raise ValueError("Unknown dataset schema")
        return value

    @field_validator("sourceId", "questionSourceGroup", "operatorId", "soupId", "sourceGroup", "familyGroup",
                     "conversationId", "question", "reviewNote", mode="after", check_fields=False)
    @classmethod
    def meaningful_text(cls, value):
        if value is not None and not value.strip():
            raise ValueError("Nonblank text required")
        return value


class ExpectedLabel(StrictDatasetModel):
    kind: Literal["answer", "reminder"]
    answer: AnswerType | None

    @model_validator(mode="after")
    def consistent_answer(self):
        if (self.kind == "answer") != (self.answer is not None):
            raise ValueError("Inconsistent expected label")
        return self


class ReviewRecord(StrictDatasetModel):
    schemaVersion: Literal[1] = 1
    operatorId: Identity
    reviewedAt: Annotated[str, Field(min_length=20, max_length=40)]
    caseDigest: Digest
    expectedLabel: ExpectedLabel
    factIds: Annotated[tuple[FactId, ...], Field(max_length=8)]
    reviewNote: Annotated[str, Field(min_length=1, max_length=1000)]
    humanConfirmed: Literal[True]
    contextDigest: Digest | None = None

    @field_validator("reviewedAt")
    @classmethod
    def utc(cls, value):
        return require_utc(value)

    @field_validator("humanConfirmed", mode="before")
    @classmethod
    def explicit_confirmation(cls, value):
        if value is not True:
            raise ValueError("Explicit human attestation required")
        return value

    @model_validator(mode="after")
    def facts_required_for_answer(self):
        if len(set(self.factIds)) != len(self.factIds) or (self.expectedLabel.kind == "answer" and not self.factIds):
            raise ValueError("Unique facts required for an answer label")
        return self


class EvalPuzzle(StrictDatasetModel):
    soupId: Identity
    puzzleVersion: PuzzleVersion
    soupJson: Annotated[str, Field(min_length=1, max_length=2097152)]
    ruleSnapshot: RuleSnapshot


class SourceDigest(StrictDatasetModel):
    schemaVersion: Literal[1] = 1
    sourceId: Identity
    sourceDigest: Digest
    questionSourceGroup: Identity
    origin: Origin
    collectedAt: Annotated[str, Field(min_length=20, max_length=40)]
    visibility: Visibility
    caseIds: Annotated[tuple[CanonicalId, ...], Field(max_length=5000)]

    @field_validator("collectedAt")
    @classmethod
    def utc(cls, value):
        return require_utc(value)

    @field_validator("caseIds")
    @classmethod
    def unique_cases(cls, value):
        if len(set(value)) != len(value):
            raise ValueError("Duplicate source case identity")
        return value


class EvalCase(StrictDatasetModel):
    schemaVersion: Literal[1] = 1
    caseId: CanonicalId
    soupId: Identity
    puzzleVersion: PuzzleVersion
    question: Annotated[str, Field(min_length=1, max_length=500)]
    caseType: Literal["single", "context", "control"]
    split: Split
    sourceGroup: Identity
    familyGroup: Identity
    conversationId: Identity | None
    contextIndex: Annotated[StrictInt, Field(ge=1, le=3)] | None
    categories: Annotated[tuple[Identity, ...], Field(max_length=8)]
    visibility: Visibility
    origin: Origin
    evidenceSourceDigest: Digest
    authorRole: Literal["ai_draft", "human", "legacy", "synthetic"]
    reviewState: Literal["pending", "reviewed", "ambiguous", "unsupported"]
    proposedLabel: ExpectedLabel | None
    proposedFactIds: Annotated[tuple[FactId, ...], Field(max_length=8)] = ()
    rawLegacyExpected: Annotated[str, Field(max_length=1000)] | None
    review: ReviewRecord | None

    @model_validator(mode="after")
    def consistent_case(self):
        if len(set(self.proposedFactIds)) != len(self.proposedFactIds):
            raise ValueError("Duplicate proposed facts")
        if self.origin == "new_authoring" and self.authorRole not in {"ai_draft", "human"}:
            raise ValueError("New authoring requires declared human or AI author")
        if self.origin == "legacy" and (self.split not in {"dev", "regression"} or self.authorRole != "legacy"):
            raise ValueError("Legacy cannot become holdout")
        if self.origin == "public_synthetic" and (self.split not in {"dev", "regression"} or self.authorRole != "synthetic"):
            raise ValueError("Public demonstration cannot become holdout")
        if self.split in {"holdout", "holdout_candidate"} and self.visibility != "private":
            raise ValueError("Holdout must remain private")
        if self.caseType == "context":
            if self.conversationId is None or self.contextIndex is None:
                raise ValueError("Explicit context metadata required")
        elif self.conversationId is not None or self.contextIndex is not None:
            raise ValueError("Standalone case cannot carry context metadata")
        if len(set(self.categories)) != len(self.categories) or any(not name.strip() for name in self.categories):
            raise ValueError("Duplicate categories")
        if (self.reviewState == "reviewed") != (self.review is not None):
            raise ValueError("Review state and attestation differ")
        if self.split == "holdout" and self.reviewState != "reviewed":
            raise ValueError("Unreviewed candidate cannot be formal holdout")
        return self


def case_digest(case: EvalCase) -> str:
    return digest(case.model_dump(mode="json", exclude={"review", "reviewState"}))


def review_context_digest(case: EvalCase, cases: tuple[EvalCase, ...]) -> str:
    """Human review context, not the actual host history supplied to a model."""
    from .grouping import _contexts
    groups, invalid = _contexts(cases)
    if case.caseType != "context" or case.conversationId in invalid or case.conversationId not in groups:
        raise DatasetError("dataset_context_group_invalid")
    group = groups[case.conversationId]
    if not any(c.caseId == case.caseId and case_digest(c) == case_digest(case) for c in group):
        raise DatasetError("dataset_context_group_invalid")
    prefix = sorted((c for c in group if c.contextIndex < case.contextIndex), key=lambda c: c.contextIndex)
    if any(c.reviewState != "reviewed" or c.review is None or c.review.caseDigest != case_digest(c) for c in prefix):
        raise DatasetError("dataset_review_required")
    return digest({"reviewContextPolicy": "context-review-v1", "conversationId": case.conversationId,
        "soupId": case.soupId, "puzzleVersion": case.puzzleVersion, "contextIndex": case.contextIndex,
        "sourceGroup": case.sourceGroup, "familyGroup": case.familyGroup, "split": case.split,
        "prefix": [{"caseDigest": case_digest(c), "expectedLabel": c.review.expectedLabel.model_dump(mode="json")}
                   for c in prefix]})


def review_is_current(case: EvalCase, cases: tuple[EvalCase, ...]) -> bool:
    if case.reviewState != "reviewed" or case.review is None or case.review.caseDigest != case_digest(case):
        return False
    if case.caseType != "context":
        return case.review.contextDigest is None
    try:
        return case.review.contextDigest == review_context_digest(case, cases)
    except DatasetError:
        return False


def validate_reviewed_case(case: EvalCase, *, catalog: tuple[EvalPuzzle, ...],
                          context_cases: tuple[EvalCase, ...] | None = None) -> EvalCase:
    from .catalog import validate_catalog
    from app.host_evidence import build_evidence_catalog
    from app.schemas import Soup
    try:
        checked = EvalCase.model_validate_json(case.model_dump_json())
        validated = validate_catalog(catalog)
        source = next((p for p in validated if p.soupId == checked.soupId and p.puzzleVersion == checked.puzzleVersion), None)
        if source is None or checked.reviewState != "reviewed" or checked.review is None:
            raise DatasetError("dataset_review_required")
        receipt = checked.review
        if not review_is_current(checked, context_cases or ()):
            raise DatasetError("dataset_review_stale")
        facts = {r.id for r in build_evidence_catalog(Soup.model_validate_json(source.soupJson), source.puzzleVersion)}
        if not (set(receipt.factIds) | set(checked.proposedFactIds)) <= facts:
            raise DatasetError("dataset_fact_mismatch")
        # A declaration and references, not human identity/entailment/privacy
        # or actual real-model quality.
        return checked
    except DatasetError:
        raise
    except Exception:
        raise DatasetError("dataset_review_invalid") from None


class DatasetIssue(StrictDatasetModel):
    code: Literal["dataset_line_invalid", "dataset_utf8_invalid", "dataset_pair_incomplete", "dataset_partial_tail",
        "dataset_line_limit", "dataset_case_invalid", "dataset_source_audit_unavailable",
        "dataset_source_coverage_invalid", "dataset_context_group_invalid", "dataset_label_conflict"]
    caseIds: Annotated[tuple[CanonicalId, ...], Field(max_length=5000)] = ()
    lineNumber: Annotated[StrictInt, Field(ge=1, le=20000)] | None = None
    sourceDigest: Digest | None = None
