"""Actual SQLite request transactions; all puzzles/sessions are synthetic."""
from contextlib import closing
from concurrent.futures import ThreadPoolExecutor
from dataclasses import FrozenInstanceError
from threading import Barrier
from uuid import uuid4

import pytest

from app import db
from app.runtime import runtime_context
from app.schemas import DifficultyLimits, Soup


@pytest.fixture
def store(runtime):
    runtime.soups = [Soup(id="synthetic", title="Frozen title", surface="Frozen surface",
                          bottom="Synthetic private truth", difficultyLimits=DifficultyLimits(
                              xuermu=2, baozi=3, tianyi=4))]
    db.initialize()
    return runtime


def start(level="xuermu", request_id=None):
    return db.create_game_once("synthetic", level, request_id or str(uuid4()))


def rows(table):
    # Table names are test-owned literals, never request/model input.
    with closing(db._connect()) as conn, conn:
        return [dict(row) for row in conn.execute(f"SELECT * FROM {table} ORDER BY rowid")]


def test_concurrent_duplicate_creation_commits_one_game_and_one_saved_response(store):
    gate, request_id = Barrier(4), str(uuid4())

    def create():
        with runtime_context(store):
            gate.wait(timeout=2)
            return start(request_id=request_id)

    with ThreadPoolExecutor(max_workers=4) as pool:
        responses = list(pool.map(lambda _: create(), range(4)))
    assert all(response == responses[0] for response in responses)
    assert len(rows("sessions")) == len(rows("creation_requests")) == 1
    assert responses[0]["requestId"] == request_id
    assert responses[0]["soupTitle"] == "Frozen title"
    assert "Synthetic private truth" not in str(responses)


@pytest.mark.parametrize("changed", [("synthetic", "tianyi"), ("other", "xuermu")])
def test_same_creation_id_with_changed_payload_conflicts_without_another_game(store, changed):
    request_id = str(uuid4())
    original = start(request_id=request_id)
    with pytest.raises(db.GameConflict, match="creation_payload_conflict"):
        db.create_game_once(*changed, request_id)
    assert start(request_id=request_id) == original
    assert len(rows("sessions")) == 1


@pytest.mark.parametrize("level,limit", [(None, 2), ("unknown", 2), ("xuermu", 2), ("baozi", 3), ("tianyi", 4)])
def test_creation_uses_frozen_difficulty_and_preserves_strictest_fallback(store, level, limit):
    store.soups[0].title = "Changed memory, not the active snapshot"
    store.soups[0].difficultyLimits.xuermu = 900
    result = start(level=level)
    assert result["questionLimit"] == limit
    assert result["soupTitle"] == "Frozen title"
    session = rows("sessions")[0]
    assert session["traffic_class"] == "test"
    assert session["puzzle_version"].startswith("p1:")
    assert session["rule_version"].startswith("r1:")


def test_distinct_creation_ids_create_distinct_intentional_games(store):
    assert start()["sessionId"] != start()["sessionId"]
    assert len(rows("sessions")) == len(rows("creation_requests")) == 2


def test_creation_with_same_fallback_but_changed_raw_payload_is_still_a_conflict(store):
    request_id = str(uuid4())
    start(level=None, request_id=request_id)
    with pytest.raises(db.GameConflict, match="creation_payload_conflict"):
        start(level="unknown", request_id=request_id)


def test_reservation_is_frozen_pins_versions_and_releases_write_lock(store):
    session_id = start()["sessionId"]
    reservation = db.reserve_turn(session_id, str(uuid4()), "Synthetic question?", now=100)
    assert reservation.sessionId == session_id
    assert reservation.question == "Synthetic question?"
    assert reservation.expectedRowVersion == 1
    assert reservation.puzzleVersion == rows("sessions")[0]["puzzle_version"]
    assert reservation.ruleVersion == rows("sessions")[0]["rule_version"]
    assert rows("turns")[0]["lease_expires_at"] == 190
    with pytest.raises(FrozenInstanceError):
        reservation.leaseToken = "changed"
    with closing(db._connect()) as independent, independent:
        independent.execute("BEGIN IMMEDIATE")
        independent.rollback()
    assert rows("sessions")[0]["questions_asked"] == 0
    assert rows("messages") == []


