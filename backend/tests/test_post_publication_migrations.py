"""Explicit005 only, on newly owned synthetic databases, never original data."""
from contextlib import closing
import sqlite3

import pytest

from app import migrations
from .test_agent_migrations import identities
from .test_metrics_migrations import dump
from .test_migration_cli import invoke, source_directory, source_hashes
from .test_migrations import puzzle


def test_005_registered_report_and_full_prefix(tmp_path):
    with closing(sqlite3.connect(tmp_path / 'five.db')) as conn, conn:
        report = migrations.migrate(conn, [puzzle()], target_version=5)
        assert report['migrationVersion'] == 5
        phase = report['phase005']
        assert set(phase) == {'checksum', 'coverageStart', 'noHistoricalBackfill'}
        assert phase['checksum'] == migrations.CHECKSUM_005
        assert type(phase['coverageStart']) is float and phase['coverageStart'] >= 0
        assert phase['noHistoricalBackfill'] is True
        assert conn.execute('SELECT count(*) FROM post_publication_runs').fetchone()[0] == 0
        assert [r[0] for r in conn.execute('SELECT version FROM schema_migrations ORDER BY version')] == [1, 2, 3, 4, 5]
        for version in range(1, 6):
            migrations.verify_schema(conn, required_version=version)
        assert conn.execute('PRAGMA foreign_key_check').fetchall() == []
        assert conn.execute('PRAGMA integrity_check').fetchone()[0] == 'ok'


def test_default_still_001_and_no_observation_table(tmp_path):
    with closing(sqlite3.connect(tmp_path / 'default.db')) as conn, conn:
        assert migrations.migrate(conn, [puzzle()])['migrationVersion'] == 1
        assert 'post_publication_runs' not in migrations.table_names(conn)


@pytest.mark.parametrize('version', [1, 2, 3, 4])
def test_005_requirement_refuses_old_database_without_writes(tmp_path, version):
    with closing(sqlite3.connect(tmp_path / 'old.db')) as conn, conn:
        migrations.migrate(conn, [puzzle()], target_version=version)
        before, changes = dump(conn), conn.total_changes
        with pytest.raises(migrations.MigrationRequired):
            migrations.verify_schema(conn, required_version=5)
        assert (dump(conn), conn.total_changes) == (before, changes)


def test_005_rerun_and_lower_targets_preserve_original_reports(tmp_path):
    with closing(sqlite3.connect(tmp_path / 'history.db')) as conn, conn:
        prior = {v: migrations.migrate(conn, [puzzle()], target_version=v) for v in range(1, 5)}
        old_sql = dict(conn.execute('SELECT name,sql FROM sqlite_master WHERE sql IS NOT NULL'))
        new_report = migrations.migrate(conn, [puzzle()], target_version=5)
        before, changes = dump(conn), conn.total_changes
        for version, report in {**prior, 5: new_report}.items():
            assert migrations.migrate(conn, [puzzle()], target_version=version) == report
        assert (dump(conn), conn.total_changes) == (before, changes)
        for name, sql in old_sql.items():
            assert conn.execute('SELECT sql FROM sqlite_master WHERE name=?', (name,)).fetchone()[0] == sql


@pytest.mark.parametrize('fault', ['table', 'index', 'report', 'ledger', 'verify', 'integrity', 'commit'])
def test_005_fault_rolls_back_only_005(tmp_path, fault):
    class FaultConnection(sqlite3.Connection):
        armed = False
        phase_started = False
        hits = 0

        def execute(self, sql, parameters=()):
            if self.armed and sql == 'BEGIN IMMEDIATE':
                self.phase_started = True
            matches = (
                fault == 'table' and sql.startswith('CREATE TABLE post_publication_runs ')
                or fault == 'index' and sql.startswith('CREATE INDEX idx_post_publication_started ')
                or fault == 'report' and 'INSERT INTO runtime_meta' in sql and "'migration_005_report'" in sql
                or fault == 'ledger' and 'INSERT INTO schema_migrations' in sql
                or fault == 'verify' and sql.startswith('SELECT version,checksum FROM schema_migrations')
                or fault == 'integrity' and sql == 'PRAGMA integrity_check'
            )
            if self.armed and self.phase_started and matches:
                self.hits += 1
                raise sqlite3.OperationalError('synthetic005 fault')
            return super().execute(sql, parameters)

        def commit(self):
            if self.armed and self.phase_started and fault == 'commit':
                self.hits += 1
                raise sqlite3.OperationalError('synthetic005 commit fault')
            return super().commit()

    with closing(sqlite3.connect(tmp_path / 'fault.db', factory=FaultConnection)) as conn, conn:
        migrations.migrate(conn, [puzzle()], target_version=4)
        before = dump(conn)
        conn.armed = True
        with pytest.raises(migrations.MigrationError):
            migrations.migrate(conn, [puzzle()], target_version=5)
        assert conn.hits == 1, 'Fault must actually hit005, not fail before it'
        assert dump(conn) == before and not conn.in_transaction
        conn.armed = False
        migrations.verify_schema(conn, required_version=4)


