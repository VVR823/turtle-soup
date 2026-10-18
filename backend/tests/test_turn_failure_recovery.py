"""Fenced paired writes, actual rollback faults and fake-clock recovery."""
from contextlib import closing
from dataclasses import replace
from concurrent.futures import ThreadPoolExecutor
import sqlite3
from threading import Barrier, Event
from uuid import uuid4

import pytest

from app import db
from app.host_context import build_context
from app.runtime import runtime_context
from app.schemas import HostResult, HostVersions
from .test_game_transactions import rows, start, store


def reserve(session_id, *, now=100):
    return db.reserve_turn(session_id, str(uuid4()), "One synthetic question?", now=now)


def result(owner, kind="answer"):
    versions = HostVersions(puzzleVersion=owner.puzzleVersion, ruleVersion=owner.ruleVersion,
                            engineVersion=owner.engineVersion)
    if kind == "answer":
        return HostResult(kind=kind, answer="是", chargeable=True, source="deterministic", reply="是", versions=versions)
    if kind == "win":
        return HostResult(kind=kind, chargeable=True, source="deterministic", reply="Synthetic win", versions=versions)
    if kind == "reminder":
        return HostResult(kind=kind, chargeable=False, source="flow", reply="Synthetic reminder", versions=versions)
    return HostResult(kind="system_error", chargeable=False, source="llm", reply="Synthetic safe failure",
                      errorCode="model_output_invalid", versions=versions)


def dump():
    with closing(db._connect()) as conn, conn:
        return tuple(conn.iterdump())


def test_answer_commits_one_linked_pair_one_charge_and_exact_saved_response(store):
    session_id = start()["sessionId"]
    owner = reserve(session_id)
    replay = db.finish_turn(owner, result(owner), now=101)
    assert replay.state == "completed" and replay.httpStatus == 200
    assert replay.safeResponse["remaining"] == 1
    assert replay.safeResponse["turnId"] == owner.turnId
    assert [(m["role"], m["content"], m["turn_id"]) for m in rows("messages")] == [
        ("user", "One synthetic question?", owner.turnId), ("host", "是", owner.turnId)]
    assert rows("sessions")[0]["questions_asked"] == 1
    assert db.get_turn_response(session_id, owner.requestId, now=102) == replay
    assert db.finish_turn(owner, result(owner), now=103) == replay
    assert len(rows("messages")) == 2


def test_last_question_and_new_request_ids_cannot_overcharge(store):
    session_id = start()["sessionId"]
    for index in range(2):
        owner = reserve(session_id, now=100 + index * 2)
        db.finish_turn(owner, result(owner), now=101 + index * 2)
    last = db.reserve_turn(session_id, str(uuid4()), "One synthetic question?", now=110)
    assert last.safeResponse["limitReached"] is True
    assert rows("sessions")[0]["questions_asked"] == 2
    assert len(rows("messages")) == 4
    assert len({m["turn_id"] for m in rows("messages")}) == 2


def test_two_synchronized_callers_compete_for_last_question_and_only_one_charges(store):
    session_id = start()["sessionId"]
    first = reserve(session_id)
    db.finish_turn(first, result(first), now=101)
    gate, rejected, release = Barrier(2), Event(), Event()

    def ask():
        with runtime_context(store):
            gate.wait(timeout=2)
            try:
                owner = reserve(session_id, now=102)
            except db.GameConflict as error:
                rejected.set()
                return error.code
            assert release.wait(timeout=2)
            return db.finish_turn(owner, result(owner), now=103).safeResponse["remaining"]

    with ThreadPoolExecutor(max_workers=2) as pool:
        calls = [pool.submit(ask) for _ in range(2)]
        try:
            assert rejected.wait(timeout=1)
            assert rows("sessions")[0]["questions_asked"] == 1
        finally:
            release.set()
        assert {call.result(timeout=1) for call in calls} == {0, "turn_in_progress"}
    assert rows("sessions")[0]["questions_asked"] == 2
    assert len(rows("messages")) == 4


@pytest.mark.parametrize("kind,status,count,code", [
    ("reminder", "completed", 0, 200), ("system_error", "failed", 0, 503), ("win", "completed", 1, 200),
])
def test_explicit_result_kind_controls_charge_state_and_failure_replay(store, kind, status, count, code):
    session_id = start()["sessionId"]
    owner = reserve(session_id)
    response = db.finish_turn(owner, result(owner, kind), now=101)
    assert response.state == status and response.httpStatus == code
    assert rows("sessions")[0]["questions_asked"] == count
    assert rows("turns")[0]["charged"] == count
    assert len(rows("messages")) == 2
    assert all(m["is_free_reminder"] == (0 if count else 1) for m in rows("messages"))
    assert db.reserve_turn(session_id, owner.requestId, owner.question, now=102) == response
    if kind == "win":
        assert rows("sessions")[0]["status"] == "solved"
        assert rows("sessions")[0]["solved_at"] == 101
    else:
        assert rows("sessions")[0]["status"] == "playing"
    if kind == "system_error":
        context = build_context(system_prompt="System", facts_prompt="Facts", question="Next question?",
                                history=db.get_session(session_id)["messages"])
        assert context.turns_included == 0
        assert response.safeResponse["code"] == "model_output_invalid"


