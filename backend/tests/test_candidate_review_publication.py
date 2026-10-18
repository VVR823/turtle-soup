"""Native atomic publication of actually generated synthetic candidates."""
from concurrent.futures import ThreadPoolExecutor
from threading import Barrier
from uuid import uuid4
import sqlite3

import pytest

from app import baselines, db
from app.candidate_review_contracts import CandidatePublish, CandidateRollback, CandidateReviewError
from app.runtime import runtime_context
from .test_candidate_review_store import proposal
from .test_candidate_review_mutations import approve_intent, meta
from .test_rule_snapshots import rule_storage, release_rows
from .test_feedback_storage import snapshot
from .test_agent_store import raw_rows


def approved(active):
    owner, run, cid = proposal(active)
    owner.approve(cid, approve_intent(owner.detail(cid)))
    detail = owner.detail(cid)
    request = CandidatePublish(operationKey=str(uuid4()), expectedReviewVersion=detail.reviewVersion,
        expectedProofDigest=detail.proofDigest, expectedRuleVersion=detail.activeRuleVersion,
        expectedPointerVersion=detail.activePointerVersion)
    return owner, run, cid, request


def test_publish_atomically_binds_release_pointer_candidate_receipts_audit_and_immutable_run(rule_storage):
    from app.rule_contract import read_rule_snapshot
    owner, run, cid, request = approved(rule_storage)
    old_releases = release_rows(); old_steps = raw_rows("agent_steps"); old_runs = raw_rows("agent_runs")
    result = owner.publish(cid, request)
    assert result.candidateStatus == result.action == "published" and result.reviewVersion == 2
    assert result.publishedRuleVersion != request.expectedRuleVersion
    row, = raw_rows("rule_candidates")
    assert row["status"] == "published" and row["published_release_id"] == result.publishedRuleVersion
    assert baselines.strict_json(row["candidate_json"])["status"] == "pending"
    assert meta("active_baseline") == ({"schemaVersion": 1, "ruleVersion": result.publishedRuleVersion}, 1)
    assert raw_rows("agent_steps") == old_steps and raw_rows("agent_runs") == old_runs
    assert release_rows()[:1] == old_releases and len(release_rows()) == 2
    detail = owner.detail(cid)
    assert detail.agentStatus.state == "awaiting_review" and detail.agentStatus.candidateId == cid
    assert detail.candidateStatus == "published" and detail.reviewVersion == 2
    assert detail.availability == "historical" and detail.proofDigest is None
    assert detail.material.report.inputCaseCount == 7 and detail.material.oldTarget.answer == "不是"
    assert detail.material.draft.answer == "是" and detail.review.reviewReceipt.answerSupported is True
    candidate_op, version = meta("candidate_operation:" + request.operationKey)
    rule_op, rule_version = meta("rule_operation:" + request.operationKey)
    assert version == rule_version == 0 and candidate_op["result"] == result.model_dump(mode="json")
    assert rule_op["result"]["ruleVersion"] == result.publishedRuleVersion
    conn = db._connect()
    try:
        actual = read_rule_snapshot(conn, run.manifest.context.observedPuzzleVersion, result.publishedRuleVersion).exactRules[0]
        assert actual.answer == "是" and actual.reviewReceipt == detail.review.reviewReceipt
    finally:
        conn.close()
    assert [row["event_type"] for row in raw_rows("audit_events")].count("candidate_published") == 1
    assert [row["event_type"] for row in raw_rows("audit_events")].count("rule_published") == 1


