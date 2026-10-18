"""Run actual isolated rehearsal and retired writers against synthetic inputs."""
from contextlib import closing
import hashlib
import json
import sqlite3

import pytest
from fastapi.testclient import TestClient

from app.config import BACKEND_DIR, Settings
from app.main import create_app
from app.testing import FakeModel
from .test_migrations import old_database, puzzle


def source_directory(tmp_path):
    source = tmp_path / "source"
    source.mkdir()
    (source / "generated_soups.json").write_text(json.dumps([puzzle().model_dump(mode="json")]), encoding="utf-8")
    return source


def source_hashes(source):
    return {file.name: hashlib.sha256(file.read_bytes()).hexdigest() for file in source.iterdir() if file.is_file()}


def invoke(source, tmp_path, *extra):
    from app.scripts import migrate_data
    return migrate_data.main(["--source", str(source), "--target", str(tmp_path / "target"),
                              "--report", str(tmp_path / "report.json"), *extra])


def test_dry_run_preserves_source_and_does_not_create_target(tmp_path, monkeypatch):
    import dotenv
    monkeypatch.setattr(dotenv, "dotenv_values", lambda *_a, **_k: pytest.fail("CLI must not load dotenv"))
    source = source_directory(tmp_path)
    conn = old_database(source / "sessions.db")
    conn.close()
    before = source_hashes(source)
    assert invoke(source, tmp_path, "--dry-run") == 0
    assert source_hashes(source) == before
    assert not (tmp_path / "target").exists()
    report = json.loads((tmp_path / "report.json").read_text(encoding="utf-8"))
    assert report["dryRun"] is True
    assert report["compatibleSessions"] == 1
    assert "Question?" not in json.dumps(report)


def test_rehearsal_uses_sqlite_backup_including_uncheckpointed_wal(tmp_path):
    source = source_directory(tmp_path)
    conn = old_database(source / "sessions.db")
    conn.execute("PRAGMA journal_mode=WAL")
    conn.execute("PRAGMA wal_autocheckpoint=0")
    conn.execute("UPDATE sessions SET question_limit=33")
    conn.commit()
    assert (source / "sessions.db-wal").stat().st_size > 0
    try:
        assert invoke(source, tmp_path) == 0
        with closing(sqlite3.connect(tmp_path / "target" / "sessions.db")) as target, target:
            assert target.execute("SELECT question_limit FROM sessions").fetchone()[0] == 33
            assert target.execute("SELECT count(*) FROM schema_migrations").fetchone()[0] == 1
        assert conn.execute("SELECT count(*) FROM sqlite_master WHERE name='schema_migrations'").fetchone()[0] == 0
    finally:
        conn.close()


def test_json_import_keeps_source_and_reports_duplicate_and_bad_record(tmp_path):
    source = source_directory(tmp_path)
    valid = {"id": "json-game", "soupId": "synthetic", "status": "playing", "questionsAsked": 1,
             "questionLimit": 10, "createdAt": 50, "messages": [
                 {"id": 71, "role": "user", "content": "Private synthetic question?", "timestamp": 51},
                 {"id": 72, "role": "host", "content": "是", "timestamp": 52},
             ]}
    (source / "sessions.json").write_text(json.dumps([valid, valid, {"id": "bad"}]), encoding="utf-8")
    before = source_hashes(source)
    assert invoke(source, tmp_path) == 2  # Needs manual review, not silently all-green.
    assert source_hashes(source) == before
    assert (source / "sessions.json").exists()
    assert not (source / "sessions.json.bak").exists()
    report = json.loads((tmp_path / "report.json").read_text(encoding="utf-8"))
    assert report["legacyRecords"] == 3
    assert report["importedSessions"] == 1
    assert {issue["code"] for issue in report["issues"]} == {"duplicate_session_id", "invalid_json_record"}
    assert "Private synthetic question" not in json.dumps(report)
    with closing(sqlite3.connect(tmp_path / "target" / "sessions.db")) as conn, conn:
        assert conn.execute("SELECT id,questions_asked,created_at FROM sessions").fetchone() == ("json-game", 1, 50)
        assert [row[0] for row in conn.execute("SELECT id FROM messages ORDER BY id")] == [71, 72]


def test_malformed_json_reports_failure_before_target_is_created(tmp_path):
    source = source_directory(tmp_path)
    (source / "sessions.json").write_text("{broken", encoding="utf-8")
    before = source_hashes(source)
    assert invoke(source, tmp_path) == 1
    assert source_hashes(source) == before
    assert not (tmp_path / "target").exists()
    assert json.loads((tmp_path / "report.json").read_text(encoding="utf-8"))["status"] == "failed"


@pytest.mark.parametrize("collision", ["target_source", "target_nonempty", "report_source", "report_exists", "target_report"])
def test_cli_rejects_paths_that_could_overwrite_inputs(tmp_path, collision):
    from app.scripts import migrate_data
    source = source_directory(tmp_path)
    target, report = tmp_path / "target", tmp_path / "report.json"
    if collision == "target_source":
        target = source
    elif collision == "target_nonempty":
        target.mkdir()
        (target / "sentinel").write_text("keep", encoding="utf-8")
    elif collision == "report_source":
        report = source / "generated_soups.json"
    elif collision == "report_exists":
        report.write_text("keep", encoding="utf-8")
    else:
        report = target / "sessions.db"
    before = source_hashes(source)
    assert migrate_data.main(["--source", str(source), "--target", str(target), "--report", str(report)]) == 1
    assert source_hashes(source) == before
    if collision in {"report_exists", "target_nonempty"}:
        assert (report if collision == "report_exists" else target / "sentinel").read_text(encoding="utf-8") == "keep"


def test_cli_refuses_actual_runtime_source_without_opening_it(tmp_path):
    from app.scripts import migrate_data
    assert migrate_data.main(["--source", str(BACKEND_DIR / "data"), "--target", str(tmp_path / "target"),
                              "--report", str(tmp_path / "report.json")]) == 1
    assert not (tmp_path / "target").exists()


def test_retired_cron_merge_and_cleanup_cannot_write_or_restart(tmp_path):
    from app.scripts import merge_verified_qa as old
    feedback, verified = tmp_path / "feedback.jsonl", tmp_path / "verified.jsonl"
    feedback.write_text('{"id":"fake","status":"approved","soupId":"synthetic","question":"?","expectedAnswer":"是"}\n', encoding="utf-8")
    before = feedback.read_bytes()
    with pytest.raises(old.LegacyWriterDisabled):
        old.run_merge(str(feedback), str(verified), restart_backend=True)
    with pytest.raises(old.LegacyWriterDisabled):
        old.cleanup_old_sessions()
    assert old.main() == 2
    assert feedback.read_bytes() == before
    assert not verified.exists()


def test_retired_http_merge_is_admin_only_and_returns_410(tmp_path):
    settings = Settings.for_test(tmp_path, ADMIN_TOKEN="synthetic-admin")
    with TestClient(create_app(settings, model=FakeModel())) as client:
        assert client.post("/api/feedback/admin/merge-verified").status_code == 401
        response = client.post("/api/feedback/admin/merge-verified", headers={"X-Admin-Token": "synthetic-admin"})
        assert response.status_code == 410
        assert response.json()["code"] == "legacy_writer_disabled"
    assert not (tmp_path / "verified_qa_pairs.jsonl").exists()
