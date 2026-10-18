"""Deterministic contamination components; no semantic classifier or model I/O."""
import unicodedata
from collections import defaultdict
from typing import Annotated, Literal

from pydantic import Field
from app.audit_events import CanonicalId
from app.baselines import canonical_json, digest
from app.question_normalization import normalize_exact_question
from .contracts import DatasetError, DatasetIssue, Digest, EvalCase, SourceDigest, StrictDatasetModel


class GroupEdge(StrictDatasetModel):
    reason: Literal["source", "family", "conversation", "raw", "exact"]
    leftCaseId: CanonicalId
    rightCaseId: CanonicalId


class ContaminationGroup(StrictDatasetModel):
    groupId: Digest
    caseIds: Annotated[tuple[CanonicalId, ...], Field(min_length=1, max_length=10000)]
    contaminationCauses: tuple[Literal["dev", "regression", "public_synthetic"], ...]


class GroupAudit(StrictDatasetModel):
    schemaVersion: Literal[1] = 1
    groups: Annotated[tuple[ContaminationGroup, ...], Field(max_length=10000)]
    edges: Annotated[tuple[GroupEdge, ...], Field(max_length=50000)]
    quarantineCaseIds: Annotated[tuple[CanonicalId, ...], Field(max_length=5000)]
    issues: Annotated[tuple[DatasetIssue, ...], Field(max_length=10000)]
    complete: bool
    candidateInputDigest: Digest
    repairInputDigest: Digest
    sourceInventoryDigest: Digest
    auditDigest: Digest


def input_digest(cases: tuple[EvalCase, ...]) -> str:
    return digest([c.model_dump(mode="json") for c in sorted(cases, key=lambda c: c.caseId)])


def _contexts(cases):
    groups = defaultdict(list)
    for case in cases:
        if case.caseType == "context":
            groups[case.conversationId].append(case)
    invalid = set()
    for name, members in groups.items():
        scope = {(c.soupId, c.puzzleVersion, c.sourceGroup, c.familyGroup, c.split) for c in members}
        if len(members) != 3 or sorted(c.contextIndex for c in members) != [1, 2, 3] or len(scope) != 1:
            invalid.add(name)
    return groups, invalid


def case_context_key(case: EvalCase, cases: tuple[EvalCase, ...]) -> str:
    if case.caseType != "context":
        return digest({"context": "standalone"})
    groups, invalid = _contexts(cases)
    if case.conversationId in invalid or case.conversationId not in groups:
        raise DatasetError("dataset_context_group_invalid")
    prefix = sorted((c for c in groups[case.conversationId] if c.contextIndex < case.contextIndex), key=lambda c: c.contextIndex)
    return digest({"prefix": [{"question": c.question,
        "expectedLabel": c.review.expectedLabel.model_dump(mode="json") if c.review is not None else None} for c in prefix]})


