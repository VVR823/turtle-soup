"""003 remains explicit and atomic on synthetic SQLite, never player storage."""
import json
import sqlite3
from contextlib import closing
from uuid import uuid4

import pytest

from app import migrations
from .test_migrations import old_database, puzzle

AGENT_TABLES = {"agent_runs", "agent_steps", "rule_candidates"}


def phase3(conn):
    return migrations.migrate(conn, [puzzle()], target_version=3)


def identities(conn):
    feedback, run, request, candidate, operation = (str(uuid4()) for _ in range(5))
    conn.execute("INSERT INTO feedback_items(id,soup_id,payload_json,source_json,status,created_at) VALUES (?,'synthetic','{}','{}','pending',100)", (feedback,))
    conn.execute("INSERT INTO agent_runs(id,request_id,feedback_id,state,checkpoint_json,manifest_json,created_at,updated_at) VALUES (?,?,?,'queued','{}','{}',100,100)", (run, request, feedback))
    conn.execute("INSERT INTO agent_steps(run_id,seq,operation_key,action_json,state,created_at) VALUES (?,0,?,'{}','planned',100)", (run, operation))
    conn.execute("INSERT INTO rule_candidates(id,run_id,soup_id,base_rule_version,candidate_json,candidate_digest,regression_json,status,created_at) VALUES (?,?,'synthetic','synthetic-base','{}',?,'{}','pending',100)", (candidate, run, "a" * 64))
    return feedback, run, request, candidate, operation


def test_prior_released_checksums_and_defaults_never_enable_agent_tables(tmp_path):
    assert migrations.CHECKSUM_001 == "e703a6f4ce5f102d0da973118dee3f08486b2e1f0c94a16ff5449acafe23f69b"
    assert migrations.CHECKSUM_002 == "aec0b404acbead6c2b6dfe93418394ed2204533c260873ffabbf605c2c545118"
    with closing(sqlite3.connect(tmp_path / "default.db")) as conn, conn:
        assert migrations.migrate(conn, [puzzle()])["migrationVersion"] == 1
        assert not AGENT_TABLES & migrations.table_names(conn)
        assert migrations.migrate(conn, [puzzle()], target_version=2)["migrationVersion"] == 2
        assert not AGENT_TABLES & migrations.table_names(conn)


def test_registered_003_tables_foreign_keys_index_and_reports(tmp_path):
    with closing(sqlite3.connect(tmp_path / "three.db")) as conn, conn:
        report = phase3(conn)
        assert report["migrationVersion"] == 3
        assert migrations.table_names(conn) - migrations.CORE_TABLES - {"feedback_items", "audit_events", "sqlite_sequence"} == AGENT_TABLES
        assert [tuple(r) for r in conn.execute("SELECT version,checksum FROM schema_migrations ORDER BY version")] == [
            (1, migrations.CHECKSUM_001), (2, migrations.CHECKSUM_002), (3, migrations.CHECKSUM_003)]
        assert [r[2] for r in conn.execute("PRAGMA index_info(idx_agent_runs_state)")] == ["state", "updated_at"]
        assert report["phase003"]["checksum"] == migrations.CHECKSUM_003
        assert report["phase003"]["historicalRunsBackfilled"] is False
        assert conn.execute("PRAGMA foreign_key_check").fetchall() == []
        assert conn.execute("PRAGMA integrity_check").fetchone()[0] == "ok"
        for version in (1, 2, 3): migrations.verify_schema(conn, required_version=version)


def test_003_rerun_preserves_all_original_rows_and_each_old_report(tmp_path):
    conn = old_database(tmp_path / "history.db")
    try:
        report1 = migrations.migrate(conn, [puzzle()])
        report2 = migrations.migrate(conn, [puzzle()], target_version=2)
        original = {table: [tuple(r) for r in conn.execute(f"SELECT * FROM {table}")] for table in migrations.CORE_TABLES}
        report3 = phase3(conn)
        identities(conn); conn.commit()
        before = "\n".join(conn.iterdump())
        assert phase3(conn) == report3
        assert migrations.migrate(conn, [puzzle()]) == report1
        assert migrations.migrate(conn, [puzzle()], target_version=2) == report2
        assert "\n".join(conn.iterdump()) == before
        for table, rows in original.items():
            after = [tuple(r) for r in conn.execute(f"SELECT * FROM {table}")]
            assert all(row in after for row in rows) if table in {"schema_migrations", "runtime_meta"} else after == rows
    finally:
        conn.close()