def test_historical_publish_ack_replays_after_rollback_expiry_and_privacy_withdrawal(rule_storage, monkeypatch):
    from app.feedback_store import set_model_permission
    from app.feedback_contract import PrivacyReview
    owner, run, cid, request = approved(rule_storage)
    published = owner.publish(cid, request)
    rollback = CandidateRollback(operationKey=str(uuid4()), targetRuleVersion=request.expectedRuleVersion,
        expectedRuleVersion=published.publishedRuleVersion, expectedPointerVersion=1, reason="Synthetic rollback")
    reverted = owner.rollback(rollback)
    assert reverted.ruleVersion == request.expectedRuleVersion and reverted.pointerVersion == 2
    monkeypatch.setattr(owner.agent_store, "clock", lambda: run.checkpoint.deadlineAt + 1000)
    detail = owner.detail(cid)
    assert detail.candidateStatus == "published" and detail.agentStatus.state == "awaiting_review"
    assert detail.availability == "historical" and detail.material is not None
    set_model_permission(run.feedbackId, run.manifest.context.sourceFeedbackVersion,
        review=PrivacyReview(safeForModel=False, reviewNote="Synthetic revoke"))
    before = snapshot()
    assert owner.publish(cid, request) == published and owner.rollback(rollback) == reverted
    assert snapshot() == before and owner.detail(cid).material is None


@pytest.mark.parametrize("change", ["version", "pointer", "base", "proof"])
def test_fresh_publish_requires_current_approved_proof_and_both_counters(rule_storage, change):
    owner, _, cid, request = approved(rule_storage)
    changed = {"version": {"expectedReviewVersion": 0}, "pointer": {"expectedPointerVersion": 1},
        "base": {"expectedRuleVersion": "r1:" + "f" * 64}, "proof": {"expectedProofDigest": "f" * 64}}[change]
    before = snapshot()
    with pytest.raises(CandidateReviewError) as error:
        owner.publish(cid, request.model_copy(update=changed))
    assert error.value.status == 409 and snapshot() == before


def test_same_publish_key_changed_body_or_subject_is_not_new_authority(rule_storage):
    owner, _, cid, request = approved(rule_storage)
    owner.publish(cid, request)
    before = snapshot()
    for subject, body in ((cid, request.model_copy(update={"expectedPointerVersion": 1})), (str(uuid4()), request)):
        with pytest.raises(CandidateReviewError) as error:
            owner.publish(subject, body)
        assert error.value.code == "candidate_operation_conflict" and snapshot() == before


def test_two_distinct_publish_operations_have_one_effective_release_and_pointer_transition(rule_storage):
    owner, _, cid, request = approved(rule_storage)
    gate = Barrier(2)
    def publish(key):
        with runtime_context(rule_storage):
            gate.wait(timeout=5)
            try:
                return owner.publish(cid, request.model_copy(update={"operationKey": key}))
            except CandidateReviewError as error:
                return error
    with ThreadPoolExecutor(max_workers=2) as pool:
        results = list(pool.map(publish, (str(uuid4()), str(uuid4()))))
    assert sum(not isinstance(row, CandidateReviewError) for row in results) == 1
    assert [row.status for row in results if isinstance(row, CandidateReviewError)] == [409]
    assert len(release_rows()) == 2 and meta("active_baseline")[1] == 1


@pytest.mark.parametrize("boundary", ["release", "pointer", "rule_operation", "candidate", "review", "candidate_operation", "rule_audit", "candidate_audit", "commit"])
def test_all_publication_writes_use_one_owned_transaction_and_roll_back_together(rule_storage, monkeypatch, boundary):
    owner, _, cid, request = approved(rule_storage)
    before = snapshot(); connect = sqlite3.connect
    injected = []
    class Fault(sqlite3.Connection):
        def execute(self, sql, parameters=()):
            if ((boundary == "release" and sql.startswith("INSERT INTO rule_releases"))
                or (boundary == "pointer" and sql.startswith("UPDATE runtime_meta") and "active_baseline" in sql)
                or (boundary == "rule_operation" and sql.startswith("INSERT INTO runtime_meta") and parameters[0].startswith("rule_operation:"))
                or (boundary == "candidate" and sql.startswith("UPDATE rule_candidates"))
                or (boundary == "review" and sql.startswith("UPDATE runtime_meta") and isinstance(parameters[1], str) and parameters[1].startswith("candidate_review:"))
                or (boundary == "candidate_operation" and sql.startswith("INSERT INTO runtime_meta") and parameters[0].startswith("candidate_operation:"))
                or (boundary == "rule_audit" and sql.startswith("INSERT INTO audit_events") and "rule_published" in parameters)
                or (boundary == "candidate_audit" and sql.startswith("INSERT INTO audit_events") and "candidate_published" in parameters)):
                injected.append(boundary)
                raise sqlite3.OperationalError("Synthetic publication write fault")
            return super().execute(sql, parameters)
        def commit(self):
            if boundary == "commit":
                injected.append(boundary)
                raise sqlite3.OperationalError("Synthetic precommit failure")
            return super().commit()
    def configured(*args, **kwargs):
        return connect(*args, **kwargs, factory=Fault)
    with monkeypatch.context() as patch:
        patch.setattr(sqlite3, "connect", configured)
        with pytest.raises(CandidateReviewError) as error:
            owner.publish(cid, request)
        assert error.value.status == 503
    assert injected == [boundary] and snapshot() == before


