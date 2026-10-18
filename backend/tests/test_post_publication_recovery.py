"""Synthetic schema-five conservation, never production restore authority.

Break caught: a latest backup cannot restore, drops pending or failed records,
changes immutable publication evidence, or makes restored statistics unknown.
"""
import asyncio
from contextlib import closing
import sqlite3

from app import db, migrations
from app.config import Settings
from app.metrics import query_metrics
from app.post_publication_regression import PostPublicationRegression
from app.runtime import Runtime, runtime_context
from app.scripts.snapshot_recovery import backup, restore
from app.testing import FakeModel
from .test_post_publication_metrics import cohort, observation_window
from .test_release_recovery import hashes
from .test_release_recovery_business import business_rows
from .test_rule_snapshots import rule_storage


def observation_rows(directory):
    with closing(sqlite3.connect(directory / 'sessions.db')) as conn, conn:
        conn.row_factory = sqlite3.Row
        return [dict(row) for row in conn.execute(
            'SELECT * FROM post_publication_runs ORDER BY rowid')]


def test_restore_preserves_all_four_states_birth_evidence_and_same_reader(
        rule_storage, tmp_path_factory, monkeypatch):
    _, records = cohort(rule_storage)
    query = observation_window()
    import app.metrics as metrics
    monkeypatch.setattr(metrics.time, 'time', lambda: records[-1].plan.deadlineAt + 1)
    source = rule_storage.settings.DATA_DIR
    before = hashes(source)
    business = business_rows(source)
    rows = observation_rows(source)
    assert [row['state'] for row in rows] == ['passed', 'failed', 'incomplete', 'running']
    expected = dict(observedRuns=4, passedRuns=1, failedRuns=1, incompleteRuns=1,
        pendingRuns=1, pendingExpiredRuns=1, plannedCases=4, attemptedCases=3,
        passedCases=1, counterexampleCases=1, errorCases=0, unsupportedCases=1,
        notAttemptedCases=1)
    assert query_metrics(rule_storage, query).summary.postPublicationRegression.excluded.test.model_dump() == expected
    # Output is a separate test-owned root, never a child of runtime input.
    outputs = tmp_path_factory.mktemp('observation-recovery')
    artifact, restored = outputs / 'artifact', outputs / 'restored'
    receipt = backup(str(source), str(artifact), str(outputs / 'backup.json'))
    assert receipt['migrationVersion'] == 5 and receipt['productionReady'] is False
    archive_hashes = hashes(artifact)
    result = restore(str(artifact), str(restored), str(outputs / 'restore.json'))
    assert result['migrationVersion'] == 5 and result['quiescenceVerified'] is False
    assert hashes(source) == before and hashes(artifact) == archive_hashes
    assert observation_rows(restored) == rows
    assert business_rows(restored) == business
    active = Runtime(Settings.for_test(restored), model=FakeModel(), soups=rule_storage.soups,
        repair_corpus=rule_storage.repair_corpus)
    try:
        with runtime_context(active):
            with closing(db._connect()) as conn, conn:
                migrations.verify_schema(conn, required_version=5)
            service = PostPublicationRegression(active)
            for original in records:
                assert service.store.get(original.plan.operationKey) == original
            summary = query_metrics(active, query).summary.postPublicationRegression
            assert summary.state == 'observed' and summary.observedRuns == summary.failedRuns == 0
            assert summary.excluded.test.model_dump() == expected
            assert observation_rows(restored) == rows  # Reads never execute pending work.
    finally:
        asyncio.run(active.aclose())
