"""Contamination is transitive; valid context-dependent labels stay distinct."""
import hashlib
from uuid import UUID

import pytest


def item(pending, number, **changes):
    from eval.contracts import EvalCase
    group = changes.get("sourceGroup", f"source-{number}")
    body = pending.model_dump(mode="python")
    body.update(caseId=str(UUID(int=number + 100)), question=f"Question {number}?", sourceGroup=group,
        familyGroup=f"family-{number}", evidenceSourceDigest=hashlib.sha256(group.encode()).hexdigest())
    body.update(changes)
    return EvalCase.model_validate(body)


def sources(cases):
    from eval.contracts import SourceDigest
    grouped = {}
    for c in cases: grouped.setdefault((c.evidenceSourceDigest, c.sourceGroup, c.origin, c.visibility), []).append(c.caseId)
    return tuple(SourceDigest(sourceId=f"owned-source-{index}", sourceDigest=key[0], questionSourceGroup=key[1],
        origin=key[2], collectedAt="2026-10-09T00:00:00Z", visibility=key[3], caseIds=tuple(sorted(set(ids))))
        for index, (key, ids) in enumerate(sorted(grouped.items())))


def audit(cases, repair=(), **options):
    from eval.grouping import audit_groups
    return audit_groups(cases, repair_cases=repair, source_digests=sources(cases + repair), source_complete=True, **options)


def test_transitive_source_family_and_exact_edges_quarantine_whole_candidate_component(pending):
    a = item(pending, 1, sourceGroup="shared-new", question="A?")
    b = item(pending, 2, sourceGroup="shared-new", familyGroup="bridge", question="B?")
    c = item(pending, 3, familyGroup="bridge", question="C？")
    old = item(pending, 4, origin="legacy", authorRole="legacy", split="regression", question=" C?? ")
    result = audit((a, b, c), (old,))
    assert result.quarantineCaseIds == tuple(sorted((a.caseId, b.caseId, c.caseId)))
    assert len(result.groups) == 1 and set(result.groups[0].caseIds) == {a.caseId, b.caseId, c.caseId, old.caseId}
    assert {edge.reason for edge in result.edges} >= {"source", "family", "exact"}
    assert result.complete is True  # Complete audit, not eligible holdout.


def test_normalization_edges_preserve_original_question_and_negation_subject_number(pending):
    questions = ["他是人吗？", "  他是人吗??", "他不是人吗？", "她是人吗？", "他有两人吗？", "他有三人吗？"]
    cases = tuple(item(pending, n + 1, question=q) for n, q in enumerate(questions))
    result = audit(cases)
    assert len(result.groups) == 5 and result.quarantineCaseIds == ()
    assert [c.question for c in cases] == questions
    assert any(set(g.caseIds) == {cases[0].caseId, cases[1].caseId} for g in result.groups)


def test_nfc_raw_duplicate_edge_does_not_replace_input_text(pending):
    left = item(pending, 1, question="café?")
    right = item(pending, 2, question="cafe\u0301?")
    result = audit((left, right))
    assert len(result.groups) == 1 and "raw" in {e.reason for e in result.edges}
    assert left.question != right.question


def test_public_example_family_contaminates_private_candidates(pending):
    private = item(pending, 1, familyGroup="published-family")
    public = item(pending, 2, origin="public_synthetic", authorRole="synthetic", split="dev",
        visibility="public_authorized", familyGroup="published-family")
    result = audit((private,), (public,))
    assert result.quarantineCaseIds == (private.caseId,)
    assert "public_synthetic" in result.groups[0].contaminationCauses


def test_audit_digest_binds_candidate_repair_and_inventory_independently(pending):
    new = item(pending, 1)
    old = item(pending, 2, origin="legacy", authorRole="legacy", split="regression")
    first = audit((new,), (old,))
    reversed_input = audit((new,), (old,))
    assert first == reversed_input
    changed_old = item(pending, 2, origin="legacy", authorRole="legacy", split="regression", question="Old changed?")
    second = audit((new,), (changed_old,))
    assert first.candidateInputDigest == second.candidateInputDigest
    assert first.repairInputDigest != second.repairInputDigest and first.auditDigest != second.auditDigest
    without_candidate = audit((), (old,))
    assert first.candidateInputDigest != without_candidate.candidateInputDigest


def test_order_independent_whole_component_proof(pending):
    a = item(pending, 1, familyGroup="shared"); b = item(pending, 2, familyGroup="shared")
    assert audit((a, b)) == audit((b, a))


def test_missing_explicit_source_audit_never_means_complete(pending):
    from eval.grouping import audit_groups
    new = item(pending, 1)
    result = audit_groups((new,), repair_cases=(), source_digests=sources((new,)), source_complete=False)
    assert result.complete is False and any(i.code == "dataset_source_audit_unavailable" for i in result.issues)


def test_missing_source_inventory_is_reported_not_inferred(pending):
    from eval.grouping import audit_groups
    result = audit_groups((item(pending, 1),), repair_cases=(), source_digests=(), source_complete=True)
    assert result.complete is False and any(i.code == "dataset_source_coverage_invalid" for i in result.issues)


