"""Content-addressed private snapshots; only explicit complete reviewed inputs."""
import json
from pathlib import Path
from typing import Annotated, Literal

from pydantic import Field, StrictInt, field_validator, model_validator
from app.audit_events import CanonicalId
from app.baselines import canonical_json, digest, strict_json
from app.rule_contract import PuzzleVersion, RuleVersion
from .catalog import validate_catalog
from .contracts import (DatasetError, DatasetIssue, Digest, EvalCase, EvalPuzzle, SourceDigest,
    StrictDatasetModel, Visibility, require_utc, validate_reviewed_case)
from .grouping import GroupAudit, audit_groups, input_digest
from .inventory import DatasetInventory, inventory, verify_audit
from .proofs import validate_scope as _proof_scope
from .legacy import MAX_SOURCE_BYTES, _read_copy, checked_path

MAX_PROOF_BYTES = 2097152


class CaseBundle(StrictDatasetModel):
    schemaVersion: Literal[1] = 1
    cases: Annotated[tuple[EvalCase, ...], Field(max_length=5000)]
    sourceDigests: Annotated[tuple[SourceDigest, ...], Field(max_length=10000)]
    issues: Annotated[tuple[DatasetIssue, ...], Field(max_length=10000)]

    @model_validator(mode="after")
    def bounded_unique_cases(self):
        if len({c.caseId for c in self.cases}) != len(self.cases):
            raise ValueError("Duplicate case identity")
        if any(len(canonical_json(c.model_dump(mode="json")).encode("utf-8")) > 32768 for c in self.cases):
            raise ValueError("Case exceeds physical bound")
        return self


class DatasetManifest(StrictDatasetModel):
    schemaVersion: Literal[1] = 1
    datasetDigest: Digest
    splitRole: Literal["holdout", "dev", "regression"]
    frozenAt: Annotated[str, Field(min_length=20, max_length=40)]
    normalizationVersion: Literal["exact-v1"] = "exact-v1"
    groupingVersion: Literal["group-v1"] = "group-v1"
    reviewPolicy: Literal["manual-v1"] = "manual-v1"
    inputCaseIds: Annotated[tuple[CanonicalId, ...], Field(min_length=1, max_length=5000)]
    inputCount: Annotated[StrictInt, Field(ge=1, le=5000)]
    eligibleCount: Annotated[StrictInt, Field(ge=1, le=5000)]
    inventory: DatasetInventory
    sourceDigests: Annotated[tuple[SourceDigest, ...], Field(max_length=10000)]
    puzzleVersions: Annotated[tuple[PuzzleVersion, ...], Field(min_length=1, max_length=256)]
    ruleVersions: Annotated[tuple[RuleVersion, ...], Field(min_length=1, max_length=256)]
    casesDigest: Digest
    catalogDigest: Digest
    auditDigest: Digest
    candidateInputDigest: Digest
    repairInputDigest: Digest
    visibility: Visibility
    complete: Literal[True]

    @field_validator("frozenAt")
    @classmethod
    def utc(cls, value):
        return require_utc(value)

    @field_validator("complete", mode="before")
    @classmethod
    def explicit_complete(cls, value):
        if value is not True: raise ValueError("Complete proof required")
        return value


class FrozenDataset(StrictDatasetModel):
    manifest: DatasetManifest
    casesJson: Annotated[str, Field(min_length=1, max_length=MAX_SOURCE_BYTES)]
    catalogJson: Annotated[str, Field(min_length=1, max_length=MAX_PROOF_BYTES)]
    groupAuditJson: Annotated[str, Field(min_length=1, max_length=MAX_PROOF_BYTES)]




def _seal(cases, *, catalog, audit, source_digests, frozen_at, role):
    try:
        if type(cases) is not tuple or not 1 <= len(cases) <= 5000:
            raise DatasetError("dataset_input_invalid")
        cases = tuple(sorted((EvalCase.model_validate_json(c.model_dump_json()) for c in cases), key=lambda c: c.caseId))
        if len({c.caseId for c in cases}) != len(cases):
            raise DatasetError("dataset_duplicate_case")
        catalog = tuple(sorted(validate_catalog(catalog), key=lambda p: p.soupId))
        proof = verify_audit(audit)
        if not proof.complete or proof.issues:
            raise DatasetError("dataset_audit_incomplete")
        if role == "holdout":
            if any(c.split not in {"holdout_candidate", "holdout"} or c.origin != "new_authoring" or c.visibility != "private" for c in cases):
                raise DatasetError("dataset_holdout_role_invalid")
            if proof.candidateInputDigest != input_digest(cases) or set(proof.quarantineCaseIds) & {c.caseId for c in cases}:
                raise DatasetError("dataset_audit_input_mismatch")
        elif any(c.split != role for c in cases) or proof.candidateInputDigest != input_digest(()) or proof.repairInputDigest != input_digest(cases):
            raise DatasetError("dataset_repair_role_invalid")
        sources = _proof_scope(cases, proof, source_digests, role)
        for case in cases: validate_reviewed_case(case, catalog=catalog, context_cases=cases)
        counted = inventory(cases, audit=proof, source_digests=sources)
        if role == "holdout" and (counted.eligibleCount != len(cases) or any(counted.deficits.model_dump().values())):
            raise DatasetError("dataset_target_incomplete")
        visibility = {c.visibility for c in cases}
        if len(visibility) != 1:
            raise DatasetError("dataset_visibility_mixed")
        cases_json = canonical_json([c.model_dump(mode="json") for c in cases])
        catalog_json = canonical_json([p.model_dump(mode="json") for p in catalog])
        audit_json = canonical_json(proof.model_dump(mode="json"))
        if any(len(canonical_json(c.model_dump(mode="json")).encode("utf-8")) > 32768 for c in cases):
            raise DatasetError("dataset_case_limit")
        body = dict(schemaVersion=1, splitRole=role, frozenAt=frozen_at, normalizationVersion="exact-v1",
            groupingVersion="group-v1", reviewPolicy="manual-v1", inputCaseIds=tuple(c.caseId for c in cases),
            inputCount=len(cases), eligibleCount=len(cases), inventory=counted.model_dump(mode="json"),
            sourceDigests=[s.model_dump(mode="json") for s in sources],
            puzzleVersions=tuple(sorted(p.puzzleVersion for p in catalog)),
            ruleVersions=tuple(sorted({p.ruleSnapshot.ruleVersion for p in catalog})),
            casesDigest=digest(strict_json(cases_json)), catalogDigest=digest(strict_json(catalog_json)),
            auditDigest=proof.auditDigest, candidateInputDigest=proof.candidateInputDigest,
            repairInputDigest=proof.repairInputDigest, visibility=next(iter(visibility)), complete=True)
        manifest = DatasetManifest.model_validate_json(canonical_json({**body, "datasetDigest": digest(body)}))
        snapshot = FrozenDataset(manifest=manifest, casesJson=cases_json, catalogJson=catalog_json, groupAuditJson=audit_json)
        if len(canonical_json(manifest.model_dump(mode="json")).encode()) + len(catalog_json.encode()) + len(audit_json.encode()) > MAX_PROOF_BYTES:
            raise DatasetError("dataset_proof_limit")
        if len(canonical_json(snapshot.model_dump(mode="json")).encode()) > MAX_SOURCE_BYTES:
            raise DatasetError("dataset_source_limit")
        return snapshot
    except DatasetError:
        raise
    except Exception:
        raise DatasetError("dataset_freeze_invalid") from None


