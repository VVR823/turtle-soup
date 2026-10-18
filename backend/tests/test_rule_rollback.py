"""Rollback switches only a pointer and can atomically fence the bad old release."""
import sqlite3
from concurrent.futures import ThreadPoolExecutor
from threading import Barrier
from uuid import uuid4

import pytest

from app import db
from app.runtime import runtime_context
from .test_feedback_storage import snapshot
from .test_rule_publication import prepare, publisher
from .test_rule_snapshots import rule_storage, release_rows
from .test_rule_suspension import stopped


def prepared():
    request = prepare(); owned = publisher(request); result = owned.publish(request)
    options = dict(target_rule_version=request.expectedRuleVersion, expected_rule_version=result.ruleVersion,
        expected_pointer_version=result.pointerVersion, operation_key=str(uuid4()), reason="Synthetic rollback")
    return request, owned, result, options


def test_rollback_preserves_versions_sessions_and_replays_same_operation(rule_storage):
    request, owned, result, options = prepared()
    new_version_game = db.create_game_once("synthetic", None, str(uuid4()))["sessionId"]
    before_releases = release_rows()
    reverted = owned.rollback(**options); before = snapshot()
    assert reverted.ruleVersion == request.expectedRuleVersion and reverted.pointerVersion == 2
    assert owned.rollback(**options) == reverted and snapshot() == before
    old_version_game = db.create_game_once("synthetic", None, str(uuid4()))["sessionId"]
    assert db.get_session(new_version_game)["ruleVersion"] == result.ruleVersion
    assert db.get_session(old_version_game)["ruleVersion"] == request.expectedRuleVersion
    assert release_rows() == before_releases


def test_rollback_can_block_source_and_keep_active_target_available(rule_storage):
    request, owned, result, options = prepared()
    bad_game = db.create_game_once("synthetic", None, str(uuid4()))["sessionId"]
    owned.rollback(**options, block_rule_version=result.ruleVersion)
    assert db.get_session(bad_game)["ruleSuspended"]
    with pytest.raises(db.GameConflict, match="rule_version_suspended"):
        db.reserve_turn(bad_game, str(uuid4()), "小明是凶手吗？")
    current = db.create_game_once("synthetic", None, str(uuid4()))["sessionId"]
    assert db.get_session(current)["ruleVersion"] == request.expectedRuleVersion
    assert not db.get_session(current)["ruleSuspended"]


def test_rollback_refuses_suspended_target_and_unrelated_block(rule_storage):
    from app.rule_publication import RulePublicationError
    request, owned, result, options = prepared()
    before = snapshot()
    with pytest.raises(RulePublicationError):
        owned.rollback(**options, block_rule_version=request.expectedRuleVersion)
    assert snapshot() == before
    stopped(request); before = snapshot()
    with pytest.raises(RulePublicationError, match="rule_version_suspended"):
        owned.rollback(**options)
    assert snapshot() == before


def test_same_rollback_key_changed_reason_is_not_a_second_operation(rule_storage):
    from app.rule_publication import RulePublicationError
    _, owned, _, options = prepared(); owned.rollback(**options); before = snapshot()
    with pytest.raises(RulePublicationError, match="rule_operation_conflict"):
        owned.rollback(**{**options, "reason": "Different reason"})
    assert snapshot() == before


def test_two_rollback_requests_only_one_pointer_cas_wins(rule_storage):
    from app.rule_publication import RulePublicationError
    _, owned, _, options = prepared(); gate = Barrier(2)
    def run(key):
        with runtime_context(rule_storage):
            gate.wait(timeout=5)
            try: return owned.rollback(**{**options, "operation_key": key})
            except RulePublicationError as error: return error.code
    with ThreadPoolExecutor(max_workers=2) as pool:
        results = list(pool.map(run, (str(uuid4()), str(uuid4()))))
    assert sum(not isinstance(result, str) for result in results) == 1
    assert results.count("rule_pointer_conflict") == 1


@pytest.mark.parametrize("boundary", ["pointer", "marker", "operation", "audit", "commit"])
def test_rollback_and_optional_stop_are_one_atomic_transaction(rule_storage, monkeypatch, boundary):
    from app.rule_publication import RulePublicationError
    _, owned, result, options = prepared(); before = snapshot(); connect = db._connect
    class Fault:
        def __init__(self): self.inner = connect()
        def __getattr__(self, name): return getattr(self.inner, name)
        def execute(self, sql, params=()):
            if ((boundary == "pointer" and sql.startswith("UPDATE runtime_meta") and "active_baseline" in sql)
                or (boundary == "marker" and sql.startswith("INSERT INTO runtime_meta") and params[0].startswith("rule_suspension:"))
                or (boundary == "operation" and sql.startswith("INSERT INTO runtime_meta") and params[0].startswith("rule_operation:"))
                or (boundary == "audit" and sql.startswith("INSERT INTO audit_events"))):
                raise sqlite3.OperationalError("PRIVATE rollback failure")
            return self.inner.execute(sql, params)
        def commit(self):
            if boundary == "commit": raise sqlite3.OperationalError("PRIVATE commit")
            return self.inner.commit()
    with monkeypatch.context() as patch:
        patch.setattr(db, "_connect", lambda **_kw: Fault())
        with pytest.raises(RulePublicationError): owned.rollback(**options, block_rule_version=result.ruleVersion)
    assert snapshot() == before
