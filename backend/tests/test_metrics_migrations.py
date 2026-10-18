"""Explicit indexes-only004 on owned synthetic SQLite; no player storage.

Breaks caught: unregistered/default automatic phase4, wrong index columns,
overwriting old reports/rows, skipped003 verification, and partial004 commits.
"""
from contextlib import closing
import json
import sqlite3

import pytest

from app import migrations
from .test_agent_migrations import identities
from .test_migration_cli import invoke, source_directory, source_hashes
from .test_migrations import old_database, puzzle


INDEXES = {
    "idx_sessions_created": ("sessions", ["created_at", "id"]),
    "idx_turns_completed": ("turns", ["completed_at", "id"]),
    "idx_feedback_created": ("feedback_items", ["created_at", "id"]),
    "idx_agent_runs_created": ("agent_runs", ["created_at", "id"]),
    "idx_rule_candidates_created": ("rule_candidates", ["created_at", "id"]),
}


def phase4(conn):
    return migrations.migrate(conn, [puzzle()], target_version=4)


def dump(conn):
    return "\n".join(conn.iterdump())


def test_registered_004_indexes_and_report(tmp_path):
    with closing(sqlite3.connect(tmp_path / "four.db")) as conn, conn:
        report = phase4(conn)
        assert report["migrationVersion"] == 4
        assert report["phase004"] == {
            "checksum": migrations.CHECKSUM_004,
            "indexNames": list(INDEXES), "noHistoricalBackfill": True,
        }
        assert [r[0] for r in conn.execute("SELECT version FROM schema_migrations ORDER BY version")] == [1, 2, 3, 4]
        for name, (table, columns) in INDEXES.items():
            assert conn.execute("SELECT tbl_name FROM sqlite_master WHERE name=?", (name,)).fetchone()[0] == table
            assert [r[2] for r in conn.execute(f"PRAGMA index_info({name})")] == columns
        for version in (1, 2, 3, 4):
            migrations.verify_schema(conn, required_version=version)
        assert conn.execute("PRAGMA foreign_key_check").fetchall() == []
        assert conn.execute("PRAGMA integrity_check").fetchone()[0] == "ok"


def test_defaults_and_prior_released_checksums_stay_unchanged(tmp_path):
    assert migrations.CHECKSUM_001 == "e703a6f4ce5f102d0da973118dee3f08486b2e1f0c94a16ff5449acafe23f69b"
    assert migrations.CHECKSUM_002 == "aec0b404acbead6c2b6dfe93418394ed2204533c260873ffabbf605c2c545118"
    with closing(sqlite3.connect(tmp_path / "default.db")) as conn, conn:
        assert migrations.migrate(conn, [puzzle()])["migrationVersion"] == 1
        assert not set(INDEXES) & {r[0] for r in conn.execute("SELECT name FROM sqlite_master")}
        assert not {"feedback_items", "agent_runs"} & migrations.table_names(conn)


@pytest.mark.parametrize("version", [1, 2, 3])
def test_required_004_refuses_old_phase_without_writes(tmp_path, version):
    with closing(sqlite3.connect(tmp_path / "oldphase.db")) as conn, conn:
        migrations.migrate(conn, [puzzle()], target_version=version)
        before = dump(conn)
        with pytest.raises(migrations.MigrationRequired):
            migrations.verify_schema(conn, required_version=4)
        assert dump(conn) == before and not conn.in_transaction


def test_004_rerun_keeps_old_rows_and_returns_each_original_report(tmp_path):
    conn = old_database(tmp_path / "history.db")
    try:
        old_reports = {v: migrations.migrate(conn, [puzzle()], target_version=v) for v in (1, 2, 3)}
        identities(conn)
        conn.commit()
        table_rows = {table: [tuple(r) for r in conn.execute(f"SELECT * FROM {table} ORDER BY rowid")]
                      for table in migrations.table_names(conn)}
        prior_sql = {r[0]: r[1] for r in conn.execute("SELECT name,sql FROM sqlite_master WHERE sql IS NOT NULL")}
        report4 = phase4(conn)
        for table, rows in table_rows.items():
            actual = [tuple(r) for r in conn.execute(f"SELECT * FROM {table} ORDER BY rowid")]
            assert all(row in actual for row in rows) if table in {"runtime_meta", "schema_migrations"} else actual == rows
        for name, sql in prior_sql.items():
            assert conn.execute("SELECT sql FROM sqlite_master WHERE name=?", (name,)).fetchone()[0] == sql
        before, changes = dump(conn), conn.total_changes
        assert phase4(conn) == report4
        for version, report in old_reports.items():
            assert migrations.migrate(conn, [puzzle()], target_version=version) == report
        assert dump(conn) == before and conn.total_changes == changes
    finally:
        conn.close()


