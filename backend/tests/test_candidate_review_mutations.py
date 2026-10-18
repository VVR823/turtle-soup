"""Explicit synthetic admin intents; neither real human nor provider evidence."""
from concurrent.futures import ThreadPoolExecutor
from threading import Barrier
from uuid import uuid4

import pytest

from app import baselines, db
from app.candidate_review_contracts import CandidateApprove, CandidateReject, CandidateReviewError
from .test_rule_snapshots import rule_storage, schema2
from .test_candidate_review_store import proposal
from .test_feedback_storage import snapshot
from .test_agent_store import raw_rows


def approve_intent(detail, **changes):
    return CandidateApprove.model_validate({**dict(operationKey=str(uuid4()), expectedReviewVersion=detail.reviewVersion,
        expectedProofDigest=detail.proofDigest, answerSupported=True, contextIndependent=True,
        reviewNote="Synthetic explicit admin confirmation, NOT real human-quality evidence"), **changes})


def meta(key):
    conn = db._connect()
    try:
        row = conn.execute("SELECT value_json,row_version FROM runtime_meta WHERE key=?", (key,)).fetchone()
        return None if row is None else (baselines.strict_json(row[0]), row[1])
    finally:
        conn.close()


def test_approve_saves_two_digest_domains_real_receipt_cas_audit_without_changing_agent_or_pointer(rule_storage):
    review, run, cid = proposal(rule_storage)
    intent = approve_intent(review.detail(cid))
    steps = raw_rows("agent_steps"); runs = raw_rows("agent_runs"); pointer = meta("active_baseline")
    result = review.approve(cid, intent)
    state, version = meta("candidate_review:" + cid)
    operation, receipt_version = meta("candidate_operation:" + intent.operationKey)
    assert result.action == result.candidateStatus == "approved" and result.reviewVersion == version == 1
    assert result.candidateId == cid and result.operationKey == intent.operationKey and result.publishedRuleVersion is None
    assert receipt_version == 0 and operation["result"] == result.model_dump(mode="json")
    assert state["candidateDraftDigest"] != state["publicationDraftDigest"]
    assert state["reviewReceipt"]["draftDigest"] == state["publicationDraftDigest"]
    assert state["reviewReceipt"]["answerSupported"] is True and state["reviewReceipt"]["contextIndependent"] is True
    assert state["reviewReceipt"]["reviewNote"] == intent.reviewNote
    assert state["approvalOperationKey"] == state["lastOperationKey"] == intent.operationKey
    detail = review.detail(cid)
    assert detail.candidateStatus == "approved" and detail.reviewVersion == 1 and detail.review.reviewNote == intent.reviewNote
    assert detail.agentStatus.state == "awaiting_review" and detail.agentStatus.candidateId == cid
    assert raw_rows("agent_steps") == steps and raw_rows("agent_runs") == runs and meta("active_baseline") == pointer
    events = [row for row in raw_rows("audit_events") if row["event_type"] == "candidate_reviewed"]
    assert len(events) == 1 and events[0]["run_id"] == run.id
    assert "是谁" not in events[0]["details_json"] and "小明" not in events[0]["details_json"]
    assert rule_storage.model.calls == []


def test_same_approval_replays_read_only_after_withdrawal_and_changed_active_base(rule_storage):
    from app.feedback_store import set_model_permission
    from app.feedback_contract import PrivacyReview
    review, run, cid = proposal(rule_storage)
    intent = approve_intent(review.detail(cid)); original = review.approve(cid, intent)
    set_model_permission(run.feedbackId, run.manifest.context.sourceFeedbackVersion,
        review=PrivacyReview(safeForModel=False, reviewNote="Synthetic withdrawn"))
    conn = db._connect()
    try:
        _, version, _ = schema2(conn)
        conn.execute("UPDATE runtime_meta SET value_json=?,row_version=row_version+1 WHERE key='active_baseline'",
            (baselines.canonical_json(dict(schemaVersion=1, ruleVersion=version)),))
        conn.commit()
    finally:
        conn.close()
    before = snapshot()
    assert review.approve(cid, intent) == original and snapshot() == before
    detail = review.detail(cid)
    assert detail.availability == "stale" and detail.material is None and detail.review is None


