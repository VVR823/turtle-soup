"""Independent-review findings reproduced on guarded synthetic data only."""
import json
import shutil
import sqlite3

import pytest
from fastapi.testclient import TestClient

from app import baselines, migrations
from app.config import Settings
from app.main import create_app
from app.testing import FakeModel
from .test_migration_cli import invoke, source_directory, source_hashes
from .test_migrations import old_database, puzzle


def test_missing_legacy_fk_and_orphan_are_refused_before_any_changes(tmp_path):
    conn = sqlite3.connect(tmp_path / "missing-fk.db")
    conn.execute(migrations.BASE_SQL[0])
    conn.execute(migrations.BASE_SQL[1].replace(",FOREIGN KEY(session_id) REFERENCES sessions(id)", ""))
    conn.execute("INSERT INTO messages VALUES (1,'orphan','user','synthetic?',100,0)")
    conn.commit()
    before = "\n".join(conn.iterdump())
    try:
        with pytest.raises(migrations.MigrationError):
            migrations.migrate(conn, [puzzle()])
        assert "\n".join(conn.iterdump()) == before
    finally:
        conn.close()


@pytest.mark.parametrize("failure", ["missing", "digest", "puzzle_relationship"])
def test_session_rule_release_must_exist_be_intact_and_match_puzzle(tmp_path, failure):
    conn = old_database(tmp_path / "sessions.db")
    migrations.migrate(conn, [puzzle()], target_version=2)  # Boot an M2 app; snapshot error assertions stay intact.
    original = conn.execute("SELECT puzzle_version,rule_version FROM sessions").fetchone()
    release = conn.execute("SELECT rules_json,manifest_json FROM rule_releases WHERE id=?", (original[1],)).fetchone()
    version = "r1:missing"
    if failure != "missing":
        rules, manifest = json.loads(release[0]), json.loads(release[1])
        if failure == "puzzle_relationship":
            changed = puzzle()
            changed.bottom = "Different synthetic truth"
            payload = {"schemaVersion": 1, "soup": changed.model_dump(mode="json")}
            puzzle_version = "p1:" + baselines.digest(payload)
            conn.execute("INSERT INTO puzzle_versions VALUES (?,?,?,100)",
                         (puzzle_version, changed.id, baselines.canonical_json(payload)))
            manifest["puzzleVersions"][changed.id] = puzzle_version
        version = "r1:" + baselines.digest({"rules": rules, "manifest": manifest})
        if failure == "digest":
            version = "r1:" + "0" * 64
        conn.execute("INSERT INTO rule_releases VALUES (?,NULL,?,?,100)",
                     (version, baselines.canonical_json(rules), baselines.canonical_json(manifest)))
    conn.execute("UPDATE sessions SET rule_version=?", (version,))
    conn.commit()
    conn.close()
    app = create_app(Settings.for_test(tmp_path), model=FakeModel(), soups=[puzzle()])
    with TestClient(app) as client:
        for response in (
            client.get("/api/session/old"),
            client.post("/api/chat", json={"sessionId": "old", "question": "还能继续吗？"}),
            client.post("/api/evaluate", json={"sessionId": "old"}),
        ):
            assert response.status_code == 503
            assert response.json()["code"] == "snapshot_unavailable"
            assert "Different synthetic truth" not in response.text
        assert not app.state.runtime.model.calls


def legacy_record(identifier, explicit=False):
    messages = [
        {"role": "user", "content": "synthetic?", "timestamp": 101},
        {"role": "host", "content": "是", "timestamp": 102},
    ]
    if explicit:
        messages[0]["id"], messages[1]["id"] = 1, 2
    return {"id": identifier, "soupId": "synthetic", "questionsAsked": 1,
            "createdAt": 100, "messages": messages}


def test_generated_ids_reserve_later_explicit_ids_in_the_entire_input(tmp_path):
    conn = sqlite3.connect(tmp_path / "import.db")
    try:
        report = migrations.migrate(conn, [puzzle()], legacy_records=[
            legacy_record("generated-first"), legacy_record("explicit-later", explicit=True),
        ])
        assert report["importedSessions"] == 2
        assert report["issues"] == []
        assert [row[0] for row in conn.execute("SELECT id FROM messages WHERE session_id='explicit-later' ORDER BY id")] == [1, 2]
        assert [row[0] for row in conn.execute("SELECT id FROM messages WHERE session_id='generated-first' ORDER BY id")] == [3, 4]
    finally:
        conn.close()


@pytest.mark.parametrize("field", ["questionsAsked", "questionLimit", "message_id"])
def test_cli_reports_sqlite_integer_overflow_as_invalid_record_not_uncaught_error(tmp_path, field):
    source = source_directory(tmp_path)
    record = legacy_record("large-integer", explicit=True)
    if field == "message_id":
        record["messages"][0]["id"] = 2 ** 63
    else:
        record[field] = 2 ** 63
    (source / "sessions.json").write_text(json.dumps([record]), encoding="utf-8")
    before = source_hashes(source)
    assert invoke(source, tmp_path) == 2
    report = json.loads((tmp_path / "report.json").read_text(encoding="utf-8"))
    assert report["status"] == "needs_review"
    assert report["issues"][0]["code"] == "invalid_json_record"
    assert report["importedSessions"] == 0
    assert source_hashes(source) == before


def test_dry_run_does_not_create_shm_in_a_wal_source_copy(tmp_path):
    original = tmp_path / "original"
    original.mkdir()
    source = source_directory(tmp_path)
    conn = old_database(original / "sessions.db")
    conn.execute("PRAGMA journal_mode=WAL")
    conn.execute("PRAGMA wal_autocheckpoint=0")
    conn.execute("UPDATE sessions SET question_limit=33")
    conn.commit()
    try:
        for name in ("sessions.db", "sessions.db-wal"):
            shutil.copyfile(original / name, source / name)
        assert not (source / "sessions.db-shm").exists()
        before = source_hashes(source)
        assert invoke(source, tmp_path, "--dry-run") == 0
        assert source_hashes(source) == before
        assert not (source / "sessions.db-shm").exists()
        assert json.loads((tmp_path / "report.json").read_text(encoding="utf-8"))["sourceUnchanged"] is True
    finally:
        conn.close()
