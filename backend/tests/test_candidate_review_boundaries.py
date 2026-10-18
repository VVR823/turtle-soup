"""Real stored synthetic proof boundaries and SQLite commit failure semantics."""
import sqlite3
from concurrent.futures import ThreadPoolExecutor
from contextvars import ContextVar
from threading import Event
from uuid import uuid4

import pytest
from pydantic import ValidationError

from app import baselines, db
from app.candidate_review_contracts import (CandidateOperationReceipt, CandidateOperationResult,
    CandidateReviewError, CandidateReviewIntent, ReviewState, CandidateReject)
from .test_rule_snapshots import rule_storage
from .test_candidate_review_store import proposal
from .test_candidate_review_mutations import approve_intent, meta
from .test_feedback_storage import snapshot
from .test_agent_store import raw_rows


def approved(active):
    review, run, cid = proposal(active)
    intent = approve_intent(review.detail(cid))
    review.approve(cid, intent)
    return review, run, cid, intent, meta("candidate_operation:" + intent.operationKey)[0]


@pytest.mark.parametrize("part,model", [("receipt", CandidateOperationReceipt), ("result", CandidateOperationResult),
    ("state", ReviewState), ("intent", CandidateReviewIntent)])
@pytest.mark.parametrize("value", [True, 1.0, "1"], ids=["boolean", "float", "string"])
def test_stored_proof_contract_requires_real_integer_schema_not_coerced_one(rule_storage, part, model, value):
    _, _, _, _, operation = approved(rule_storage)
    payload = operation if part == "receipt" else operation[part]
    payload["schemaVersion"] = value
    with pytest.raises(ValidationError):
        model.model_validate_json(baselines.canonical_json(payload))


def test_self_consistent_saved_review_cannot_predate_actual_candidate_creation(rule_storage):
    review, _, cid, intent, operation = approved(rule_storage)
    state, version = meta("candidate_review:" + cid)
    state["reviewedAt"] = operation["state"]["reviewedAt"] = 0.0
    conn = db._connect()
    try:
        conn.execute("UPDATE rule_candidates SET reviewed_at=0 WHERE id=?", (cid,))
        conn.execute("UPDATE runtime_meta SET value_json=? WHERE key=?",
            (baselines.canonical_json(state), "candidate_review:" + cid))
        conn.execute("UPDATE runtime_meta SET value_json=? WHERE key=?",
            (baselines.canonical_json(operation), "candidate_operation:" + intent.operationKey))
        conn.commit()
    finally:
        conn.close()
    before = snapshot()
    with pytest.raises(CandidateReviewError) as caught:
        review.detail(cid)
    assert caught.value.code == "candidate_review_corrupt" and snapshot() == before


def test_clock_reversal_after_approval_cannot_save_an_earlier_rejection(rule_storage):
    review, _, cid, _, operation = approved(rule_storage)
    created = baselines.strict_json(raw_rows("rule_candidates")[0]["candidate_json"])["createdAt"]
    reviewed = operation["state"]["reviewedAt"]
    assert reviewed > created
    review.agent_store.clock = lambda: (created + reviewed) / 2
    before = snapshot()
    with pytest.raises(CandidateReviewError) as caught:
        review.reject(cid, CandidateReject(operationKey=str(uuid4()), expectedReviewVersion=1,
            reviewNote="Synthetic reversed-clock rejection"))
    assert caught.value.status == 503 and snapshot() == before


def test_consistent_latest_rejection_cannot_predate_its_actual_prior_approval(rule_storage):
    review, _, cid, _, approval = approved(rule_storage)
    intent = CandidateReject(operationKey=str(uuid4()), expectedReviewVersion=1, reviewNote="Synthetic later rejection")
    review.reject(cid, intent)
    created = baselines.strict_json(raw_rows("rule_candidates")[0]["candidate_json"])["createdAt"]
    earlier = (created + approval["state"]["reviewedAt"]) / 2
    state, _ = meta("candidate_review:" + cid)
    operation, _ = meta("candidate_operation:" + intent.operationKey)
    state["reviewedAt"] = operation["state"]["reviewedAt"] = earlier
    conn = db._connect()
    try:
        conn.execute("UPDATE rule_candidates SET reviewed_at=? WHERE id=?", (earlier, cid))
        conn.execute("UPDATE runtime_meta SET value_json=? WHERE key=?", (baselines.canonical_json(state), "candidate_review:" + cid))
        conn.execute("UPDATE runtime_meta SET value_json=? WHERE key=?", (baselines.canonical_json(operation), "candidate_operation:" + intent.operationKey))
        conn.commit()
    finally:
        conn.close()
    before = snapshot()
    with pytest.raises(CandidateReviewError) as caught:
        review.detail(cid)
    assert caught.value.code == "candidate_review_corrupt" and snapshot() == before


def test_shutdown_after_actual_audit_insert_rolls_back_whole_review(rule_storage, monkeypatch):
    from app import audit_store
    review, _, cid = proposal(rule_storage); intent = approve_intent(review.detail(cid)); before = snapshot()
    insert = audit_store.insert_business_event

    def close_after_insert(conn, event):
        result = insert(conn, event)
        with rule_storage.lock:
            rule_storage.closed = True
        return result

    monkeypatch.setattr(audit_store, "insert_business_event", close_after_insert)
    with pytest.raises(CandidateReviewError) as caught:
        review.approve(cid, intent)
    assert caught.value.status == 503 and snapshot() == before