@pytest.mark.parametrize("changed", ["note", "candidate", "action"])
def test_saved_operation_cannot_be_reused_for_changed_subject_or_intent(rule_storage, changed):
    review, _, cid = proposal(rule_storage)
    intent = approve_intent(review.detail(cid)); review.approve(cid, intent)
    before = snapshot()
    with pytest.raises(CandidateReviewError) as caught:
        if changed == "action":
            review.reject(cid, CandidateReject(operationKey=intent.operationKey, expectedReviewVersion=0, reviewNote=intent.reviewNote))
        else:
            review.approve(str(uuid4()) if changed == "candidate" else cid,
                intent.model_copy(update={"reviewNote": "Different synthetic note"}) if changed == "note" else intent)
    assert caught.value.code == "candidate_operation_conflict" and caught.value.status == 409 and snapshot() == before


def test_stale_approval_proof_cannot_write_any_review_state(rule_storage):
    from app.feedback_store import set_model_permission
    from app.feedback_contract import PrivacyReview
    review, run, cid = proposal(rule_storage)
    intent = approve_intent(review.detail(cid))
    set_model_permission(run.feedbackId, run.manifest.context.sourceFeedbackVersion,
        review=PrivacyReview(safeForModel=False, reviewNote="Synthetic withdrawal"))
    before = snapshot()
    with pytest.raises(CandidateReviewError) as caught:
        review.approve(cid, intent)
    assert caught.value.status == 409 and snapshot() == before and meta("candidate_review:" + cid) is None


def test_two_current_approvers_only_one_effective_transition(rule_storage):
    review, _, cid = proposal(rule_storage)
    detail = review.detail(cid)
    intents = [approve_intent(detail), approve_intent(detail)]
    barrier = Barrier(2)

    def attempt(intent):
        barrier.wait(timeout=4)
        try:
            return review.approve(cid, intent).candidateStatus
        except CandidateReviewError as error:
            return error.status

    with ThreadPoolExecutor(max_workers=2) as pool:
        results = list(pool.map(attempt, intents))
    assert results.count("approved") == results.count(409) == 1
    assert meta("candidate_review:" + cid)[1] == 1
    assert len([row for row in raw_rows("audit_events") if row["event_type"] == "candidate_reviewed"]) == 1


@pytest.mark.parametrize("approved_first", [False, True])
def test_reject_can_dismiss_withdrawn_pending_or_approved_preserving_original_history(rule_storage, approved_first):
    from app.feedback_store import set_model_permission
    from app.feedback_contract import PrivacyReview
    review, run, cid = proposal(rule_storage)
    if approved_first:
        review.approve(cid, approve_intent(review.detail(cid)))
    set_model_permission(run.feedbackId, run.manifest.context.sourceFeedbackVersion,
        review=PrivacyReview(safeForModel=False, reviewNote="Synthetic withdrawal"))
    pointer = meta("active_baseline"); steps = raw_rows("agent_steps"); runs = raw_rows("agent_runs")
    intent = CandidateReject(operationKey=str(uuid4()), expectedReviewVersion=1 if approved_first else 0,
        reviewNote="Synthetic discard, no publication")
    result = review.reject(cid, intent)
    assert result.candidateStatus == "rejected" and result.reviewVersion == (2 if approved_first else 1)
    assert raw_rows("rule_candidates")[0]["status"] == "rejected"
    assert raw_rows("agent_steps") == steps and raw_rows("agent_runs") == runs and meta("active_baseline") == pointer
    before = snapshot()
    assert review.reject(cid, intent) == result and snapshot() == before
    with pytest.raises(CandidateReviewError):
        review.reject(cid, intent.model_copy(update={"operationKey": str(uuid4()), "expectedReviewVersion": result.reviewVersion}))


def test_audit_failure_rolls_back_candidate_metadata_operation_and_receipt(rule_storage, monkeypatch):
    from app import audit_store
    review, _, cid = proposal(rule_storage); intent = approve_intent(review.detail(cid)); before = snapshot()

    def fail(*args, **kwargs):
        raise audit_store.AuditPersistenceError("Synthetic write failure")

    monkeypatch.setattr(audit_store, "insert_business_event", fail)
    with pytest.raises(CandidateReviewError) as caught:
        review.approve(cid, intent)
    assert caught.value.status == 503 and snapshot() == before


