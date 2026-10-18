"""Legacy history preservation and explicit application-startup contracts."""
import json
import sqlite3

import pytest
from fastapi.testclient import TestClient

from app import db, migrations
from app.config import Settings
from app.main import create_app
from app.testing import FakeModel
from .test_migrations import old_database, puzzle


def test_normal_old_playing_game_restores_and_continues(tmp_path):
    from app import migrations
    conn = old_database(tmp_path / "sessions.db")
    report = migrations.migrate(conn, [puzzle()], target_version=2)  # Application fixture now requires registered M2.
    assert report["compatibleSessions"] == 1
    assert conn.execute("SELECT compat_state FROM sessions").fetchone()[0] == "compatible"
    assert conn.execute("SELECT count(*) FROM turns").fetchone()[0] == 1
    assert conn.execute("SELECT count(DISTINCT turn_id) FROM messages").fetchone()[0] == 1
    conn.close()
    app = create_app(Settings.for_test(tmp_path), model=FakeModel(), soups=[puzzle()])
    with TestClient(app) as client:
        restored = client.get("/api/session/old")
        assert restored.status_code == 200
        assert restored.json()["questionsAsked"] == 1
        assert [m["content"] for m in restored.json()["messages"]] == ["Question?", "是"]
        reply = client.post("/api/chat", json={"sessionId": "old", "question": "这是本格吗？"})
        assert reply.status_code == 200
        assert client.get("/api/session/old").json()["questionsAsked"] == 2


@pytest.mark.parametrize("mutation,code", [
    ("missing_puzzle", "missing_puzzle"), ("unpaired", "unpaired_messages"),
    ("reminder_mismatch", "reminder_mismatch"), ("count_mismatch", "count_mismatch"),
    ("terminal_conflict", "terminal_conflict"), ("negative_count", "invalid_session"),
])
def test_bad_legacy_game_has_report_no_fabricated_turn_and_410(tmp_path, mutation, code):
    from app import migrations
    conn = old_database(tmp_path / "sessions.db")
    if mutation == "missing_puzzle":
        conn.execute("UPDATE sessions SET soup_id='removed'")
    elif mutation == "unpaired":
        conn.execute("DELETE FROM messages WHERE role='host'")
    elif mutation == "reminder_mismatch":
        conn.execute("UPDATE messages SET is_free_reminder=1 WHERE role='host'")
    elif mutation == "count_mismatch":
        conn.execute("UPDATE sessions SET questions_asked=9")
    elif mutation == "terminal_conflict":
        conn.execute("UPDATE sessions SET solved_at=100")
    else:
        conn.execute("UPDATE sessions SET questions_asked=-1")
    conn.commit()
    before = [tuple(row) for row in conn.execute("SELECT id,role,content,timestamp FROM messages ORDER BY id")]
    report = migrations.migrate(conn, [puzzle()], target_version=2)  # Keep legacy preservation assertions unchanged.
    assert any(issue["code"] == code for issue in report["issues"])
    assert "Question?" not in json.dumps(report)
    assert conn.execute("SELECT count(*) FROM turns").fetchone()[0] == 0
    assert [tuple(row) for row in conn.execute("SELECT id,role,content,timestamp FROM messages ORDER BY id")] == before
    conn.close()
    with TestClient(create_app(Settings.for_test(tmp_path), model=FakeModel(), soups=[puzzle()])) as client:
        for response in (
            client.get("/api/session/old"),
            client.post("/api/chat", json={"sessionId": "old", "question": "继续吗？"}),
            client.post("/api/evaluate", json={"sessionId": "old"}),
        ):
            assert response.status_code == 410
            assert response.json()["code"] == "legacy_session_incompatible"


def test_legacy_startup_refuses_without_changing_database(tmp_path):
    from app import migrations
    conn = old_database(tmp_path / "sessions.db")
    conn.close()
    before = (tmp_path / "sessions.db").read_bytes()
    with pytest.raises(migrations.MigrationRequired):
        with TestClient(create_app(Settings.for_test(tmp_path), model=FakeModel(), soups=[puzzle()])):
            pass
    assert (tmp_path / "sessions.db").read_bytes() == before
    assert not (tmp_path / "sessions.db-wal").exists()


def test_new_session_is_bound_to_snapshot_and_test_traffic(runtime):
    session = db.create_session("xin", 20)
    stored = db.get_session(session["id"])
    assert stored["compatState"] == "compatible"
    assert stored["puzzleVersion"].startswith("p1:")
    assert stored["ruleVersion"].startswith("r1:")
    conn = sqlite3.connect(runtime.settings.DATA_DIR / "sessions.db")
    assert conn.execute("SELECT traffic_class FROM sessions").fetchone()[0] == "test"
    conn.close()


@pytest.mark.parametrize("filename,contents", [
    ("generated_soups.json", "not json"), ("generated_soups.json", '[{"id":"broken"}]'),
    ("verified_qa_pairs.jsonl", "not json\n"),
    ("verified_qa_pairs.jsonl", '{"soupId":"missing","confusionPoint":{"q":"?","a":"是"}}\n'),
])
def test_configured_bad_catalog_or_rules_fail_startup(tmp_path, filename, contents):
    (tmp_path / filename).write_text(contents, encoding="utf-8")
    before = (tmp_path / filename).read_bytes()
    # Runtime no longer parses legacy verified rules: their mere presence
    # requires explicit rehearsal before opening a fresh database.
    expected = migrations.MigrationRequired if filename == "verified_qa_pairs.jsonl" else db.DataLoadError
    with pytest.raises(expected):
        with TestClient(create_app(Settings.for_test(tmp_path, LOAD_RUNTIME_PUZZLES=True), model=FakeModel())):
            pass
    assert not (tmp_path / "sessions.db").exists()
    assert (tmp_path / filename).read_bytes() == before


def test_snapshot_puzzle_is_used_even_if_live_catalog_changes(tmp_path):
    from app import migrations
    conn = old_database(tmp_path / "sessions.db")
    migrations.migrate(conn, [puzzle()], target_version=2)
    conn.close()
    changed = puzzle()
    changed.surface = "Changed surface"
    changed.bottom = "Changed truth"
    with TestClient(create_app(Settings.for_test(tmp_path), model=FakeModel(), soups=[changed])) as client:
        assert client.get("/api/session/old").json()["soupSurface"] == "Surface"


@pytest.mark.parametrize("fail_on", ["INSERT INTO turns", "UPDATE messages SET turn_id", "UPDATE sessions SET puzzle_version"])
def test_backfill_failure_does_not_leave_versions_or_half_round(tmp_path, fail_on):
    from app import migrations

    class FaultConnection(sqlite3.Connection):
        def execute(self, sql, parameters=()):
            if fail_on in sql:
                raise sqlite3.OperationalError("injected backfill failure")
            return super().execute(sql, parameters)

    conn = old_database(tmp_path / "old.db", factory=FaultConnection)
    before = "\n".join(conn.iterdump())
    with pytest.raises(migrations.MigrationError):
        migrations.migrate(conn, [puzzle()])
    assert "\n".join(conn.iterdump()) == before
    conn.close()
