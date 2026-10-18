"""Declared synthetic statistical volume, never user/model-quality evidence."""
from contextlib import closing
import json
import math
import platform
import sqlite3
import time
from uuid import uuid4

from app import baselines, db
from app.audit_events import AuditEvent, AttemptDetails
from app.metrics import query_metrics
from app.metrics_contracts import MetricsPage
from app.post_publication_contracts import PostPublicationPlan, checked_observation, validate_result
from app.scripts.benchmark_metrics import nearest_rank
from .test_post_publication_metrics import cohort, observation_window
from .test_rule_snapshots import rule_storage


def test_mixed_observation_scale_measures_twenty_full_reader_samples(rule_storage, monkeypatch):
    from app import metrics, post_publication_metrics as module
    _, originals = cohort(rule_storage)
    with closing(db._connect()) as conn, conn:
        original_rows = {row['id']: dict(row) for row in conn.execute('SELECT * FROM post_publication_runs')}
        rows = []
        for index in range(200):
            original = originals[index % 4]
            row = dict(original_rows[original.plan.runId])
            plan = checked_observation(PostPublicationPlan, original.plan.model_copy(update={
                'runId': str(uuid4()), 'operationKey': str(uuid4()),
                'trafficClass': 'unknown' if index % 5 == 0 else 'test'}))
            row.update(id=plan.runId, operation_key=plan.operationKey, traffic_class=plan.trafficClass,
                payload_digest=plan.payloadDigest, plan_digest=plan.planDigest,
                plan_json=baselines.canonical_json(plan.model_dump(mode='json')))
            if original.result is not None:
                result = validate_result(plan, original.result.model_copy(update={
                    'runId': plan.runId, 'planDigest': plan.planDigest}))
                row.update(result_json=baselines.canonical_json(result.model_dump(mode='json')),
                    result_digest=baselines.digest(result.model_dump(mode='json')))
            rows.append(row)
        columns = tuple(rows[0])
        conn.executemany('INSERT INTO post_publication_runs (' + ','.join(columns)
            + ') VALUES (' + ','.join('?' for _ in columns) + ')',
            [tuple(row[name] for name in columns) for row in rows])
        attempts = []
        for index in range(5000):
            event = AuditEvent(eventId=str(uuid4()), eventType='http_attempt', createdAt=time.time(),
                details=AttemptDetails(method='GET', routeTemplate='/health', statusCode=200,
                    durationMs=1.0, outcome='success', responseStarted=True, disconnected=False,
                    trafficClass='test'))
            attempts.append((event.eventId, baselines.canonical_json(event.model_dump(mode='json')), event.createdAt))
        conn.executemany("INSERT INTO audit_events(id,event_type,details_json,created_at) VALUES(?,'http_attempt',?,?)", attempts)
        assert conn.execute('SELECT count(*) FROM post_publication_runs').fetchone()[0] == 204
    # These 200 extra rows are statistical copies with unique identities, not
    # 200 executed observations. All origins remain synthetic test/unknown.
    query = observation_window()
    monkeypatch.setattr(module.time, 'time', lambda: originals[-1].plan.deadlineAt + 1)
    original_source, original_execute = module._source, metrics._DeadlineConnection.execute
    sources, queries, plans = [], [], []
    def source(*values):
        sources.append(1)
        return original_source(*values)
    def execute(connection, sql, parameters=()):
        if sql == module._SUMMARY_SQL:
            queries.append(1)
            if not plans:
                plans.extend(str(tuple(row)) for row in original_execute(
                    connection, 'EXPLAIN QUERY PLAN ' + sql, parameters).fetchall())
        return original_execute(connection, sql, parameters)
    monkeypatch.setattr(module, '_source', source)
    monkeypatch.setattr(metrics._DeadlineConnection, 'execute', execute)
    samples, sizes = [], []
    for index in range(23):
        started = time.perf_counter()
        page = query_metrics(rule_storage, query)
        encoded = page.model_dump_json()
        decoded = MetricsPage.model_validate_json(encoded)
        assert decoded == page
        value = decoded.summary.postPublicationRegression
        assert value.state == 'observed' and value.observedRuns == value.plannedCases == 0
        assert value.excluded.test.model_dump() == dict(observedRuns=164, passedRuns=41, failedRuns=41,
            incompleteRuns=41, pendingRuns=41, pendingExpiredRuns=41,
            plannedCases=164, attemptedCases=123, passedCases=41, counterexampleCases=41,
            errorCases=0, unsupportedCases=41, notAttemptedCases=41)
        assert value.excluded.unknown.observedRuns == 40
        assert (value.excluded.unknown.passedRuns, value.excluded.unknown.failedRuns,
            value.excluded.unknown.incompleteRuns, value.excluded.unknown.pendingRuns) == (10, 10, 10, 10)
        assert value.excluded.unknown.plannedCases == 40 and value.excluded.unknown.attemptedCases == 30
        assert value.excluded.unknown.notAttemptedCases == 10 and value.excluded.synthetic.observedRuns == 0
        assert value.excluded.unknown.pendingExpiredRuns == 10
        if index >= 3:
            samples.append((time.perf_counter() - started) * 1000)
            sizes.append(len(encoded.encode('utf-8')))
    assert len(sources) == len(queries) == 23  # One source/batch per read, not 204 per read.
    assert any('idx_post_publication_started' in plan for plan in plans)
    assert len(samples) == 20 and all(math.isfinite(value) and 0 <= value < 3000 for value in samples)
    print(json.dumps(dict(evidenceKind='declared_synthetic_benchmark',
        limitations=['200 statistical copies, not additional executions', 'No real users or model accuracy',
            'Local end-to-end latency is not a production SLA'], python=platform.python_version(),
        sqlite=sqlite3.sqlite_version, observationRows=204, additionalHttpAttempts=5000,
        warmups=3, samplesMs=samples, p50Ms=nearest_rank(samples, 0.5), p95Ms=nearest_rank(samples, 0.95),
        serializedBytes=sizes, serializationIncluded=True, sourceVerificationsPerRead=1,
        observationStatementsPerRead=1, explain=plans), ensure_ascii=False))