def test_approved_metadata_requires_actual_bound_approval_operation(rule_storage):
    review, _, cid = proposal(rule_storage); intent = approve_intent(review.detail(cid)); review.approve(cid, intent)
    conn = db._connect()
    try:
        conn.execute("DELETE FROM runtime_meta WHERE key=?", ("candidate_operation:" + intent.operationKey,))
        conn.commit()
    finally:
        conn.close()
    before = snapshot()
    with pytest.raises(CandidateReviewError) as caught:
        review.detail(cid)
    assert caught.value.code == "candidate_review_corrupt" and caught.value.status == 503 and snapshot() == before


@pytest.mark.parametrize("approved_first", [False, True])
def test_rejected_detail_shows_actual_rejection_reason_separate_from_prior_approval(rule_storage, approved_first):
    review, _, cid = proposal(rule_storage)
    if approved_first:
        review.approve(cid, approve_intent(review.detail(cid)))
    intent = CandidateReject(operationKey=str(uuid4()), expectedReviewVersion=1 if approved_first else 0,
        reviewNote="Synthetic explicit rejection, NOT the approval reason")
    review.reject(cid, intent)
    detail = review.detail(cid)
    assert detail.availability == "historical" and detail.proofDigest is None
    assert detail.review.reviewNote == intent.reviewNote and detail.review.status == "rejected"
    if approved_first:
        assert detail.review.reviewReceipt.reviewNote != intent.reviewNote
    else:
        assert detail.review.reviewReceipt is None


def test_old_approval_ack_replays_after_later_rejection_without_resurrecting_approval(rule_storage):
    review, _, cid = proposal(rule_storage)
    intent = approve_intent(review.detail(cid)); original = review.approve(cid, intent)
    review.reject(cid, CandidateReject(operationKey=str(uuid4()), expectedReviewVersion=1, reviewNote="Synthetic later rejection"))
    before = snapshot()
    assert review.approve(cid, intent) == original and snapshot() == before
    assert review.detail(cid).candidateStatus == "rejected"


@pytest.mark.parametrize("change", ["false_flag", "changed_note", "wrong_subject", "wrong_receipt", "result_version", "operation_row_version"])
def test_changed_actual_approval_operation_is_refused_without_fabricated_authority(rule_storage, change):
    review, _, cid = proposal(rule_storage)
    intent = approve_intent(review.detail(cid)); review.approve(cid, intent)
    key = "candidate_operation:" + intent.operationKey
    operation, _ = meta(key)
    if change == "false_flag":
        operation["intent"]["request"]["answerSupported"] = False
    elif change == "changed_note":
        operation["intent"]["request"]["reviewNote"] = "Changed synthetic review"
    elif change == "wrong_subject":
        operation["intent"]["candidateId"] = str(uuid4())
    elif change == "wrong_receipt":
        operation["state"]["reviewReceipt"]["draftDigest"] = "e" * 64
    elif change == "result_version":
        operation["result"]["reviewVersion"] = 2
    conn = db._connect()
    try:
        conn.execute("UPDATE runtime_meta SET value_json=?,row_version=? WHERE key=?",
            (baselines.canonical_json(operation), 1 if change == "operation_row_version" else 0, key))
        conn.commit()
    finally:
        conn.close()
    before = snapshot()
    with pytest.raises(CandidateReviewError) as caught:
        review.detail(cid)
    assert caught.value.code == "candidate_review_corrupt" and snapshot() == before


@pytest.mark.parametrize("field", ["answerSupported", "contextIndependent"])
def test_review_audit_does_not_coerce_integer_one_into_human_confirmation(rule_storage, field):
    from app.audit_events import AuditEvent
    from pydantic import ValidationError
    review, _, cid = proposal(rule_storage); review.approve(cid, approve_intent(review.detail(cid)))
    event = next(row for row in raw_rows("audit_events") if row["event_type"] == "candidate_reviewed")
    value = baselines.strict_json(event["details_json"])
    value["details"][field] = 1
    with pytest.raises(ValidationError):
        AuditEvent.model_validate_json(baselines.canonical_json(value))