@pytest.mark.parametrize('damage', ['index', 'trigger', 'report', 'ledger'])
def test_005_drift_is_rejected_even_for_old_required_version(tmp_path, damage):
    with closing(sqlite3.connect(tmp_path / 'drift.db')) as conn, conn:
        migrations.migrate(conn, [puzzle()], target_version=5)
        if damage == 'index':
            conn.execute('DROP INDEX idx_post_publication_started')
            conn.execute('CREATE INDEX idx_post_publication_started ON post_publication_runs(finished_at,id)')
        elif damage == 'trigger':
            conn.execute('DROP TRIGGER post_publication_runs_no_delete')
        elif damage == 'report':
            conn.execute("UPDATE runtime_meta SET value_json='{}' WHERE key='migration_005_report'")
        else:
            conn.execute("UPDATE schema_migrations SET checksum='bad' WHERE version=5")
        conn.commit()
        before = dump(conn)
        with pytest.raises(migrations.MigrationError):
            migrations.verify_schema(conn, required_version=1)
        assert dump(conn) == before


@pytest.mark.parametrize('dry_run', [False, True])
def test_cli_explicit005_uses_only_owned_output_and_preserves_input(tmp_path, dry_run):
    source = source_directory(tmp_path)
    before = source_hashes(source)
    extra = ('--dry-run',) if dry_run else ()
    assert invoke(source, tmp_path, '--target-version', '5', *extra) == 0
    assert source_hashes(source) == before
    if dry_run:
        assert not (tmp_path / 'target').exists()
    else:
        with closing(sqlite3.connect(tmp_path / 'target' / 'sessions.db')) as conn, conn:
            migrations.verify_schema(conn, required_version=5)
            assert conn.execute('SELECT count(*) FROM post_publication_runs').fetchone()[0] == 0


def test_unknown006_remains_rejected_without_writes(tmp_path):
    with closing(sqlite3.connect(tmp_path / 'six.db')) as conn, conn:
        migrations.migrate(conn, [puzzle()], target_version=5)
        before = dump(conn)
        for entry, args in [(migrations.migrate, {'soups': [puzzle()], 'target_version': 6}),
            (migrations.verify_schema, {'required_version': 6})]:
            with pytest.raises(migrations.MigrationError):
                entry(conn, **args)
        assert dump(conn) == before


def test_005_requires_non_null_run_identity_at_sql_boundary(tmp_path):
    # SQL-only synthetic storage fixture: deliberately NOT publication proof.
    with closing(sqlite3.connect(tmp_path / 'identity.db')) as conn, conn:
        report = migrations.migrate(conn, [puzzle()], target_version=5)
        _, _, operation, candidate, publication = identities(conn)
        conn.commit()
        puzzle_version = conn.execute('SELECT id FROM puzzle_versions LIMIT 1').fetchone()[0]
        rule_version = conn.execute('SELECT id FROM rule_releases LIMIT 1').fetchone()[0]
        started = report['phase005']['coverageStart']
        with pytest.raises(sqlite3.IntegrityError):
            conn.execute('INSERT INTO post_publication_runs '
                '(id,operation_key,payload_digest,candidate_id,publication_operation_key,soup_id,puzzle_version,'
                'published_rule_version,published_at,started_at,deadline_at,traffic_class,evidence_kind,'
                'plan_json,plan_digest,planned_case_count,state) VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)',
                (None, operation, 'a' * 64, candidate, publication, 'synthetic', puzzle_version,
                 rule_version, started, started, started + 5, 'test', 'synthetic_fixture', '{}', 'b' * 64, 1, 'running'))