def audit_groups(cases: tuple[EvalCase, ...], *, repair_cases: tuple[EvalCase, ...],
                 source_digests: tuple[SourceDigest, ...], source_complete: bool) -> GroupAudit:
    try:
        if (type(cases) is not tuple or type(repair_cases) is not tuple or type(source_digests) is not tuple
            or type(source_complete) is not bool or len(cases) > 5000 or len(repair_cases) > 5000 or len(source_digests) > 10000):
            raise DatasetError("dataset_audit_invalid")
        new = tuple(EvalCase.model_validate_json(c.model_dump_json()) for c in cases)
        old = tuple(EvalCase.model_validate_json(c.model_dump_json()) for c in repair_cases)
        if any(c.split not in {"holdout_candidate", "holdout"} or c.origin != "new_authoring" for c in new):
            raise DatasetError("dataset_candidate_role_invalid")
        if any(c.split not in {"dev", "regression"} for c in old):
            raise DatasetError("dataset_repair_role_invalid")
        all_cases = tuple(sorted(new + old, key=lambda c: c.caseId))
        by_id = {c.caseId: c for c in all_cases}
        if len(by_id) != len(all_cases):
            raise DatasetError("dataset_duplicate_case")
        sources = tuple(sorted((SourceDigest.model_validate_json(s.model_dump_json()) for s in source_digests), key=lambda s: s.sourceId))
        issues = []
        if not source_complete:
            issues.append(DatasetIssue(code="dataset_source_audit_unavailable"))
        memberships = defaultdict(list)
        for s in sources:
            for identity in s.caseIds:
                memberships[identity].append(s)
        coverage_ok = len({s.sourceId for s in sources}) == len(sources) and set(memberships) == set(by_id)
        for identity, case in by_id.items():
            matched = memberships[identity]
            coverage_ok = coverage_ok and len(matched) == 1
            if len(matched) == 1:
                s = matched[0]
                coverage_ok = coverage_ok and (s.sourceDigest, s.questionSourceGroup, s.origin, s.visibility) == (
                    case.evidenceSourceDigest, case.sourceGroup, case.origin, case.visibility)
        if not coverage_ok:
            issues.append(DatasetIssue(code="dataset_source_coverage_invalid"))
        contexts, invalid = _contexts(all_cases)
        for name in sorted(invalid):
            issues.append(DatasetIssue(code="dataset_context_group_invalid", caseIds=tuple(sorted(c.caseId for c in contexts[name]))))

        parent = {identity: identity for identity in by_id}
        edges = set()
        representatives = {}
        def find(identity):
            while parent[identity] != identity:
                parent[identity] = parent[parent[identity]]
                identity = parent[identity]
            return identity
        def link(reason, key, identity):
            named = (reason, key)
            if named not in representatives:
                representatives[named] = identity
                return
            other = representatives[named]
            edges.add((reason, min(other, identity), max(other, identity)))
            left, right = find(other), find(identity)
            if left != right:
                parent[max(left, right)] = min(left, right)

        for c in all_cases:
            scope = (c.soupId, c.puzzleVersion)
            link("source", scope + (c.sourceGroup,), c.caseId)
            link("family", scope + (c.familyGroup,), c.caseId)
            if c.conversationId is not None:
                link("conversation", scope + (c.conversationId,), c.caseId)
            link("raw", (c.soupId, unicodedata.normalize("NFC", c.question)), c.caseId)
            try:
                exact = normalize_exact_question(c.question)
            except ValueError:
                # A valid bounded punctuation-only control stays in input;
                # it simply has no exact-v1 semantic key.
                exact = None
            if exact is not None: link("exact", (c.soupId, exact), c.caseId)

        labels = defaultdict(list)
        for c in all_cases:
            if c.review is None or c.conversationId in invalid: continue
            try: exact = normalize_exact_question(c.question)
            except ValueError: exact = unicodedata.normalize("NFC", c.question)
            key = (c.soupId, c.puzzleVersion, exact, case_context_key(c, all_cases))
            labels[key].append(c)
        for members in labels.values():
            if len({canonical_json(c.review.expectedLabel.model_dump(mode="json")) for c in members}) > 1:
                issues.append(DatasetIssue(code="dataset_label_conflict", caseIds=tuple(sorted(c.caseId for c in members))))

        components = defaultdict(list)
        for c in all_cases: components[find(c.caseId)].append(c)
        groups, quarantine = [], set()
        candidate_ids = {c.caseId for c in new}
        for members in components.values():
            identities = tuple(sorted(c.caseId for c in members))
            causes = tuple(sorted({c.split for c in members if c.split in {"dev", "regression"}} |
                                  {"public_synthetic" for c in members if c.origin == "public_synthetic"}))
            groups.append(ContaminationGroup(groupId=digest({"groupingVersion": "group-v1", "caseIds": identities}),
                caseIds=identities, contaminationCauses=causes))
            if causes: quarantine.update(set(identities) & candidate_ids)
        ordered_issues = tuple(sorted(issues, key=lambda i: canonical_json(i.model_dump(mode="json"))))
        body = dict(schemaVersion=1, groups=tuple(sorted(groups, key=lambda g: g.groupId)),
            edges=tuple(GroupEdge(reason=r, leftCaseId=a, rightCaseId=b) for r, a, b in sorted(edges)),
            quarantineCaseIds=tuple(sorted(quarantine)), issues=ordered_issues, complete=not ordered_issues,
            candidateInputDigest=input_digest(new), repairInputDigest=input_digest(old),
            sourceInventoryDigest=digest([s.model_dump(mode="json") for s in sources]))
        encoded = {key: [v.model_dump(mode="json") for v in value] if key in {"groups", "edges", "issues"} else value for key, value in body.items()}
        return GroupAudit(**body, auditDigest=digest(encoded))
    except DatasetError:
        raise
    except Exception:
        raise DatasetError("dataset_audit_invalid") from None