@pytest.mark.parametrize("point", ["review_metadata", "candidate_status", "operation_receipt", "audit", "before_commit"])
def test_each_sql_write_or_before_commit_failure_leaves_no_partial_review(rule_storage, monkeypatch, point):
    review, _, cid = proposal(rule_storage); intent = approve_intent(review.detail(cid)); before = snapshot()
    connect = sqlite3.connect

    class FailingConnection(sqlite3.Connection):
        def execute(self, sql, parameters=()):
            selected = (point == "review_metadata" and sql.startswith("INSERT INTO runtime_meta") and str(parameters[0]).startswith("candidate_review:"))
            selected |= point == "candidate_status" and sql.startswith("UPDATE rule_candidates SET status=")
            selected |= point == "operation_receipt" and sql.startswith("INSERT INTO runtime_meta") and str(parameters[0]).startswith("candidate_operation:")
            selected |= point == "audit" and sql.startswith("INSERT INTO audit_events")
            if selected:
                raise sqlite3.OperationalError("Synthetic selected SQLite write failure")
            return super().execute(sql, parameters)

        def commit(self):
            if point == "before_commit":
                raise sqlite3.OperationalError("Synthetic commit not executed")
            return super().commit()

    def failed_connect(*args, **kwargs):
        return connect(*args, **{**kwargs, "factory": FailingConnection})

    with monkeypatch.context() as patch:
        patch.setattr(sqlite3, "connect", failed_connect)
        with pytest.raises(CandidateReviewError) as caught:
            review.approve(cid, intent)
    assert caught.value.status == 503 and snapshot() == before


def test_actual_commit_followed_by_lost_ack_replays_saved_result_not_an_extra_approval(rule_storage, monkeypatch):
    review, _, cid = proposal(rule_storage); intent = approve_intent(review.detail(cid))
    connect = sqlite3.connect

    class LostAcknowledgement(sqlite3.Connection):
        def commit(self):
            super().commit()
            raise sqlite3.OperationalError("Synthetic acknowledgement lost AFTER successful commit")

    def interrupted_connect(*args, **kwargs):
        return connect(*args, **{**kwargs, "factory": LostAcknowledgement})

    with monkeypatch.context() as patch:
        patch.setattr(sqlite3, "connect", interrupted_connect)
        with pytest.raises(CandidateReviewError) as caught:
            review.approve(cid, intent)
    assert caught.value.status == 503
    operation, version = meta("candidate_operation:" + intent.operationKey)
    before = snapshot()
    result = review.approve(cid, intent)
    assert result.candidateStatus == "approved" and result.reviewVersion == 1 and version == 0
    assert result.model_dump(mode="json") == operation["result"] and snapshot() == before


def test_approval_then_waiting_withdrawal_is_serialized_and_cannot_leave_fresh_authority(rule_storage, monkeypatch):
    from app.feedback_contract import PrivacyReview
    from app.feedback_store import set_model_permission
    from app.runtime import runtime_context
    review, run, cid = proposal(rule_storage); intent = approve_intent(review.detail(cid))
    entered, release, withdrawal_begin = Event(), Event(), Event()
    withdrawing = ContextVar("synthetic_review_withdrawal", default=False)
    original_detail, connect = review._detail, sqlite3.connect

    def gated_detail(conn, candidate_id):
        value = original_detail(conn, candidate_id)
        entered.set()
        assert release.wait(timeout=4)
        return value

    class ObservedConnection(sqlite3.Connection):
        def execute(self, sql, parameters=()):
            if withdrawing.get() and sql == "BEGIN IMMEDIATE":
                withdrawal_begin.set()
            return super().execute(sql, parameters)

    def observed_connect(*args, **kwargs):
        return connect(*args, **{**kwargs, "factory": ObservedConnection})

    def withdraw():
        # A new thread must never fall back to standalone/default user data.
        with runtime_context(rule_storage):
            token = withdrawing.set(True)
            try:
                return set_model_permission(run.feedbackId, run.manifest.context.sourceFeedbackVersion,
                    review=PrivacyReview(safeForModel=False, reviewNote="Synthetic concurrent withdrawal"))
            finally:
                withdrawing.reset(token)

    monkeypatch.setattr(review, "_detail", gated_detail)
    monkeypatch.setattr(sqlite3, "connect", observed_connect)
    with ThreadPoolExecutor(max_workers=2) as pool:
        first = pool.submit(review.approve, cid, intent)
        second = None
        try:
            assert entered.wait(timeout=3)
            second = pool.submit(withdraw)
            assert withdrawal_begin.wait(timeout=3) and not second.done()
        finally:
            release.set()
        assert first.result(timeout=5).candidateStatus == "approved"
        assert second.result(timeout=5).safeForModel is False
    result = review.detail(cid)
    assert result.candidateStatus == "approved"  # history, not renewed permission
    assert result.availability == "stale" and result.proofDigest is None and result.material is None and result.review is None
