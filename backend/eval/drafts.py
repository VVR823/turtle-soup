"""Deterministic pending authoring; never invokes a model or mints a review."""
from typing import Annotated, Literal
from uuid import NAMESPACE_URL, uuid5

from pydantic import Field, StrictInt, field_validator
from app.baselines import canonical_json, digest
from app.host_evidence import build_evidence_catalog
from app.schemas import Soup
from .catalog import validate_catalog
from .contracts import (DatasetError, EvalCase, EvalPuzzle, ExpectedLabel, FactId, Identity,
                        StrictDatasetModel, require_utc)


class DraftEntry(StrictDatasetModel):
    soupId: Identity
    question: Annotated[str, Field(min_length=1, max_length=500)]
    caseType: Literal["single", "context", "control"]
    sourceGroup: Identity
    familyGroup: Identity
    conversationId: Identity | None
    contextIndex: Annotated[StrictInt, Field(ge=1, le=3)] | None
    categories: Annotated[tuple[Identity, ...], Field(max_length=8)]
    proposedLabel: ExpectedLabel | None
    factIds: Annotated[tuple[FactId, ...], Field(max_length=8)]


class DraftRequest(StrictDatasetModel):
    catalog: Annotated[tuple[EvalPuzzle, ...], Field(min_length=1, max_length=256)]
    entries: Annotated[tuple[DraftEntry, ...], Field(min_length=1, max_length=5000)]
    authorBatchId: Identity
    collectedAt: Annotated[str, Field(min_length=20, max_length=40)]

    @field_validator("collectedAt")
    @classmethod
    def utc(cls, value):
        return require_utc(value)

    @field_validator("authorBatchId")
    @classmethod
    def batch(cls, value):
        if not value.strip(): raise ValueError("Nonblank batch required")
        return value


def build_pending_draft(request: DraftRequest) -> tuple[EvalCase, ...]:
    try:
        checked = DraftRequest.model_validate_json(request.model_dump_json())
        catalog = validate_catalog(checked.catalog)
        by_id = {p.soupId: p for p in catalog}
        facts = {p.soupId: {r.id for r in build_evidence_catalog(Soup.model_validate_json(p.soupJson), p.puzzleVersion)} for p in catalog}
        source_digest = digest(checked.model_dump(mode="json"))
        entry_keys = set()
        result = []
        for entry in checked.entries:
            payload = entry.model_dump(mode="json")
            key = digest(payload)
            if key in entry_keys:
                raise DatasetError("dataset_duplicate_draft")
            entry_keys.add(key)
            puzzle = by_id.get(entry.soupId)
            if puzzle is None or not set(entry.factIds) <= facts[entry.soupId] or len(set(entry.factIds)) != len(entry.factIds):
                raise DatasetError("dataset_draft_scope_invalid")
            identity = str(uuid5(NAMESPACE_URL, canonical_json({"batch": checked.authorBatchId, "sourceDigest": source_digest,
                "collectedAt": checked.collectedAt, "entry": payload, "puzzleVersion": puzzle.puzzleVersion})))
            values = entry.model_dump(mode="python", exclude={"factIds"})
            result.append(EvalCase(**values, caseId=identity, puzzleVersion=puzzle.puzzleVersion,
                proposedFactIds=entry.factIds, split="holdout_candidate", visibility="private", origin="new_authoring",
                evidenceSourceDigest=source_digest, authorRole="ai_draft", reviewState="pending", rawLegacyExpected=None, review=None))
        return tuple(result)
    except DatasetError:
        raise
    except Exception:
        raise DatasetError("dataset_draft_invalid") from None
