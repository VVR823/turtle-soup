"""Observed SQLite ordering, explicit runtime in every test worker thread."""
from concurrent.futures import ThreadPoolExecutor
from contextvars import ContextVar
from threading import Barrier, Event
from uuid import uuid4
import sqlite3

import pytest

from app import audit_store
from app.candidate_review_contracts import CandidatePublish, CandidateReviewError
from app.runtime import runtime_context
from .test_candidate_review_publication import approved
from .test_candidate_review_store import proposal
from .test_candidate_review_mutations import approve_intent, meta
from .test_rule_snapshots import rule_storage, release_rows
from .test_feedback_storage import snapshot
from .test_agent_store import raw_rows


def test_two_actual_candidates_with_the_same_corpus_and_base_have_one_pointer_cas_winner(rule_storage):
    first, _, cid1 = proposal(rule_storage)
    corpus = rule_storage.repair_corpus
    second, _, cid2 = proposal(rule_storage, corpus=corpus)
    assert cid1 != cid2
    items = []
    for owner, cid in ((first, cid1), (second, cid2)):
        owner.approve(cid, approve_intent(owner.detail(cid)))
        detail = owner.detail(cid)
        items.append((owner, cid, CandidatePublish(operationKey=str(uuid4()), expectedReviewVersion=1,
            expectedProofDigest=detail.proofDigest, expectedRuleVersion=detail.activeRuleVersion,
            expectedPointerVersion=0)))
    gate = Barrier(2)
    def publish(item):
        with runtime_context(rule_storage):
            gate.wait(timeout=5)
            try:
                return item[0].publish(item[1], item[2])
            except CandidateReviewError as error:
                return error
    with ThreadPoolExecutor(max_workers=2) as pool:
        results = list(pool.map(publish, items))
    assert sum(not isinstance(item, CandidateReviewError) for item in results) == 1
    assert [item.status for item in results if isinstance(item, CandidateReviewError)] == [409]
    assert sorted(row["status"] for row in raw_rows("rule_candidates")) == ["approved", "published"]
    assert len(release_rows()) == 2 and meta("active_baseline")[1] == 1


def test_publication_then_waiting_withdrawal_keeps_history_but_never_fresh_authority(rule_storage, monkeypatch):
    from app.feedback_contract import PrivacyReview
    from app.feedback_store import set_model_permission
    owner, run, cid, request = approved(rule_storage)
    entered, release, withdrawal_begin = Event(), Event(), Event()
    withdrawing = ContextVar("synthetic_publication_withdrawal", default=False)
    original_detail, connect = owner._detail, sqlite3.connect
    def gated_detail(conn, candidate_id):
        result = original_detail(conn, candidate_id)
        entered.set()
        assert release.wait(timeout=4)
        return result
    class Observed(sqlite3.Connection):
        def execute(self, sql, parameters=()):
            if withdrawing.get() and sql == "BEGIN IMMEDIATE":
                withdrawal_begin.set()
            return super().execute(sql, parameters)
    def withdraw():
        with runtime_context(rule_storage):
            token = withdrawing.set(True)
            try:
                return set_model_permission(run.feedbackId, run.manifest.context.sourceFeedbackVersion,
                    review=PrivacyReview(safeForModel=False, reviewNote="Synthetic waiting withdrawal"))
            finally:
                withdrawing.reset(token)
    monkeypatch.setattr(owner, "_detail", gated_detail)
    monkeypatch.setattr(sqlite3, "connect", lambda *a, **kw: connect(*a, **kw, factory=Observed))
    with ThreadPoolExecutor(max_workers=2) as pool:
        first = pool.submit(owner.publish, cid, request)
        second = None
        try:
            assert entered.wait(timeout=3)
            second = pool.submit(withdraw)
            assert withdrawal_begin.wait(timeout=3) and not second.done()
        finally:
            release.set()
        assert first.result(timeout=5).candidateStatus == "published"
        assert second.result(timeout=5).safeForModel is False
    result = owner.detail(cid)
    assert result.candidateStatus == "published" and result.availability == "stale"
    assert result.material is result.proofDigest is result.review is None


def test_closing_after_actual_publication_audit_cannot_commit_any_partial_release(rule_storage, monkeypatch):
    owner, _, cid, request = approved(rule_storage)
    before = snapshot(); insert = audit_store.insert_business_event
    def close_after_insert(conn, event):
        result = insert(conn, event)
        if event.eventType == "candidate_published":
            rule_storage.closed = True
        return result
    monkeypatch.setattr(audit_store, "insert_business_event", close_after_insert)
    try:
        with pytest.raises(CandidateReviewError) as error:
            owner.publish(cid, request)
        assert error.value.status == 503
    finally:
        rule_storage.closed = False
    assert snapshot() == before