@pytest.mark.parametrize("version", [1, 2])
def test_required_003_refuses_prior_phase_read_only(tmp_path, version):
    with closing(sqlite3.connect(tmp_path / "prior.db")) as conn, conn:
        migrations.migrate(conn, [puzzle()], target_version=version)
        before = "\n".join(conn.iterdump())
        with pytest.raises(migrations.MigrationRequired): migrations.verify_schema(conn, required_version=3)
        assert "\n".join(conn.iterdump()) == before


def test_every_003_statement_and_ledger_failure_rolls_back_only_003(tmp_path):
    class FaultConnection(sqlite3.Connection):
        trigger = None
        def execute(self, sql, parameters=()):
            if self.trigger and self.trigger in sql: raise sqlite3.OperationalError("synthetic003 fault")
            return super().execute(sql, parameters)
    statements = migrations.AGENT_SQL + ("'migration_003_report'", "INSERT INTO schema_migrations")
    for index, fault in enumerate(statements):
        conn = sqlite3.connect(tmp_path / f"fault-{index}.db", factory=FaultConnection)
        try:
            migrations.migrate(conn, [puzzle()], target_version=2)
            before = "\n".join(conn.iterdump())
            conn.trigger = fault
            with pytest.raises(migrations.MigrationError): phase3(conn)
            assert not conn.in_transaction and "\n".join(conn.iterdump()) == before
            conn.trigger = None
            migrations.verify_schema(conn, required_version=2)
            assert not AGENT_TABLES & migrations.table_names(conn)
        finally:
            conn.close()


@pytest.mark.parametrize("mutation", ["checksum", "gap", "future", "missing_table", "wrong_index", "missing_trigger", "report", "report_bool", "report_time"])
def test_003_structural_or_coverage_drift_refuses_read_only(tmp_path, mutation):
    with closing(sqlite3.connect(tmp_path / "drift.db")) as conn, conn:
        phase3(conn)
        if mutation == "checksum": conn.execute("UPDATE schema_migrations SET checksum='wrong' WHERE version=3")
        elif mutation == "gap": conn.execute("DELETE FROM schema_migrations WHERE version=2")
        elif mutation == "future": conn.execute("INSERT INTO schema_migrations VALUES(4,'future',100)")
        elif mutation == "missing_table": conn.execute("DROP TABLE agent_steps")
        elif mutation == "wrong_index":
            conn.execute("DROP INDEX idx_agent_runs_state")
            conn.execute("CREATE INDEX idx_agent_runs_state ON agent_runs(id)")
        elif mutation == "missing_trigger": conn.execute("DROP TRIGGER rule_candidates_body_immutable")
        elif mutation == "report": conn.execute("DELETE FROM runtime_meta WHERE key='migration_003_report'")
        else:
            raw = json.loads(conn.execute("SELECT value_json FROM runtime_meta WHERE key='migration_003_report'").fetchone()[0])
            raw["phase003"]["historicalRunsBackfilled" if mutation == "report_bool" else "coverageStart"] = 0 if mutation == "report_bool" else "synthetic-invalid-time"
            conn.execute("UPDATE runtime_meta SET value_json=? WHERE key='migration_003_report'", (json.dumps(raw),))
        conn.commit(); before = "\n".join(conn.iterdump())
        with pytest.raises(migrations.MigrationError): migrations.verify_schema(conn, required_version=3)
        assert "\n".join(conn.iterdump()) == before


@pytest.mark.parametrize("field", ["id", "run_id", "soup_id", "base_rule_version", "candidate_json", "candidate_digest", "regression_json", "created_at"])
def test_candidate_body_is_immutable_but_later_review_metadata_is_not(tmp_path, field):
    with closing(sqlite3.connect(tmp_path / "candidate.db")) as conn, conn:
        phase3(conn); _, _, _, candidate, _ = identities(conn)
        before = "\n".join(conn.iterdump())
        value = 101 if field == "created_at" else "b" * 64 if field == "candidate_digest" else "changed"
        with pytest.raises(sqlite3.IntegrityError): conn.execute(f"UPDATE rule_candidates SET {field}=? WHERE id=?", (value, candidate))
        assert "\n".join(conn.iterdump()) == before
        conn.execute("UPDATE rule_candidates SET status='rejected',reviewed_at=101 WHERE id=?", (candidate,))
        assert conn.execute("SELECT status FROM rule_candidates").fetchone()[0] == "rejected"


