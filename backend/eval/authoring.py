"""Explicit private authoring adapter; no default files, models or review minting."""
import hashlib
from pathlib import Path
from typing import Annotated, Literal
from uuid import NAMESPACE_URL, uuid5

from pydantic import Field, StrictInt, field_validator
from app.baselines import digest
from app.host_evidence import build_evidence_catalog
from app.schemas import Soup
from .catalog import build_seed_catalog, validate_catalog
from .contracts import (DatasetError, EvalCase, EvalPuzzle, ExpectedLabel, Identity,
                        SourceDigest, StrictDatasetModel, require_utc)
from .drafts import DraftEntry, DraftRequest, build_pending_draft
from .grouping import audit_groups
from .inventory import inventory
from .legacy import _read_copy, checked_path
from .manifest import CaseBundle, _write_new, write_new_case_bundle


class AuthoringEntry(StrictDatasetModel):
    soupId: Identity
    question: Annotated[str, Field(min_length=1, max_length=500)]
    caseType: Literal["single", "context", "control"]
    sourceGroup: Identity
    familyGroup: Identity
    conversationId: Identity | None
    contextIndex: Annotated[StrictInt, Field(ge=1, le=3)] | None
    categories: Annotated[tuple[Identity, ...], Field(max_length=8)]
    proposedLabel: ExpectedLabel | None
    factSourcePaths: Annotated[tuple[Literal["bottom"], ...], Field(min_length=1, max_length=8)]


class AuthoringSource(StrictDatasetModel):
    schemaVersion: Literal[1] = 1
    soupIds: Annotated[tuple[Identity, ...], Field(min_length=1, max_length=256)]
    authorBatchId: Identity
    collectedAt: Annotated[str, Field(min_length=20, max_length=40)]
    entries: Annotated[tuple[AuthoringEntry, ...], Field(min_length=1, max_length=5000)]

    @field_validator("collectedAt")
    @classmethod
    def utc(cls, value):
        return require_utc(value)


class CatalogBundle(StrictDatasetModel):
    schemaVersion: Literal[1] = 1
    puzzles: Annotated[tuple[EvalPuzzle, ...], Field(min_length=1, max_length=256)]

    @field_validator("puzzles")
    @classmethod
    def complete_catalog(cls, value):
        return validate_catalog(value)


def compile_authoring(source: Path, *, cases_output: Path, catalog_output: Path, audit_output: Path):
    try:
        source = checked_path(source)
        outputs = tuple(checked_path(p) for p in (cases_output, catalog_output, audit_output))
        if len(set(outputs)) != 3 or any(p == source or p.exists() for p in outputs):
            raise DatasetError("dataset_output_exists")
        if any(a.is_relative_to(b) or b.is_relative_to(a) for i, a in enumerate(outputs) for b in outputs[i + 1:]):
            raise DatasetError("dataset_output_overlap")
        raw = _read_copy(source)
        authored = AuthoringSource.model_validate_json(raw)
        catalog = build_seed_catalog(soup_ids=authored.soupIds)
        facts = {p.soupId: {r.sourcePath: r.id for r in build_evidence_catalog(
            Soup.model_validate_json(p.soupJson), p.puzzleVersion)} for p in catalog}
        entries = []
        for entry in authored.entries:
            if entry.soupId not in facts:
                raise DatasetError("dataset_draft_scope_invalid")
            refs = tuple(facts[entry.soupId][path] for path in entry.factSourcePaths)
            entries.append(DraftEntry(**entry.model_dump(mode="python", exclude={"factSourcePaths"}), factIds=refs))
        request = DraftRequest(catalog=catalog, entries=tuple(entries),
            authorBatchId=authored.authorBatchId, collectedAt=authored.collectedAt)
        built = build_pending_draft(request)
        physical_digest = hashlib.sha256(raw).hexdigest()
        # These are newly authored pending rows, not reviewed records. Bind the
        # actual original bytes as well as the already validated compiled input.
        cases = tuple(EvalCase.model_validate_json(c.model_copy(update={
            "caseId": str(uuid5(NAMESPACE_URL, digest({"compiledId": c.caseId, "physicalSourceDigest": physical_digest}))),
            "evidenceSourceDigest": physical_digest}).model_dump_json()) for c in built)
        by_group = {}
        for case in cases:
            by_group.setdefault(case.sourceGroup, []).append(case.caseId)
        sources = tuple(SourceDigest(sourceId="authoring:" + digest({"batch": authored.authorBatchId, "group": group}),
            sourceDigest=physical_digest, questionSourceGroup=group, origin="new_authoring",
            collectedAt=authored.collectedAt, visibility="private", caseIds=tuple(sorted(ids)))
            for group, ids in sorted(by_group.items()))
        audit = audit_groups(cases, repair_cases=(), source_digests=sources, source_complete=False)
        counted = inventory(cases, audit=audit, source_digests=sources)
        bundle = CaseBundle(cases=cases, sourceDigests=sources, issues=audit.issues)
        # Always unavailable overlap audit until explicit old copies and manual
        # family review exist. Never mint true simply because a new file parsed.
        write_new_case_bundle(bundle, output=outputs[0])
        _write_new(CatalogBundle(puzzles=catalog), outputs[1])
        _write_new(audit, outputs[2])
        return counted
    except DatasetError:
        raise
    except Exception:
        raise DatasetError("dataset_authoring_invalid") from None