def test_duplicate_ids_or_legacy_candidate_cannot_be_audited_as_new_holdout(pending):
    from eval.contracts import DatasetError
    same = item(pending, 1)
    with pytest.raises(DatasetError): audit((same, same))
    old = item(pending, 2, origin="legacy", authorRole="legacy", split="regression")
    with pytest.raises(DatasetError): audit((old,))


def context_case(pending, reviewed, n, group, index, question, answer="是", split="holdout_candidate"):
    from eval.contracts import ExpectedLabel, case_digest
    c = item(pending, n, caseType="context", conversationId=group, contextIndex=index,
        sourceGroup=group, familyGroup=group, question=question, split=split)
    receipt = reviewed.review.model_copy(update={"caseDigest": case_digest(c),
        "expectedLabel": ExpectedLabel(kind="answer", answer=answer)})
    return c.model_copy(update={"reviewState": "reviewed", "review": receipt})


def test_identical_pronouns_with_different_histories_keep_opposite_labels(pending, reviewed):
    from eval.grouping import case_context_key
    left = tuple(context_case(pending, reviewed, 10 + i, "left", i,
        ["Is the keeper the subject?", "Is the keeper male?", "他是男性吗？"][i - 1]) for i in (1, 2, 3))
    right = tuple(context_case(pending, reviewed, 20 + i, "right", i,
        ["Is the visitor the subject?", "Is the visitor female?", "他是男性吗？"][i - 1], answer="不是") for i in (1, 2, 3))
    result = audit(left + right)
    assert len(result.groups) == 1 and len(result.groups[0].caseIds) == 6
    assert result.complete is True and not any(i.code == "dataset_label_conflict" for i in result.issues)
    assert case_context_key(left[2], left + right) != case_context_key(right[2], left + right)
    assert left[2].review.expectedLabel.answer == "是" and right[2].review.expectedLabel.answer == "不是"


def test_standalone_opposite_reviewed_labels_block_completeness(pending, reviewed):
    from eval.contracts import ExpectedLabel, case_digest
    a = item(pending, 1, question="Same question?"); b = item(pending, 2, question="Same question？")
    a = a.model_copy(update={"reviewState": "reviewed", "review": reviewed.review.model_copy(update={"caseDigest": case_digest(a)})})
    b = b.model_copy(update={"reviewState": "reviewed", "review": reviewed.review.model_copy(update={"caseDigest": case_digest(b), "expectedLabel": ExpectedLabel(kind="answer", answer="不是")})})
    result = audit((a, b))
    assert result.complete is False and any(i.code == "dataset_label_conflict" and set(i.caseIds) == {a.caseId, b.caseId} for i in result.issues)


@pytest.mark.parametrize("problem", ["partial", "duplicate-index", "split", "family", "p1"])
def test_context_triplet_inconsistency_blocks_audit(pending, reviewed, problem):
    cases = tuple(context_case(pending, reviewed, 30 + i, "context", i, f"Round {i}?") for i in (1, 2, 3))
    if problem == "partial": cases = cases[:2]
    else:
        update = {"duplicate-index": {"contextIndex": 1}, "split": {"split": "holdout"},
            "family": {"familyGroup": "different"}, "p1": {"puzzleVersion": "p1:" + "b" * 64}}[problem]
        cases = cases[:2] + (cases[2].model_copy(update=update),)
    result = audit(cases)
    assert result.complete is False and any(i.code == "dataset_context_group_invalid" for i in result.issues)


def test_punctuation_only_control_is_retained_even_without_exact_key(pending):
    c = item(pending, 1, caseType="control", question="？")
    result = audit((c,))
    assert result.complete and result.groups[0].caseIds == (c.caseId,)


def test_review_label_change_changes_full_audit_digest_without_group_change(pending, reviewed):
    from eval.contracts import ExpectedLabel, case_digest
    c = item(pending, 1)
    c = c.model_copy(update={"reviewState": "reviewed", "review": reviewed.review.model_copy(update={"caseDigest": case_digest(c)})})
    changed = c.model_copy(update={"review": c.review.model_copy(update={"expectedLabel": ExpectedLabel(kind="answer", answer="不是")})})
    first, second = audit((c,)), audit((changed,))
    assert first.groups == second.groups and first.edges == second.edges
    assert first.candidateInputDigest != second.candidateInputDigest and first.auditDigest != second.auditDigest


def test_false_source_provenance_and_coerced_confirmation_do_not_grant_complete(pending):
    from eval.contracts import DatasetError
    from eval.grouping import audit_groups
    c = item(pending, 1); inventory = sources((c,))
    altered = inventory[0].model_copy(update={"sourceDigest": "b" * 64})
    result = audit_groups((c,), repair_cases=(), source_digests=(altered,), source_complete=True)
    assert not result.complete and result.issues[0].code == "dataset_source_coverage_invalid"
    with pytest.raises(DatasetError):
        audit_groups((c,), repair_cases=(), source_digests=inventory, source_complete="true")