def test_candidate_delete_and_run_or_step_identity_rewrite_are_refused(tmp_path):
    with closing(sqlite3.connect(tmp_path / "identities.db")) as conn, conn:
        phase3(conn); _, run, _, candidate, operation = identities(conn)
        for sql, args in (("DELETE FROM rule_candidates WHERE id=?", (candidate,)),
            ("UPDATE agent_runs SET manifest_json='changed' WHERE id=?", (run,)),
            ("UPDATE agent_steps SET action_json='changed' WHERE operation_key=?", (operation,))):
            with pytest.raises(sqlite3.IntegrityError): conn.execute(sql, args)
        conn.execute("UPDATE agent_steps SET result_json='{}',state='completed' WHERE operation_key=?", (operation,))
        with pytest.raises(sqlite3.IntegrityError): conn.execute("UPDATE agent_steps SET result_json='changed' WHERE operation_key=?", (operation,))
        with pytest.raises(sqlite3.IntegrityError): conn.execute("DELETE FROM agent_steps WHERE operation_key=?", (operation,))


@pytest.mark.parametrize("sql", ["UPDATE agent_runs SET row_version=-1", "UPDATE agent_runs SET row_version=1.5",
    "UPDATE agent_runs SET state='published'", "UPDATE agent_runs SET feedback_id='foreign'",
    "UPDATE agent_steps SET seq=-1", "UPDATE agent_steps SET state='unknown'",
    "UPDATE rule_candidates SET status='unknown'", "UPDATE rule_candidates SET published_release_id='foreign'"])
def test_real_foreign_keys_and_state_counter_constraints_reject_invalid_rows(tmp_path, sql):
    with closing(sqlite3.connect(tmp_path / "constraints.db")) as conn, conn:
        phase3(conn); identities(conn)
        with pytest.raises(sqlite3.IntegrityError): conn.execute(sql)


@pytest.mark.parametrize("sequence", [-1, 1.5])
def test_sequence_constraint_is_proven_on_insert_not_preempted_by_identity_trigger(tmp_path, sequence):
    with closing(sqlite3.connect(tmp_path / "sequence.db")) as conn, conn:
        phase3(conn); _, run, _, _, _ = identities(conn)
        with pytest.raises(sqlite3.IntegrityError):
            conn.execute("INSERT INTO agent_steps(run_id,seq,operation_key,action_json,state,created_at) VALUES (?,?,?,'{}','planned',100)",
                (run, sequence, str(uuid4())))
        conn.execute("INSERT INTO agent_steps(run_id,seq,operation_key,action_json,state,created_at) VALUES (?,1,?,'{}','planned',100)",
            (run, str(uuid4())))
        assert conn.execute("SELECT count(*) FROM agent_steps").fetchone()[0] == 2


def test_foreign_feedback_and_run_constraints_are_proven_on_inserts(tmp_path):
    with closing(sqlite3.connect(tmp_path / "foreign.db")) as conn, conn:
        phase3(conn); identities(conn)
        with pytest.raises(sqlite3.IntegrityError):
            conn.execute("INSERT INTO agent_runs(id,request_id,feedback_id,state,checkpoint_json,manifest_json,created_at,updated_at) VALUES (?,?,'foreign','queued','{}','{}',100,100)",
                (str(uuid4()), str(uuid4())))
        with pytest.raises(sqlite3.IntegrityError):
            conn.execute("INSERT INTO agent_steps(run_id,seq,operation_key,action_json,state,created_at) VALUES ('foreign',0,?,'{}','planned',100)",
                (str(uuid4()),))


def test_explicit_003_rehearsal_cli_retains_source_and_default001(tmp_path, capsys):
    from .test_migration_cli import invoke, source_directory, source_hashes
    source = source_directory(tmp_path)
    before = source_hashes(source)
    target = tmp_path / "target"
    assert invoke(source, tmp_path, "--target-version", "3") == 0
    output = json.loads(capsys.readouterr().out)
    assert output["migrationVersion"] == 3 and output["productionReady"] is False
    assert source_hashes(source) == before
    with closing(sqlite3.connect(target / "sessions.db")) as conn, conn: migrations.verify_schema(conn, required_version=3)


@pytest.mark.parametrize("entry", ["verify", "rerun"])
def test_003_existing_orphan_cannot_reuse_success_report(tmp_path, entry):
    with closing(sqlite3.connect(tmp_path / "orphan.db")) as conn, conn:
        phase3(conn); conn.commit()
        conn.execute("PRAGMA foreign_keys=OFF")
        conn.execute("INSERT INTO agent_runs(id,request_id,feedback_id,state,checkpoint_json,manifest_json,created_at,updated_at) VALUES (?,?,'missing-feedback','queued','{}','{}',100,100)",
            (str(uuid4()), str(uuid4())))
        conn.commit(); before = "\n".join(conn.iterdump())
        assert conn.execute("PRAGMA foreign_key_check").fetchone() is not None
        with pytest.raises(migrations.MigrationError):
            migrations.verify_schema(conn, required_version=3) if entry == "verify" else phase3(conn)
        assert "\n".join(conn.iterdump()) == before