@pytest.mark.parametrize("fault", [*INDEXES, "report", "ledger", "verify", "foreign_keys", "integrity", "commit"])
def test_every_004_failure_hits_target_and_rolls_back_only_004(tmp_path, fault):
    class FaultConnection(sqlite3.Connection):
        armed = False
        phase_started = False
        hits = 0

        def execute(self, sql, parameters=()):
            if self.armed and sql == "BEGIN IMMEDIATE":
                self.phase_started = True
            matches = (fault in INDEXES and sql.startswith(f"CREATE INDEX {fault} ")
                       or fault == "report" and "INSERT INTO runtime_meta" in sql and "'migration_004_report'" in sql
                       or fault == "ledger" and "INSERT INTO schema_migrations" in sql
                       or fault == "verify" and sql.startswith("SELECT version,checksum FROM schema_migrations")
                       or fault == "foreign_keys" and sql == "PRAGMA foreign_key_check"
                       or fault == "integrity" and sql == "PRAGMA integrity_check")
            if self.armed and self.phase_started and matches:
                self.hits += 1
                raise sqlite3.OperationalError("declared synthetic004 fault")
            return super().execute(sql, parameters)

        def commit(self):
            if self.armed and self.phase_started and fault == "commit":
                self.hits += 1
                raise sqlite3.OperationalError("declared synthetic004 commit fault")
            return super().commit()

    conn = sqlite3.connect(tmp_path / "fault.db", factory=FaultConnection)
    try:
        migrations.migrate(conn, [puzzle()], target_version=3)
        identities(conn)
        conn.commit()
        before = dump(conn)
        conn.armed = True
        with pytest.raises(migrations.MigrationError):
            phase4(conn)
        assert conn.hits == 1, "Fault must hit the declared004 boundary, not an earlier refusal"
        assert not conn.in_transaction and dump(conn) == before
        conn.armed = False
        migrations.verify_schema(conn, required_version=3)
        assert not set(INDEXES) & {r[0] for r in conn.execute("SELECT name FROM sqlite_master")}
    finally:
        conn.close()


@pytest.mark.parametrize("mutation", ["checksum", "gap", "future", "missing_index", "wrong_index",
    "report_missing", "report_phase", "report_bool", "report_indexes", "report_prior", "agent_index", "agent_report"])
def test_004_drift_rejects_even_old_consumers_read_only(tmp_path, mutation):
    with closing(sqlite3.connect(tmp_path / "drift.db")) as conn, conn:
        report = phase4(conn)
        if mutation == "checksum":
            conn.execute("UPDATE schema_migrations SET checksum='wrong' WHERE version=4")
        elif mutation == "gap":
            conn.execute("DELETE FROM schema_migrations WHERE version=3")
        elif mutation == "future":
            conn.execute("INSERT INTO schema_migrations VALUES(5,'future',100)")
        elif mutation in {"missing_index", "wrong_index"}:
            conn.execute("DROP INDEX idx_turns_completed")
            if mutation == "wrong_index":
                conn.execute("CREATE INDEX idx_turns_completed ON turns(id,completed_at)")
        elif mutation == "report_missing":
            conn.execute("DELETE FROM runtime_meta WHERE key='migration_004_report'")
        elif mutation == "agent_index":
            conn.execute("DROP INDEX idx_agent_runs_state")
        elif mutation == "agent_report":
            conn.execute("DELETE FROM runtime_meta WHERE key='migration_003_report'")
        else:
            if mutation == "report_phase": report["migrationVersion"] = True
            elif mutation == "report_bool": report["phase004"]["noHistoricalBackfill"] = 1
            elif mutation == "report_indexes": report["phase004"]["indexNames"].reverse()
            elif mutation == "report_prior": report["phase003"]["coverageStart"] += 1
            conn.execute("UPDATE runtime_meta SET value_json=? WHERE key='migration_004_report'", (json.dumps(report),))
        conn.commit()
        before = dump(conn)
        for version in (1, 2, 3, 4):
            with pytest.raises(migrations.MigrationError):
                migrations.verify_schema(conn, required_version=version)
        assert dump(conn) == before


def test_cli_explicit_004_preserves_owned_source_and_default_is_still_001(tmp_path):
    source = source_directory(tmp_path)
    before = source_hashes(source)
    assert invoke(source, tmp_path, "--target-version", "4") == 0
    assert source_hashes(source) == before
    with closing(sqlite3.connect(tmp_path / "target" / "sessions.db")) as conn, conn:
        migrations.verify_schema(conn, required_version=4)
        assert conn.execute("SELECT max(version) FROM schema_migrations").fetchone()[0] == 4
    default_root = tmp_path / "default"
    default_root.mkdir()
    default_source = source_directory(default_root)
    assert invoke(default_source, default_root) == 0
    with closing(sqlite3.connect(default_root / "target" / "sessions.db")) as conn, conn:
        assert conn.execute("SELECT max(version) FROM schema_migrations").fetchone()[0] == 1
