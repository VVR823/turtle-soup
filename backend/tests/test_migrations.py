"""001 migration contracts on synthetic SQLite only, never runtime databases."""
from contextlib import closing
import json
import sqlite3

import pytest

from app.schemas import Soup


def puzzle():
    return Soup(id="synthetic", title="Test", surface="Surface", bottom="Truth",
                checkpoints=[{"key": "fact", "answer": True}],
                confusionPoints=[{"q": "Question?", "a": "是"}])


def old_database(path, *, factory=sqlite3.Connection):
    conn = sqlite3.connect(path, factory=factory)
    conn.row_factory = sqlite3.Row
    conn.executescript("""
        PRAGMA foreign_keys=ON;
        CREATE TABLE sessions (
            id TEXT PRIMARY KEY, soup_id TEXT NOT NULL, status TEXT NOT NULL DEFAULT 'playing',
            questions_asked INTEGER NOT NULL DEFAULT 0, question_limit INTEGER,
            created_at REAL NOT NULL, solved_at REAL, given_up_at REAL);
        CREATE TABLE messages (
            id INTEGER PRIMARY KEY AUTOINCREMENT, session_id TEXT NOT NULL,
            role TEXT NOT NULL, content TEXT NOT NULL, timestamp REAL NOT NULL,
            is_free_reminder INTEGER NOT NULL DEFAULT 0,
            FOREIGN KEY(session_id) REFERENCES sessions(id));
        INSERT INTO sessions VALUES ('old', 'synthetic', 'playing', 1, 20, 100, NULL, NULL);
        INSERT INTO messages VALUES (41, 'old', 'user', 'Question?', 101, 0);
        INSERT INTO messages VALUES (42, 'old', 'host', '是', 102, 0);
    """)
    return conn


def test_new_database_has_only_001_tables(tmp_path):
    from app import migrations
    with closing(sqlite3.connect(tmp_path / "new.db")) as conn, conn:
        conn.row_factory = sqlite3.Row
        report = migrations.migrate(conn, [puzzle()])
        names = {row[0] for row in conn.execute("SELECT name FROM sqlite_master WHERE type='table'")}
        assert names - {"sqlite_sequence"} == {
            "sessions", "messages", "schema_migrations", "puzzle_versions", "rule_releases",
            "runtime_meta", "creation_requests", "turns", "evaluations",
        }
        assert report["migrationVersion"] == 1
        assert list(conn.execute("PRAGMA foreign_key_check")) == []


def test_old_ids_counts_timestamps_and_message_bytes_preserved(tmp_path):
    from app import migrations
    conn = old_database(tmp_path / "old.db")
    before = [tuple(row) for row in conn.execute("SELECT * FROM sessions")]
    messages = [tuple(row) for row in conn.execute("SELECT * FROM messages ORDER BY id")]
    migrations.migrate(conn, [puzzle()])
    assert [tuple(row) for row in conn.execute(
        "SELECT id,soup_id,status,questions_asked,question_limit,created_at,solved_at,given_up_at FROM sessions"
    )] == before
    assert [tuple(row) for row in conn.execute(
        "SELECT id,session_id,role,content,timestamp,is_free_reminder FROM messages ORDER BY id"
    )] == messages
    conn.close()


def test_repeat_is_idempotent_and_message_query_uses_index(tmp_path):
    from app import migrations
    conn = old_database(tmp_path / "old.db")
    first = migrations.migrate(conn, [puzzle()])
    assert migrations.migrate(conn, [puzzle()]) == first
    assert conn.execute("SELECT count(*) FROM schema_migrations").fetchone()[0] == 1
    assert conn.execute("SELECT count(*) FROM messages").fetchone()[0] == 2
    plan = conn.execute("EXPLAIN QUERY PLAN SELECT role,content FROM messages WHERE session_id=? ORDER BY id", ("old",)).fetchall()
    assert any("idx_messages_session_id" in row[3] for row in plan)
    conn.close()


