"""Real isolated new-session/cache/rollback behavior, not production evidence."""
from uuid import uuid4
import sqlite3

import pytest

from app import db
from app.candidate_review_contracts import CandidateRollback, CandidateReviewError
from .test_candidate_review_publication import approved
from .test_candidate_review_store import proposal
from .test_candidate_review_mutations import meta, approve_intent
from .test_rule_snapshots import rule_storage, release_rows
from .test_feedback_storage import snapshot
from .test_agent_store import raw_rows


def rollback_body(request, result, **changes):
    return {**dict(operationKey=str(uuid4()), targetRuleVersion=request.expectedRuleVersion,
        expectedRuleVersion=result.publishedRuleVersion, expectedPointerVersion=1, reason="Synthetic rollback reason"), **changes}


def test_new_sessions_and_versioned_cache_follow_publish_then_rollback_without_losing_new_writes(rule_storage):
    from app.game_service import ask
    from app.schemas import ChatRequest
    owner, run, cid, request = approved(rule_storage)
    old = db.create_game_once("synthetic", None, str(uuid4()))["sessionId"]
    published = owner.publish(cid, request)
    new = db.create_game_once("synthetic", None, str(uuid4()))["sessionId"]
    def answer(sid):
        return ask(ChatRequest(sessionId=sid, soupId="synthetic", question="小明是凶手吗？")).safeResponse["reply"]
    assert answer(old) == "不是" and answer(new) == "是"
    releases = release_rows(); steps = raw_rows("agent_steps"); candidates = raw_rows("rule_candidates")
    new_turns = tuple(db.get_session(new)["messages"])
    reverted = owner.rollback(rollback_body(request, published))
    restored = db.create_game_once("synthetic", None, str(uuid4()))["sessionId"]
    assert reverted.ruleVersion == request.expectedRuleVersion and reverted.pointerVersion == 2
    assert answer(restored) == "不是" and answer(new) == "是"
    assert db.get_session(old)["ruleVersion"] == db.get_session(restored)["ruleVersion"] == request.expectedRuleVersion
    assert db.get_session(new)["ruleVersion"] == published.publishedRuleVersion
    assert tuple(db.get_session(new)["messages"])[:len(new_turns)] == new_turns
    assert release_rows() == releases and raw_rows("agent_steps") == steps and raw_rows("rule_candidates") == candidates
    assert owner.detail(cid).candidateStatus == "published" and rule_storage.model.calls == []


def test_rollback_sameconn_never_initializes_or_commits_caller_transaction(rule_storage, monkeypatch):
    from app.rule_publication import RulePublisher
    owner, _, cid, request = approved(rule_storage)
    published = owner.publish(cid, request)
    before = snapshot(); conn = db._connect()
    def forbidden(*args, **kwargs):
        raise AssertionError("Internal rollback created storage or another transaction")
    try:
        conn.execute("BEGIN IMMEDIATE")
        with monkeypatch.context() as patch:
            patch.setattr(db, "initialize", forbidden)
            patch.setattr(db, "_connect", forbidden)
            result = RulePublisher(authorizer=lambda *_: None).rollback_in_transaction(conn,
                CandidateRollback(**rollback_body(request, published)))
            assert result.pointerVersion == 2 and conn.in_transaction
        conn.rollback()
    finally:
        conn.close()
    assert snapshot() == before


def test_rollback_cannot_use_an_approval_operation_key_for_a_different_verb(rule_storage):
    owner, _, cid, request = approved(rule_storage)
    original_key = meta("candidate_review:" + cid)[0]["approvalOperationKey"]
    result = owner.publish(cid, request)
    before = snapshot()
    with pytest.raises(CandidateReviewError) as error:
        owner.rollback(rollback_body(request, result, operationKey=original_key))
    assert error.value.code == "candidate_operation_conflict" and snapshot() == before


def test_approval_cannot_reuse_a_prior_rollback_operation_key(rule_storage):
    owner, _, cid, request = approved(rule_storage)
    published = owner.publish(cid, request)
    rollback = rollback_body(request, published)
    owner.rollback(rollback)
    next_owner, _, next_cid = proposal(rule_storage)
    intent = approve_intent(next_owner.detail(next_cid), operationKey=rollback["operationKey"])
    before = snapshot()
    with pytest.raises(CandidateReviewError) as error:
        next_owner.approve(next_cid, intent)
    assert error.value.code == "candidate_operation_conflict" and snapshot() == before


def test_fresh_rollback_to_the_already_active_version_is_not_a_pointer_transition(rule_storage):
    owner, _, cid, request = approved(rule_storage)
    published = owner.publish(cid, request)
    before = snapshot()
    with pytest.raises(CandidateReviewError) as error:
        owner.rollback(rollback_body(request, published, targetRuleVersion=published.publishedRuleVersion))
    assert error.value.status == 422 and snapshot() == before


@pytest.mark.parametrize("boundary", ["marker", "pointer", "operation", "audit", "commit"])
def test_store_rollback_and_source_blocking_faults_leave_all_history_and_pointer_unchanged(rule_storage, monkeypatch, boundary):
    owner, _, cid, request = approved(rule_storage)
    published = owner.publish(cid, request)
    before = snapshot(); connect = sqlite3.connect; injected = []
    class Fault(sqlite3.Connection):
        def execute(self, sql, parameters=()):
            if ((boundary == "marker" and sql.startswith("INSERT INTO runtime_meta") and parameters[0].startswith("rule_suspension:"))
                or (boundary == "pointer" and sql.startswith("UPDATE runtime_meta") and "active_baseline" in sql)
                or (boundary == "operation" and sql.startswith("INSERT INTO runtime_meta") and parameters[0].startswith("rule_operation:"))
                or (boundary == "audit" and sql.startswith("INSERT INTO audit_events") and "rule_rolled_back" in parameters)):
                injected.append(boundary)
                raise sqlite3.OperationalError("Synthetic rollback write failure")
            return super().execute(sql, parameters)
        def commit(self):
            if boundary == "commit":
                injected.append(boundary)
                raise sqlite3.OperationalError("Synthetic rollback precommit failure")
            return super().commit()
    with monkeypatch.context() as patch:
        patch.setattr(sqlite3, "connect", lambda *a, **kw: connect(*a, **kw, factory=Fault))
        with pytest.raises(CandidateReviewError) as error:
            owner.rollback(rollback_body(request, published, blockRuleVersion=published.publishedRuleVersion))
        assert error.value.status == 503
    assert injected == [boundary] and snapshot() == before