@pytest.mark.parametrize("mutation", ["token", "row_version", "question", "puzzle", "engine", "status"])
def test_stale_or_changed_owner_cannot_write_pair_count_or_win(store, mutation):
    session_id = start()["sessionId"]
    owner = reserve(session_id)
    if mutation == "token":
        owner = replace(owner, leaseToken="not-the-owner")
    elif mutation == "question":
        owner = replace(owner, question="Changed question?")
    elif mutation == "puzzle":
        owner = replace(owner, puzzleVersion="changed-version")
    elif mutation == "engine":
        owner = replace(owner, engineVersion="changed-engine")
    else:
        with closing(db._connect()) as conn, conn:
            column = "row_version=row_version+1" if mutation == "row_version" else "status='given_up'"
            conn.execute(f"UPDATE sessions SET {column} WHERE id=?", (session_id,))
    before = dump()
    with pytest.raises(db.GameConflict, match="turn_owner_stale"):
        db.finish_turn(owner, result(owner, "win"), now=101)
    assert dump() == before


def test_result_versions_must_match_program_owned_reservation(store):
    session_id = start()["sessionId"]
    owner = reserve(session_id)
    wrong = result(owner).model_copy(update={"versions": HostVersions()})
    before = dump()
    with pytest.raises(db.GameConflict, match="result_version_conflict"):
        db.finish_turn(owner, wrong, now=101)
    assert dump() == before


def test_cancellation_seen_at_commit_gate_is_persisted_without_charging(store):
    session_id = start()["sessionId"]
    owner = reserve(session_id)
    cancelled = Event()
    cancelled.set()
    response = db.finish_turn(owner, result(owner, "win"), now=101, cancelled=cancelled)
    assert response.state == "failed"
    assert response.safeResponse["code"] == "model_cancelled"
    assert rows("sessions")[0]["questions_asked"] == 0
    assert rows("sessions")[0]["status"] == "playing"


def test_expiry_reclaims_once_and_late_win_cannot_overwrite_new_turn(store):
    session_id = start()["sessionId"]
    old = reserve(session_id)
    assert db.expire_reserved_turns(session_id, now=189.99) == 0
    assert db.expire_reserved_turns(session_id, now=190) == 1
    assert db.expire_reserved_turns(session_id, now=190) == 0
    old_response = db.get_turn_response(session_id, old.requestId, now=191)
    assert old_response.state == "expired" and old_response.httpStatus == 503
    assert old_response.safeResponse["state"] == "expired"
    assert old_response.safeResponse["code"] == "turn_expired"
    new = reserve(session_id, now=191)
    before = dump()
    with pytest.raises(db.GameConflict, match="turn_owner_stale"):
        db.finish_turn(old, result(old, "win"), now=192)
    assert dump() == before
    db.finish_turn(new, result(new), now=192)
    assert rows("sessions")[0]["status"] == "playing"
    assert rows("sessions")[0]["questions_asked"] == 1
    assert len(rows("messages")) == 2


def test_query_and_same_request_recover_expired_owner_without_reissuing_it(store):
    session_id = start()["sessionId"]
    old = reserve(session_id)
    first = db.get_turn_response(session_id, old.requestId, now=190)
    assert first.state == "expired"
    assert db.reserve_turn(session_id, old.requestId, old.question, now=191) == first
    assert rows("sessions")[0]["questions_asked"] == 0
    assert rows("messages") == []
    assert len(rows("turns")) == 1


def test_expired_finish_persists_recovery_before_returning_stale_owner_error(store):
    session_id = start()["sessionId"]
    owner = reserve(session_id)
    with pytest.raises(db.GameConflict, match="turn_owner_stale"):
        db.finish_turn(owner, result(owner, "win"), now=190)
    assert rows("turns")[0]["state"] == "expired"
    assert rows("sessions")[0]["questions_asked"] == 0
    assert rows("sessions")[0]["status"] == "playing"
    assert rows("messages") == []


@pytest.mark.parametrize("failure_point", ["user", "host", "session", "turn", "commit"])
def test_fault_at_each_write_boundary_rolls_back_entire_pair_and_response(store, monkeypatch, failure_point):
    session_id = start()["sessionId"]
    owner = reserve(session_id)
    before = dump()
    connect = db._connect

    class FaultConnection:
        def __init__(self):
            self.inner = connect()

        @property
        def in_transaction(self):
            return self.inner.in_transaction

        def execute(self, sql, args=()):
            cursor = self.inner.execute(sql, args)
            words = sql.strip().upper()
            triggered = ((failure_point in {"user", "host"} and words.startswith("INSERT INTO MESSAGES")
                          and args[1] == failure_point)
                         or (failure_point == "session" and words.startswith("UPDATE SESSIONS"))
                         or (failure_point == "turn" and words.startswith("UPDATE TURNS")))
            if triggered:
                raise sqlite3.OperationalError("synthetic write fault")
            return cursor

        def commit(self):
            if failure_point == "commit":
                raise sqlite3.OperationalError("synthetic commit fault")
            self.inner.commit()

        def rollback(self):
            self.inner.rollback()

        def close(self):
            self.inner.close()

    with monkeypatch.context() as patch:
        patch.setattr(db, "_connect", FaultConnection)
        with pytest.raises(sqlite3.OperationalError):
            db.finish_turn(owner, result(owner, "win"), now=101)
    assert dump() == before
    assert db.finish_turn(owner, result(owner), now=102).safeResponse["remaining"] == 1


def test_legacy_single_message_and_status_writers_cannot_bypass_managed_turns(store):
    session_id = start()["sessionId"]
    owner = reserve(session_id)
    before = dump()
    with pytest.raises(db.GameConflict, match="atomic_writer_required"):
        db.save_message(session_id, "user", "Bypass?")
    with pytest.raises(db.GameConflict, match="atomic_writer_required"):
        db.update_session_status(session_id, "solved")
    assert dump() == before
    db.finish_turn(owner, result(owner), now=101)
