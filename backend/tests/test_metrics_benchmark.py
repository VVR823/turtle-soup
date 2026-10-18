"""Measured declared-synthetic SQL volume, not real traffic/model-quality proof."""
from importlib import import_module
import json
import math

import pytest


def benchmark():
    try:
        return import_module('app.scripts.benchmark_metrics')
    except ModuleNotFoundError as error:
        if error.name == 'app.scripts.benchmark_metrics':
            pytest.fail('TS16 actual metrics benchmark is not implemented')
        raise


def test_metrics_nearest_rank_is_discrete_and_never_fabricates_empty_or_nonfinite_samples():
    measure = benchmark()
    assert measure.nearest_rank(list(range(1, 21)), 0.95) == 19
    assert measure.nearest_rank(list(range(20, 0, -1)), 0.5) == 10
    for samples in ([], [math.nan], [math.inf], [False], [-1]):
        with pytest.raises(ValueError):
            measure.nearest_rank(samples, 0.95)


def test_schema_four_benchmark_expected_summary_explicitly_reports_missing_observation_schema(tmp_path):
    measure = benchmark()
    from app.schemas import Soup
    soups = [Soup(id=f'benchmark-{index}', title='Synthetic', surface='Synthetic surface',
        bottom='Synthetic truth', checkpoints=[{'key': 'fact', 'answer': True}],
        confusionPoints=[{'q': 'Synthetic?', 'a': '是'}]) for index in range(4)]
    rows, expected, _ = measure._seed(tmp_path / 'sessions.db', soups)
    assert rows == {'sessions': 200, 'turns': 1000, 'auditEvents': 5000}
    assert expected['postPublicationRegression'] == {
        'state': 'unknown', 'observedRuns': None, 'failedRuns': None, 'reason': 'schema_5_required'}


def test_actual_200_1000_5000_benchmark_reports_all_twenty_samples_and_real_plans():
    measure = benchmark()
    report = measure.measure_metrics()
    assert report['status'] == 'complete' and report['evidenceKind'] == 'declared_synthetic_benchmark'
    assert report['inputRows'] == {'sessions': 200, 'turns': 1000, 'auditEvents': 5000}
    assert report['warmups'] == 3 and report['samples'] == 20
    counts = report['expectedSummary']['counts']
    assert counts['sessionsCreated'] == 50 and counts['successfulChargedTurns'] == 150 and counts['httpAttempts'] == 1000
    assert report['actualSummary'] == report['expectedSummary']
    assert report['aggregateStatementCount'] == 2
    for name in ('reader', 'sqlBatchBeforeIndexes', 'sqlBatchAfterIndexes'):
        values = report[name]['samplesMs']
        assert len(values) == 20 and all(math.isfinite(value) and value >= 0 for value in values)
        assert report[name]['p50Ms'] == measure.nearest_rank(values, 0.5)
        assert report[name]['p95Ms'] == measure.nearest_rank(values, 0.95)
    assert report['reader']['comparisonKind'] == 'end_to_end_reader'
    assert report['sqlBatchBeforeIndexes']['comparisonKind'] == 'same_statement_batch_not_reader'
    assert report['sqlBatchAfterIndexes']['comparisonKind'] == 'same_statement_batch_not_reader'
    plans = '\n'.join(report['plansAfterIndexes'])
    for index in ('idx_sessions_created', 'idx_turns_completed', 'idx_feedback_created', 'idx_agent_runs_created', 'idx_rule_candidates_created'):
        assert index in plans
    assert all(index not in '\n'.join(report['plansBeforeIndexes']) for index in
        ('idx_sessions_created', 'idx_turns_completed', 'idx_feedback_created', 'idx_agent_runs_created', 'idx_rule_candidates_created'))
    assert report['resources']['pythonAllocatedPeakBytes'] >= 0
    assert report['resources']['cpuMilliseconds'] >= 0 and report['resources']['dbFileBytes'] > 0
    assert 'rss' not in json.dumps(report['resources']).lower()
    assert report['cleanupConfirmed'] is True


def test_failed_real_reader_never_gets_success_quantiles_or_raw_diagnostics(monkeypatch):
    measure = benchmark()
    from app import metrics
    from app.metrics_contracts import MetricsError
    def unavailable(*args, **kwargs):
        raise MetricsError('metrics_busy', 503)
    monkeypatch.setattr(metrics, 'query_metrics', unavailable)
    report = measure.measure_metrics(warmups=0, samples=1)
    assert report['status'] == 'failed' and report['failureCode'] == 'metrics_busy'
    assert report['cleanupConfirmed'] is True and 'reader' not in report
    assert 'p50Ms' not in json.dumps(report) and 'p95Ms' not in json.dumps(report)


def test_benchmark_includes_unknown_traffic_and_a_post_coverage_window():
    report = benchmark().measure_metrics(warmups=0, samples=1)
    assert report['status'] == 'complete'
    assert report['inputRows'] == {'sessions': 200, 'turns': 1000, 'auditEvents': 5000}
    assert report['actualSummary']['excluded']['unknown']['httpAttempts'] == 1000
    assert report['actualSummary']['counts']['httpAttempts'] == 1000
    assert report['coverage']['windowStartsBeforeAudit'] is False
    assert report['coverage']['windowStartsBeforeAgent'] is False
    assert report['query']['start'] >= max(report['coverage']['auditStartedAt'], report['coverage']['agentStartedAt'])


def test_reader_profile_consumes_actual_full_serialized_pages(monkeypatch):
    measure = benchmark()
    from app.metrics_contracts import MetricsPage
    real_profile, real_json = measure._profile, MetricsPage.model_dump_json
    reader_active = [False]
    serialized = []

    def profile(call, warmups, samples, kind):
        reader_active[0] = kind == 'end_to_end_reader'
        try:
            return real_profile(call, warmups, samples, kind)
        finally:
            reader_active[0] = False

    def full_json(self, *args, **kwargs):
        raw = real_json(self, *args, **kwargs)
        if reader_active[0]:
            serialized.append(raw)
        return raw

    monkeypatch.setattr(measure, '_profile', profile)
    monkeypatch.setattr(MetricsPage, 'model_dump_json', full_json)
    report = measure.measure_metrics(warmups=0, samples=1)
    assert report['status'] == 'complete'
    assert len(serialized) == 1  # Real serialized body inside timed reader, not only its summary.
    actual = MetricsPage.model_validate_json(serialized[0])
    assert actual.summary.model_dump(mode='json') == report['expectedSummary']
    assert actual.query.model_dump(mode='json') == report['query']
    assert report['reader']['serializedBytes'] == [len(serialized[0].encode('utf-8'))]
    assert report['reader']['serializationIncluded'] is True


def test_benchmark_clock_does_not_seed_before_actual_coverage(monkeypatch):
    measure = benchmark()
    real_reader = measure.metrics.query_metrics
    pages = []

    def observed(*args, **kwargs):
        page = real_reader(*args, **kwargs)
        pages.append(page)
        return page

    monkeypatch.setattr(measure.metrics, 'query_metrics', observed)
    report = measure.measure_metrics(warmups=0, samples=1)
    assert report['status'] == 'complete' and pages
    for page in pages:
        assert page.coverage.windowStartsBeforeAudit is False
        assert page.coverage.windowStartsBeforeAgent is False
