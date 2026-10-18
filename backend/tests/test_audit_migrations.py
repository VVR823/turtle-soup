"""002 is explicit, independently atomic, and never rewrites released 001."""
from contextlib import closing
import json
import sqlite3

import pytest
from fastapi.testclient import TestClient

from app import baselines, db, migrations
from app.config import Settings
from app.main import create_app
from app.testing import FakeModel
from app.runtime import Runtime, runtime_context
from .test_migrations import old_database, puzzle
from .test_migration_cli import invoke, source_directory, source_hashes


def test_released_001_literals_are_pinned_before_002():
    assert migrations.CHECKSUM_001 == "e703a6f4ce5f102d0da973118dee3f08486b2e1f0c94a16ff5449acafe23f69b"
    assert baselines.digest(migrations.BASE_SQL + migrations.CORE_SQL) == "abb9cd5e98f7625e3a123186167c049afb9a714b94184f67c2c67e8246006137"


def test_default_stays_only_001(tmp_path):
    conn = old_database(tmp_path / "one.db")
    try:
        assert migrations.migrate(conn, [puzzle()])["migrationVersion"] == 1
        assert not {"feedback_items", "audit_events"} & migrations.table_names(conn)
        migrations.verify_schema(conn)
    finally:
        conn.close()


def test_explicit_002_tables_indexes_safe_default_and_no_future_tables(tmp_path):
    with closing(sqlite3.connect(tmp_path / "two.db")) as conn, conn:
        report = migrations.migrate(conn, [puzzle()], target_version=2)
        assert report["migrationVersion"] == 2
        assert migrations.table_names(conn) - migrations.CORE_TABLES - {"sqlite_sequence"} == {"feedback_items", "audit_events"}
        assert [tuple(row) for row in conn.execute("SELECT version,checksum FROM schema_migrations ORDER BY version")] == [(1, migrations.CHECKSUM_001), (2, migrations.CHECKSUM_002)]
        assert [row[2] for row in conn.execute("PRAGMA index_info(idx_audit_events_time)")] == ["created_at", "event_type"]
        assert [row[2] for row in conn.execute("PRAGMA index_info(idx_feedback_status)")] == ["status", "created_at"]
        conn.execute("INSERT INTO feedback_items (id,soup_id,payload_json,source_json,status,created_at) VALUES ('f','synthetic','{}','{}','pending',100)")
        assert tuple(conn.execute("SELECT safe_for_model,row_version FROM feedback_items").fetchone()) == (0, 0)
        with pytest.raises(sqlite3.IntegrityError):
            conn.execute("UPDATE feedback_items SET safe_for_model=2")
        migrations.verify_schema(conn, required_version=2)


def test_002_repeat_preserves_original_report_rows_ids_bytes_and_baselines(tmp_path):
    conn = old_database(tmp_path / "repeat.db")
    try:
        report001 = migrations.migrate(conn, [puzzle()])
        dump001 = {table: [tuple(row) for row in conn.execute(f"SELECT * FROM {table}")] for table in migrations.CORE_TABLES}
        report = migrations.migrate(conn, [puzzle()], target_version=2)
        assert report["baseline"] == report001["baseline"]
        assert migrations.migrate(conn, [puzzle()], target_version=2) == report
        assert migrations.migrate(conn, [puzzle()]) == report001
        for table, rows in dump001.items():
            actual = [tuple(row) for row in conn.execute(f"SELECT * FROM {table}")]
            if table in {"schema_migrations", "runtime_meta"}:
                assert all(row in actual for row in rows)
            else:
                assert actual == rows
        coverage = json.loads(conn.execute("SELECT value_json FROM runtime_meta WHERE key='audit_coverage_start'").fetchone()[0])
        assert coverage["historicalAttemptsBackfilled"] is False
        assert coverage["startedAt"] == report["phase002"]["coverageStart"]
        assert conn.execute("SELECT count(*) FROM audit_events").fetchone()[0] == 0
        assert not conn.in_transaction
    finally:
        conn.close()


@pytest.mark.parametrize("fail_on", ["CREATE TABLE feedback_items", "CREATE TABLE audit_events", "CREATE INDEX idx_audit_events_time", "CREATE INDEX idx_feedback_status", "'audit_coverage_start'", "'migration_002_report'", "INSERT INTO schema_migrations"])
def test_each_002_statement_failure_rolls_back_only_that_phase(tmp_path, fail_on):
    class FaultConnection(sqlite3.Connection):
        armed = False

        def execute(self, sql, parameters=()):
            if self.armed and fail_on in sql:
                raise sqlite3.OperationalError("synthetic phase002 fault")
            return super().execute(sql, parameters)

    conn = old_database(tmp_path / "rollback.db", factory=FaultConnection)
    try:
        original = migrations.migrate(conn, [puzzle()])
        before = "\n".join(conn.iterdump())
        conn.armed = True
        with pytest.raises(migrations.MigrationError):
            migrations.migrate(conn, [puzzle()], target_version=2)
        assert not conn.in_transaction
        assert "\n".join(conn.iterdump()) == before
        migrations.verify_schema(conn)
        assert migrations.migrate(conn, [puzzle()]) == original
    finally:
        conn.close()


