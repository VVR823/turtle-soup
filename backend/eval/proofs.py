"""Shared structural/source scope validation for inventory and sealing."""
from app.baselines import digest
from .contracts import DatasetError, SourceDigest
from .grouping import audit_groups


def _sources(values):
    if type(values) is not tuple or len(values) > 10000:
        raise DatasetError("dataset_source_coverage_invalid")
    checked = tuple(sorted((SourceDigest.model_validate_json(s.model_dump_json()) for s in values), key=lambda s: s.sourceId))
    if len({s.sourceId for s in checked}) != len(checked):
        raise DatasetError("dataset_source_coverage_invalid")
    return checked


def validate_scope(cases, proof, source_digests, role):
    sources = _sources(source_digests)
    if proof.sourceInventoryDigest != digest([s.model_dump(mode="json") for s in sources]):
        raise DatasetError("dataset_source_inventory_mismatch")
    members = {}
    for source in sources:
        for identity in source.caseIds:
            if identity in members: raise DatasetError("dataset_source_coverage_invalid")
            members[identity] = source
    identities = {c.caseId for c in cases}
    case_by_id = {c.caseId: c for c in cases}
    candidates = {c.caseId for c in cases if c.split in {"holdout_candidate", "holdout"}}
    for c in cases:
        source = members.get(c.caseId)
        if source is None or (source.sourceDigest, source.questionSourceGroup, source.origin, source.visibility) != (
            c.evidenceSourceDigest, c.sourceGroup, c.origin, c.visibility):
            raise DatasetError("dataset_source_coverage_invalid")
    group_for, edge_keys, required_quarantine = {}, set(), set()
    for group in proof.groups:
        if tuple(sorted(set(group.caseIds))) != group.caseIds or group.groupId != digest({"groupingVersion": "group-v1", "caseIds": group.caseIds}):
            raise DatasetError("dataset_group_proof_invalid")
        for identity in group.caseIds:
            if identity in group_for: raise DatasetError("dataset_group_proof_invalid")
            group_for[identity] = group.groupId
        if tuple(sorted(set(group.contaminationCauses))) != group.contaminationCauses:
            raise DatasetError("dataset_group_proof_invalid")
        known = tuple(case_by_id[i] for i in group.caseIds if i in case_by_id)
        if set(group.caseIds) <= identities:
            causes = tuple(sorted({c.split for c in known if c.split in {"dev", "regression"}} |
                {"public_synthetic" for c in known if c.origin == "public_synthetic"}))
            if causes != group.contaminationCauses:
                raise DatasetError("dataset_group_proof_invalid")
        if group.contaminationCauses or set(group.caseIds) - identities:
            required_quarantine.update(set(group.caseIds) & candidates)
        if role == "holdout" and set(group.caseIds) & identities:
            if group.contaminationCauses or set(group.caseIds) - identities:
                raise DatasetError("dataset_quarantine_required")
    if (set(group_for) != set(members)
        or tuple(sorted(required_quarantine)) != proof.quarantineCaseIds):
        raise DatasetError("dataset_group_proof_invalid")
    parent = {identity: identity for identity in members}
    def find(identity):
        while parent[identity] != identity:
            parent[identity] = parent[parent[identity]]
            identity = parent[identity]
        return identity
    for edge in proof.edges:
        key = (edge.reason, edge.leftCaseId, edge.rightCaseId)
        if key in edge_keys or edge.leftCaseId >= edge.rightCaseId or any(i not in group_for for i in key[1:]):
            raise DatasetError("dataset_edge_proof_invalid")
        edge_keys.add(key)
        if group_for[edge.leftCaseId] != group_for[edge.rightCaseId]:
            raise DatasetError("dataset_edge_proof_invalid")
        left, right = find(edge.leftCaseId), find(edge.rightCaseId)
        parent[right] = left
    for group in proof.groups:
        if len({find(i) for i in group.caseIds}) != 1:
            raise DatasetError("dataset_group_proof_invalid")
    if not identities <= set(group_for) or not set(proof.quarantineCaseIds) <= set(group_for):
        raise DatasetError("dataset_group_proof_invalid")
    if role in {"holdout", "inventory"}:
        # Recompute all in-body source/family/raw/exact/context relationships.
        # Old labels remain outside the input blob; outside IDs in a candidate
        # component already refuse above. Manual aliases remain human evidence.
        candidate_sources = tuple(s.model_copy(update={"caseIds": tuple(i for i in s.caseIds if i in identities)})
            for s in sources if set(s.caseIds) & identities)
        new = tuple(c for c in cases if c.split in {"holdout_candidate", "holdout"})
        old = tuple(c for c in cases if c.split in {"dev", "regression"})
        intrinsic = audit_groups(new, repair_cases=old, source_digests=candidate_sources,
            source_complete=True if role == "holdout" else proof.complete)
        if not intrinsic.complete and (role == "holdout" or proof.complete):
            raise DatasetError("dataset_intrinsic_audit_invalid")
        for group in intrinsic.groups:
            if len({group_for[i] for i in group.caseIds}) != 1:
                raise DatasetError("dataset_group_proof_invalid")
    else:
        if set(members) != identities:
            raise DatasetError("dataset_repair_scope_invalid")
        intrinsic = audit_groups((), repair_cases=cases, source_digests=sources, source_complete=True)
        if proof != intrinsic:
            raise DatasetError("dataset_repair_audit_invalid")
    return sources
