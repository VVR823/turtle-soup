"""Whole-input coverage and deficits; no filtered denominator or accuracy."""
from typing import Annotated
from pydantic import Field, StrictInt
from app.baselines import digest
from .contracts import DatasetError, EvalCase, SourceDigest, StrictDatasetModel, review_is_current
from .proofs import validate_scope
from .grouping import GroupAudit, _contexts, input_digest

Count = Annotated[StrictInt, Field(ge=0, le=5000)]


class CoverageDeficits(StrictDatasetModel):
    single: Annotated[StrictInt, Field(ge=0, le=60)]
    soups: Annotated[StrictInt, Field(ge=0, le=6)]
    contextGroups: Annotated[StrictInt, Field(ge=0, le=10)]
    controls: Annotated[StrictInt, Field(ge=0, le=20)]


class DatasetInventory(StrictDatasetModel):
    inputCount: Count
    singleCount: Count
    singleSoupCount: Count
    contextGroupCount: Count
    contextDecisionCount: Count
    controlCount: Count
    pendingCount: Count
    ambiguousCount: Count
    unsupportedCount: Count
    reviewedCount: Count
    quarantineCount: Count
    eligibleCount: Count
    issueCount: Annotated[StrictInt, Field(ge=0, le=10000)]
    auditComplete: bool
    deficits: CoverageDeficits


def verify_audit(audit: GroupAudit) -> GroupAudit:
    try:
        checked = GroupAudit.model_validate_json(audit.model_dump_json())
        if checked.auditDigest != digest(checked.model_dump(mode="json", exclude={"auditDigest"})):
            raise DatasetError("dataset_audit_digest_mismatch")
        if checked.complete != (not checked.issues):
            raise DatasetError("dataset_audit_completeness_invalid")
        return checked
    except DatasetError:
        raise
    except Exception:
        raise DatasetError("dataset_audit_invalid") from None


def inventory(cases: tuple[EvalCase, ...], *, audit: GroupAudit,
              source_digests: tuple[SourceDigest, ...]) -> DatasetInventory:
    try:
        if type(cases) is not tuple or len(cases) > 5000:
            raise DatasetError("dataset_input_invalid")
        checked = tuple(EvalCase.model_validate_json(c.model_dump_json()) for c in cases)
        if len({c.caseId for c in checked}) != len(checked):
            raise DatasetError("dataset_duplicate_case")
        proof = verify_audit(audit)
        new = tuple(c for c in checked if c.split in {"holdout_candidate", "holdout"})
        old = tuple(c for c in checked if c.split in {"dev", "regression"})
        # A candidate-only inventory may retain an independent old-reference
        # digest in its audit without importing those labels into its input.
        if ((new or not old) and input_digest(new) != proof.candidateInputDigest
            or old and input_digest(old) != proof.repairInputDigest):
            raise DatasetError("dataset_audit_input_mismatch")
        validate_scope(checked, proof, source_digests, "inventory")
        quarantine = set(proof.quarantineCaseIds)
        selected = tuple(c for c in new if c.origin == "new_authoring" and c.visibility == "private" and c.caseId not in quarantine)
        singles = tuple(c for c in selected if c.caseType == "single")
        contexts = tuple(c for c in selected if c.caseType == "context")
        groups, invalid = _contexts(contexts)
        controls = tuple(c for c in selected if c.caseType == "control")
        eligible = tuple(c for c in selected if proof.complete and c.reviewState == "reviewed"
            and review_is_current(c, checked))
        return DatasetInventory(inputCount=len(checked), singleCount=len(singles),
            singleSoupCount=len({c.soupId for c in singles}), contextGroupCount=len(groups) - len(invalid),
            contextDecisionCount=len(contexts), controlCount=len(controls),
            pendingCount=sum(c.reviewState == "pending" for c in checked),
            ambiguousCount=sum(c.reviewState == "ambiguous" for c in checked),
            unsupportedCount=sum(c.reviewState == "unsupported" for c in checked),
            reviewedCount=sum(c.reviewState == "reviewed" for c in checked),
            quarantineCount=sum(c.caseId in quarantine for c in checked), eligibleCount=len(eligible),
            issueCount=len(proof.issues), auditComplete=proof.complete,
            deficits=CoverageDeficits(single=max(0, 60 - len(singles)),
                soups=max(0, 6 - len({c.soupId for c in singles})),
                contextGroups=max(0, 10 - (len(groups) - len(invalid))), controls=max(0, 20 - len(controls))))
    except DatasetError:
        raise
    except Exception:
        raise DatasetError("dataset_inventory_invalid") from None