@pytest.mark.parametrize("mutation", ["checksum", "gap", "future", "missing_table", "missing_column", "missing_index", "wrong_index"])
def test_002_drift_is_refused_read_only(tmp_path, mutation):
    with closing(sqlite3.connect(tmp_path / "drift.db")) as conn, conn:
        migrations.migrate(conn, [puzzle()], target_version=2)
        if mutation == "checksum":
            conn.execute("UPDATE schema_migrations SET checksum='wrong' WHERE version=2")
        elif mutation == "gap":
            conn.execute("DELETE FROM schema_migrations WHERE version=1")
        elif mutation == "future":
            conn.execute("INSERT INTO schema_migrations VALUES (3,'unknown',100)")
        elif mutation == "missing_table":
            conn.execute("DROP TABLE audit_events")
        elif mutation == "missing_column":
            conn.execute("ALTER TABLE audit_events DROP COLUMN details_json")
        else:
            conn.execute("DROP INDEX idx_audit_events_time")
            if mutation == "wrong_index":
                conn.execute("CREATE INDEX idx_audit_events_time ON audit_events(id)")
        conn.commit(); before = "\n".join(conn.iterdump())
        with pytest.raises(migrations.MigrationError):
            migrations.verify_schema(conn, required_version=2)
        assert "\n".join(conn.iterdump()) == before


@pytest.mark.parametrize("wal", [False, True])
def test_existing_001_startup_refuses_before_wal_without_source_changes(tmp_path, monkeypatch, wal):
    conn = old_database(tmp_path / "sessions.db")
    migrations.migrate(conn, [puzzle()])
    if wal:
        conn.execute("PRAGMA journal_mode=WAL")
    conn.close()
    before = source_hashes(tmp_path)
    monkeypatch.setattr(db, "_connect", lambda: pytest.fail("WAL connection must not open before required002 verification"))
    with pytest.raises(migrations.MigrationRequired):
        with TestClient(create_app(Settings.for_test(tmp_path), model=FakeModel(), soups=[puzzle()])):
            pass
    assert source_hashes(tmp_path) == before
    assert not (tmp_path / "sessions.db-wal").exists()
    assert not (tmp_path / "sessions.db-shm").exists()


def test_new_application_initializes_002(tmp_path):
    with TestClient(create_app(Settings.for_test(tmp_path), model=FakeModel(), soups=[puzzle()])) as client:
        assert client.get("/api/soups").status_code == 200
    with closing(sqlite3.connect(tmp_path / "sessions.db")) as conn, conn:
        migrations.verify_schema(conn, required_version=2)


@pytest.mark.parametrize("version", [1, 2])
def test_startup_preflight_reads_uncheckpointed_wal_without_touching_source(tmp_path, version):
    conn = old_database(tmp_path / "sessions.db")
    try:
        migrations.migrate(conn, [puzzle()], target_version=version)
        conn.execute("PRAGMA journal_mode=WAL"); conn.execute("PRAGMA wal_autocheckpoint=0")
        conn.execute("UPDATE sessions SET question_limit=33"); conn.commit()
        assert (tmp_path / "sessions.db-wal").stat().st_size > 0
        before = source_hashes(tmp_path)
        runtime = Runtime(Settings.for_test(tmp_path), model=FakeModel(), soups=[puzzle()])
        with runtime_context(runtime):
            if version == 1:
                with pytest.raises(migrations.MigrationRequired):
                    db.initialize()
            else:
                db.initialize(); assert runtime.initialized
                assert runtime.soups[0].bottom == "Truth"
        assert source_hashes(tmp_path) == before
    finally:
        conn.close()


def test_preflight_refuses_a_source_changed_during_copy(tmp_path, monkeypatch):
    conn = old_database(tmp_path / "sessions.db")
    try:
        migrations.migrate(conn, [puzzle()], target_version=2)
        conn.execute("PRAGMA journal_mode=WAL"); conn.execute("PRAGMA wal_autocheckpoint=0")
        conn.execute("UPDATE sessions SET question_limit=33"); conn.commit()
        original_copy = db.shutil.copy2

        def copy_and_change(source, target, *args, **kwargs):
            result = original_copy(source, target, *args, **kwargs)
            if source.name == "sessions.db":
                conn.execute("UPDATE sessions SET question_limit=32"); conn.commit()
            return result

        monkeypatch.setattr(db.shutil, "copy2", copy_and_change)
        runtime = Runtime(Settings.for_test(tmp_path), model=FakeModel(), soups=[puzzle()])
        with runtime_context(runtime), pytest.raises(migrations.MigrationError, match="changed during startup"):
            db.initialize()
        assert runtime.initialized is False
        assert conn.execute("SELECT question_limit FROM sessions").fetchone()[0] == 32
    finally:
        conn.close()


@pytest.mark.parametrize("dry", [False, True])
def test_cli_explicit002_preserves_source_and_old_report(tmp_path, dry, capsys):
    source = source_directory(tmp_path)
    conn = old_database(source / "sessions.db")
    original = migrations.migrate(conn, [puzzle()]); conn.close()
    before = source_hashes(source)
    assert invoke(source, tmp_path, "--target-version", "2", *( ["--dry-run"] if dry else [])) == 0
    report = json.loads((tmp_path / "report.json").read_text(encoding="utf-8"))
    assert report["migrationVersion"] == 2
    assert report["baseline"] == original["baseline"]
    assert report["productionReady"] is False
    assert source_hashes(source) == before
    assert json.loads(capsys.readouterr().out)["migrationVersion"] == 2
    if dry:
        assert not (tmp_path / "target").exists()
    else:
        with closing(sqlite3.connect(tmp_path / "target" / "sessions.db")) as target, target:
            migrations.verify_schema(target, required_version=2)
            assert json.loads(target.execute("SELECT value_json FROM runtime_meta WHERE key='migration_001_report'").fetchone()[0]) == original


def test_cli_002_existing_output_is_never_overwritten(tmp_path):
    source = source_directory(tmp_path); target = tmp_path / "target"; target.mkdir()
    (target / "sentinel").write_text("keep", encoding="utf-8")
    assert invoke(source, tmp_path, "--target-version", "2") == 1
    assert (target / "sentinel").read_text(encoding="utf-8") == "keep"