@pytest.mark.parametrize("mutation", ["checksum", "future_version", "missing_table"])
def test_unknown_or_drifted_schema_is_refused(tmp_path, mutation):
    from app import migrations
    conn = old_database(tmp_path / "old.db")
    migrations.migrate(conn, [puzzle()])
    if mutation == "checksum":
        conn.execute("UPDATE schema_migrations SET checksum='wrong'")
    elif mutation == "future_version":
        conn.execute("INSERT INTO schema_migrations VALUES (99,'future',200)")
    else:
        conn.execute("DROP TABLE evaluations")
    conn.commit()
    before = conn.total_changes
    with pytest.raises(migrations.MigrationError):
        migrations.migrate(conn, [puzzle()])
    assert conn.total_changes == before
    conn.close()


@pytest.mark.parametrize("fail_on", [
    "CREATE TABLE schema_migrations", "ADD COLUMN row_version", "ADD COLUMN puzzle_version",
    "ADD COLUMN rule_version", "ADD COLUMN compat_state", "ADD COLUMN last_activity_at",
    "ADD COLUMN traffic_class", "CREATE TABLE puzzle_versions", "CREATE TABLE rule_releases",
    "CREATE TABLE runtime_meta", "CREATE TABLE creation_requests", "CREATE TABLE turns",
    "CREATE UNIQUE INDEX idx_turns_active", "ADD COLUMN turn_id",
    "CREATE INDEX idx_messages_session_id", "CREATE TABLE evaluations",
    "INSERT INTO puzzle_versions", "INSERT INTO rule_releases", "INSERT INTO runtime_meta",
    "INSERT INTO schema_migrations",
])
def test_failure_rolls_back_entire_phase(tmp_path, fail_on):
    from app import migrations

    class FailingConnection(sqlite3.Connection):
        def execute(self, sql, parameters=()):
            if fail_on in sql:
                raise sqlite3.OperationalError("injected migration failure")
            return super().execute(sql, parameters)

    conn = old_database(tmp_path / "old.db", factory=FailingConnection)
    before = "\n".join(conn.iterdump())
    with pytest.raises(migrations.MigrationError):
        migrations.migrate(conn, [puzzle()])
    assert not conn.in_transaction
    assert "\n".join(conn.iterdump()) == before
    conn.close()


def test_full_snapshot_restores_after_input_changes(tmp_path):
    from app import baselines, migrations
    conn = old_database(tmp_path / "old.db")
    original = puzzle()
    migrations.migrate(conn, [original])
    original.bottom = "Changed later"
    original.confusionPoints[0].a = "不是"
    restored = baselines.active_soups(conn)
    assert restored[0].bottom == "Truth"
    assert restored[0].confusionPoints[0].a == "是"
    assert restored[0].checkpoints[0].key == "fact"
    conn.close()


@pytest.mark.parametrize("table,column", [("puzzle_versions", "payload_json"), ("rule_releases", "rules_json")])
def test_snapshots_cannot_be_updated_or_deleted(tmp_path, table, column):
    from app import migrations
    conn = old_database(tmp_path / "old.db")
    migrations.migrate(conn, [puzzle()])
    with pytest.raises(sqlite3.IntegrityError):
        conn.execute(f"UPDATE {table} SET {column}='{{}}'")
    with pytest.raises(sqlite3.IntegrityError):
        conn.execute(f"DELETE FROM {table}")
    conn.close()


def test_corrupted_snapshot_fails_instead_of_falling_back(tmp_path):
    from app import baselines, migrations
    conn = old_database(tmp_path / "old.db")
    migrations.migrate(conn, [puzzle()])
    conn.execute("DROP TRIGGER puzzle_versions_no_update")
    raw = json.loads(conn.execute("SELECT payload_json FROM puzzle_versions").fetchone()[0])
    raw["soup"]["bottom"] = "Tampered"
    conn.execute("UPDATE puzzle_versions SET payload_json=?", (json.dumps(raw),))
    conn.commit()
    with pytest.raises(baselines.SnapshotError):
        baselines.active_soups(conn)
    conn.close()
