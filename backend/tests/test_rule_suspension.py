"""Explicit version suspension fences real reserved work without deleting history."""
import sqlite3
from concurrent.futures import ThreadPoolExecutor
from threading import Event
from uuid import uuid4

import pytest

from app import db
from app.game_service import ask, evaluate_snapshot
from app.runtime import runtime_context
from app.schemas import ChatRequest, HostResult, HostVersions
from app.testing import FakeModel
from .test_feedback_storage import snapshot
from .test_rule_publication import prepare, publisher
from .test_rule_snapshots import rule_storage


def stopped(request, owned=None, **changes):
    owned = owned or publisher(request)
    kwargs = dict(expected_marker_version=None, suspended=True, reason="Synthetic stop", operation_key=str(uuid4()))
    kwargs.update(changes)
    owned.set_rule_suspension(request.expectedRuleVersion, **kwargs)
    return kwargs


def test_suspension_blocks_new_reservation_and_evaluation_but_history_remains(rule_storage):
    request = prepare(); session_id = db.create_game_once("synthetic", None, str(uuid4()))["sessionId"]
    stopped(request); before = snapshot()
    with pytest.raises(db.GameConflict, match="rule_version_suspended"):
        db.reserve_turn(session_id, str(uuid4()), "小明是凶手吗？")
    with pytest.raises(db.GameConflict, match="rule_version_suspended"):
        db.evaluate_once(session_id, evaluate_snapshot)
    assert db.get_session(session_id)["ruleSuspended"] is True
    assert snapshot() == before and rule_storage.model.calls == []


def test_late_owned_answer_refused_without_count_or_message_write(rule_storage):
    request = prepare(); session_id = db.create_game_once("synthetic", None, str(uuid4()))["sessionId"]
    owner = db.reserve_turn(session_id, str(uuid4()), "小明是凶手吗？", now=100)
    publisher(request).publish(request)
    stopped(request); before = snapshot()
    result = HostResult(kind="answer", answer="是", reply="是", chargeable=True, source="llm",
        versions=HostVersions(puzzleVersion=owner.puzzleVersion, ruleVersion=owner.ruleVersion))
    with pytest.raises(db.GameConflict, match="rule_version_suspended"):
        db.finish_turn(owner, result, now=101)
    assert snapshot() == before
    assert db.get_session(session_id)["questionsAsked"] == 0 and db.get_session(session_id)["messages"] == []
    assert db.get_turn_response(session_id, owner.requestId, now=102).state == "reserved"
    assert db.expire_reserved_turns(session_id, now=191) == 1
    assert db.get_turn_response(session_id, owner.requestId, now=192).state == "expired"


def test_actual_blocked_fake_model_cannot_commit_after_suspension(rule_storage):
    entered, release = Event(), Event()
    class BlockedModel(FakeModel):
        def _respond(self, messages):
            entered.set()
            assert release.wait(timeout=10)
            return super()._respond(messages)
    rule_storage.model = BlockedModel("是")
    request = prepare(); session_id = db.create_game_once("synthetic", None, str(uuid4()))["sessionId"]
    def run():
        with runtime_context(rule_storage):
            try:
                return ask(ChatRequest(sessionId=session_id, soupId="synthetic", question="小红是凶手吗？"))
            except db.GameConflict as error:
                return error.code
    with ThreadPoolExecutor(max_workers=1) as pool:
        future = pool.submit(run)
        try:
            assert entered.wait(timeout=5)
            stopped(request)
        finally:
            release.set()
        assert future.result(timeout=10) == "rule_version_suspended"
    current = db.get_session(session_id)
    assert current["questionsAsked"] == 0 and current["messages"] == [] and len(rule_storage.model.calls) == 1


def test_marker_cas_replay_and_explicit_unsuspend(rule_storage):
    from app.rule_publication import RulePublicationError
    request = prepare(); owned = publisher(request); kwargs = stopped(request, owned)
    before = snapshot()
    owned.set_rule_suspension(request.expectedRuleVersion, **kwargs)
    assert snapshot() == before
    with pytest.raises(RulePublicationError, match="rule_suspension_conflict"):
        stopped(request, owned)
    with pytest.raises(RulePublicationError, match="rule_operation_conflict"):
        owned.set_rule_suspension(request.expectedRuleVersion, **{**kwargs, "reason": "Different"})
    owned.set_rule_suspension(request.expectedRuleVersion, expected_marker_version=0,
        suspended=False, reason="Explicit reopen", operation_key=str(uuid4()))
    session_id = db.create_game_once("synthetic", None, str(uuid4()))["sessionId"]
    assert not db.get_session(session_id)["ruleSuspended"]
    assert db.reserve_turn(session_id, str(uuid4()), "小明是凶手吗？")


def test_saved_ended_evaluation_remains_readable_when_version_stopped(rule_storage):
    request = prepare(); session_id = db.create_game_once("synthetic", None, str(uuid4()))["sessionId"]
    ended = db.evaluate_once(session_id, evaluate_snapshot)
    stopped(request)
    assert db.evaluate_once(session_id, evaluate_snapshot) == ended
    restored = db.get_session(session_id)
    assert restored["evaluation"] == ended and restored["ruleSuspended"]


@pytest.mark.parametrize("boundary", ["marker", "operation", "audit", "commit"])
def test_suspension_failure_rolls_back_marker_and_audit(rule_storage, monkeypatch, boundary):
    from app.rule_publication import RulePublicationError
    request = prepare(); before = snapshot(); connect = db._connect
    class Fault:
        def __init__(self): self.inner = connect()
        def __getattr__(self, name): return getattr(self.inner, name)
        def execute(self, sql, params=()):
            if ((boundary == "marker" and sql.startswith("INSERT INTO runtime_meta") and params[0].startswith("rule_suspension:"))
                or (boundary == "operation" and sql.startswith("INSERT INTO runtime_meta") and params[0].startswith("rule_operation:"))
                or (boundary == "audit" and sql.startswith("INSERT INTO audit_events"))):
                raise sqlite3.OperationalError("PRIVATE stop failure")
            return self.inner.execute(sql, params)
        def commit(self):
            if boundary == "commit": raise sqlite3.OperationalError("PRIVATE commit")
            return self.inner.commit()
    with monkeypatch.context() as patch:
        patch.setattr(db, "_connect", lambda **_kw: Fault())
        with pytest.raises(RulePublicationError): stopped(request)
    assert snapshot() == before


def test_suspended_active_rule_cannot_create_a_new_game(rule_storage):
    request = prepare(); stopped(request); before = snapshot()
    with pytest.raises(db.GameConflict, match="rule_version_suspended"):
        db.create_game_once("synthetic", None, str(uuid4()))
    assert snapshot() == before


def test_retired_embedded_creation_cannot_bypass_stopped_active_version(rule_storage):
    request = prepare(); stopped(request); before = snapshot()
    with pytest.raises(db.GameConflict, match="rule_version_suspended"):
        db.create_session("synthetic")
    assert snapshot() == before