def test_sameconn_rule_publisher_never_commits_or_initializes_caller_database(rule_storage, monkeypatch):
    from .test_rule_publication import prepare, publisher
    request = prepare(); owned = publisher(request)
    before = snapshot(); conn = db._connect()
    def forbidden(*args, **kwargs):
        raise AssertionError("Same-connection path opened another database")
    try:
        conn.execute("BEGIN IMMEDIATE")
        with monkeypatch.context() as patch:
            patch.setattr(db, "initialize", forbidden)
            patch.setattr(db, "_connect", forbidden)
            result = owned.publish_in_transaction(conn, request)
            assert conn.in_transaction and result.pointerVersion == 1
        conn.rollback()
    finally:
        conn.close()
    assert snapshot() == before


def test_missing_actual_approval_operation_cannot_publish_even_with_typed_approved_metadata(rule_storage):
    owner, _, cid, request = approved(rule_storage)
    state, _ = meta("candidate_review:" + cid)
    conn = db._connect()
    try:
        conn.execute("DELETE FROM runtime_meta WHERE key=?", ("candidate_operation:" + state["approvalOperationKey"],))
        conn.commit()
    finally:
        conn.close()
    before = snapshot()
    with pytest.raises(CandidateReviewError) as error:
        owner.publish(cid, request)
    assert error.value.status == 503 and snapshot() == before and len(release_rows()) == 1


def test_committed_publication_with_lost_ack_replays_exact_saved_result(rule_storage, monkeypatch):
    owner, _, cid, request = approved(rule_storage)
    connect = sqlite3.connect
    class LostAck(sqlite3.Connection):
        def commit(self):
            super().commit()
            raise sqlite3.OperationalError("Synthetic acknowledgement lost AFTER commit")
    with monkeypatch.context() as patch:
        patch.setattr(sqlite3, "connect", lambda *a, **kw: connect(*a, **kw, factory=LostAck))
        with pytest.raises(CandidateReviewError) as error:
            owner.publish(cid, request)
        assert error.value.status == 503
    before = snapshot()
    result = owner.publish(cid, request)
    assert result.candidateStatus == "published" and result.reviewVersion == 2
    assert len(release_rows()) == 2 and snapshot() == before


def test_privacy_withdrawn_before_publication_refuses_all_writes(rule_storage):
    from app.feedback_store import set_model_permission
    from app.feedback_contract import PrivacyReview
    owner, run, cid, request = approved(rule_storage)
    set_model_permission(run.feedbackId, run.manifest.context.sourceFeedbackVersion,
        review=PrivacyReview(safeForModel=False, reviewNote="Synthetic withdraw before publish"))
    before = snapshot()
    with pytest.raises(CandidateReviewError) as error:
        owner.publish(cid, request)
    assert error.value.status == 409 and snapshot() == before


def test_missing_rule_operation_makes_historical_candidate_publication_ack_unavailable(rule_storage):
    owner, _, cid, request = approved(rule_storage)
    owner.publish(cid, request)
    conn = db._connect()
    try:
        conn.execute("DELETE FROM runtime_meta WHERE key=?", ("rule_operation:" + request.operationKey,))
        conn.commit()
    finally:
        conn.close()
    before = snapshot()
    with pytest.raises(CandidateReviewError) as error:
        owner.publish(cid, request)
    assert error.value.status == 503 and snapshot() == before