def freeze_dataset(cases, *, catalog, audit, source_digests, frozen_at):
    return _seal(cases, catalog=catalog, audit=audit, source_digests=source_digests, frozen_at=frozen_at, role="holdout")


def freeze_regression(cases, *, catalog, audit, source_digests, frozen_at):
    roles = {c.split for c in cases}
    if len(roles) != 1 or not roles <= {"dev", "regression"}:
        raise DatasetError("dataset_repair_role_invalid")
    return _seal(cases, catalog=catalog, audit=audit, source_digests=source_digests, frozen_at=frozen_at, role=next(iter(roles)))


def _array(raw, cls, max_items):
    values = strict_json(raw)
    if type(values) is not list or len(values) > max_items or canonical_json(values) != raw:
        raise DatasetError("dataset_blob_invalid")
    return tuple(cls.model_validate_json(canonical_json(value)) for value in values)


def verify_frozen_dataset(snapshot):
    try:
        checked = FrozenDataset.model_validate_json(snapshot.model_dump_json())
        cases = _array(checked.casesJson, EvalCase, 5000)
        catalog = _array(checked.catalogJson, EvalPuzzle, 256)
        raw_audit = strict_json(checked.groupAuditJson)
        if canonical_json(raw_audit) != checked.groupAuditJson:
            raise DatasetError("dataset_blob_invalid")
        proof = GroupAudit.model_validate_json(checked.groupAuditJson)
        actual = _seal(cases, catalog=catalog, audit=proof, source_digests=checked.manifest.sourceDigests,
            frozen_at=checked.manifest.frozenAt, role=checked.manifest.splitRole)
        if actual != checked:
            raise DatasetError("dataset_manifest_mismatch")
        return checked
    except DatasetError:
        raise
    except Exception:
        raise DatasetError("dataset_snapshot_invalid") from None


def load_repair_corpus(snapshot):
    checked = verify_frozen_dataset(snapshot)
    if checked.manifest.splitRole not in {"dev", "regression"}:
        raise DatasetError("dataset_holdout_repair_forbidden")
    return _array(checked.casesJson, EvalCase, 5000)


def _write_new(value, output):
    try:
        path = checked_path(output)
        if path.exists():
            raise DatasetError("dataset_output_exists")
        raw = canonical_json(value.model_dump(mode="json")).encode("utf-8")
        if len(raw) > MAX_SOURCE_BYTES:
            raise DatasetError("dataset_source_limit")
        path.parent.mkdir(parents=True, exist_ok=True)
        with path.open("xb") as stream:
            stream.write(raw)
            stream.flush()
        # A failed newly created output is retained, never overwrite or delete
        # another artifact. Durability against hardware power loss is not claimed.
    except DatasetError:
        raise
    except Exception:
        raise DatasetError("dataset_output_failed") from None


def write_new_snapshot(snapshot, *, output: Path):
    _write_new(verify_frozen_dataset(snapshot), output)


def write_new_case_bundle(bundle: CaseBundle, *, output: Path):
    try:
        checked = CaseBundle.model_validate_json(bundle.model_dump_json())
        _write_new(checked, output)
    except DatasetError:
        raise
    except Exception:
        raise DatasetError("dataset_bundle_invalid") from None


def _read(path):
    try:
        return _read_copy(checked_path(path)).decode("utf-8")
    except DatasetError:
        raise
    except Exception:
        raise DatasetError("dataset_input_invalid") from None


def read_snapshot(path: Path):
    try:
        return verify_frozen_dataset(FrozenDataset.model_validate_json(_read(path)))
    except DatasetError:
        raise
    except Exception:
        raise DatasetError("dataset_snapshot_invalid") from None


def read_case_bundle(path: Path):
    try:
        return CaseBundle.model_validate_json(_read(path))
    except DatasetError:
        raise
    except Exception:
        raise DatasetError("dataset_bundle_invalid") from None