def test_same_turn_id_returns_in_progress_and_changed_question_is_rejected(store):
    session_id, request_id = start()["sessionId"], str(uuid4())
    reservation = db.reserve_turn(session_id, request_id, "One question?", now=100)
    replay = db.reserve_turn(session_id, request_id, "One question?", now=101)
    assert replay.state == "reserved"
    assert replay.httpStatus == 202
    assert replay.safeResponse["turnId"] == reservation.turnId
    assert replay.safeResponse["requestId"] == request_id
    with pytest.raises(db.GameConflict, match="turn_payload_conflict"):
        db.reserve_turn(session_id, request_id, "Different question?", now=102)
    assert len(rows("turns")) == 1


def test_concurrent_different_ids_reserve_at_most_one_turn(store):
    session_id, gate = start()["sessionId"], Barrier(2)

    def reserve():
        with runtime_context(store):
            gate.wait(timeout=2)
            try:
                db.reserve_turn(session_id, str(uuid4()), "Synthetic question?", now=100)
                return "reserved"
            except db.GameConflict as error:
                return error.code

    with ThreadPoolExecutor(max_workers=2) as pool:
        assert sorted(pool.map(lambda _: reserve(), range(2))) == ["reserved", "turn_in_progress"]
    assert len(rows("turns")) == 1


def test_redundant_soup_id_must_match_bound_puzzle(store):
    session_id = start()["sessionId"]
    with pytest.raises(db.GameConflict, match="session_soup_conflict"):
        db.reserve_turn(session_id, str(uuid4()), "Synthetic question?", soup_id="other", now=100)
    assert rows("turns") == []
    db.reserve_turn(session_id, str(uuid4()), "Synthetic question?", soup_id="synthetic", now=100)
    assert len(rows("turns")) == 1


def test_unknown_session_is_a_distinct_not_found_error(store):
    with pytest.raises(db.GameNotFound):
        db.reserve_turn("unknown", str(uuid4()), "Synthetic question?", now=100)
    assert rows("turns") == []


@pytest.mark.parametrize("status", ["solved", "given_up", "expired"])
def test_terminal_session_cannot_reserve_a_new_turn(store, status):
    session_id = start()["sessionId"]
    with closing(db._connect()) as conn, conn:
        conn.execute("UPDATE sessions SET status=? WHERE id=?", (status, session_id))
    with pytest.raises(db.GameConflict, match="game_ended"):
        db.reserve_turn(session_id, str(uuid4()), "Synthetic question?", now=100)
    assert rows("turns") == []


def test_incompatible_session_keeps_distinct_legacy_guard(store):
    session_id = start()["sessionId"]
    with closing(db._connect()) as conn, conn:
        conn.execute("UPDATE sessions SET compat_state='legacy' WHERE id=?", (session_id,))
    with pytest.raises(db.SessionCompatibilityError):
        db.reserve_turn(session_id, str(uuid4()), "Synthetic question?", now=100)
    assert rows("turns") == []


def test_limit_reached_is_persisted_as_free_reminder_without_new_model_work(store):
    session_id, request_id = start()["sessionId"], str(uuid4())
    with closing(db._connect()) as conn, conn:
        conn.execute("UPDATE sessions SET questions_asked=question_limit WHERE id=?", (session_id,))
    replay = db.reserve_turn(session_id, request_id, "Synthetic question?", now=100)
    assert replay.state == "completed" and replay.httpStatus == 200
    assert replay.safeResponse["limitReached"] is True
    assert replay.safeResponse["remaining"] == 0
    assert replay.safeResponse["isFreeReminder"] is True
    assert rows("turns")[0]["charged"] == 0
    assert rows("turns")[0]["kind"] == "reminder"
    assert rows("messages") == []
    assert db.reserve_turn(session_id, request_id, "Synthetic question?", now=101) == replay


def test_unlimited_puzzle_is_not_given_a_synthetic_question_cap(store):
    # Make a separate fresh isolated catalog, not a mutation of a frozen version.
    from app.config import Settings
    from app.runtime import Runtime
    active = Runtime(Settings.for_test(store.settings.DATA_DIR / "unlimited"), model=store.model,
                     soups=[Soup(id="synthetic", title="Unlimited", surface="Surface",
                                 bottom="Synthetic truth", unlimited=True)])
    with runtime_context(active):
        assert start()["questionLimit"] is None
