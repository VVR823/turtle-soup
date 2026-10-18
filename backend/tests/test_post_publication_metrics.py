"""Birth-verified synthetic observations, never real-user/model quality evidence."""
from contextlib import closing
from uuid import uuid4
import time

import pytest

from app import baselines, db
from app.metrics import export_metrics, query_metrics
from app.metrics_contracts import MetricsQuery
from app.post_publication_regression import PostPublicationRegression
from .test_metrics_queries import metrics_runtime
from .test_post_publication_regression import published, unsupported_corpus
from .test_candidate_validation import scope
from .test_repair_corpus import frozen_corpus
from .test_rule_snapshots import rule_storage


def observation_window():
    with closing(db._connect()) as conn, conn:
        report = baselines.strict_json(conn.execute("SELECT value_json FROM runtime_meta WHERE key='migration_005_report'").fetchone()[0])
    return MetricsQuery(start=report['phase005']['coverageStart'], end=time.time() + 30)


def cohort(active):
    request = published(active)
    original = active.repair_corpus
    service = PostPublicationRegression(active)
    passed = service.run(request)
    active.repair_corpus = frozen_corpus(scope(), labels=('不是',))
    failed = service.run(request | {'operationKey': str(uuid4())})
    active.repair_corpus = unsupported_corpus(active)
    incomplete = service.run(request | {'operationKey': str(uuid4())})
    active.repair_corpus = original
    now = time.time()
    # An admitted, unexecuted fixture is intentionally pending. Do not invent
    # results or describe these tagged test records as real observations.
    pending_plan = passed.plan.model_copy(update={'runId': str(uuid4()), 'operationKey': str(uuid4()),
        'startedAt': now, 'deadlineAt': now + 5})
    pending, created = service.store.reserve(pending_plan)
    assert created and (passed.state, failed.state, incomplete.state, pending.state) == ('passed', 'failed', 'incomplete', 'running')
    return request, (passed, failed, incomplete, pending)


def test_protocol_three_counts_complete_cohort_not_only_successful_results(rule_storage, monkeypatch):
    _, records = cohort(rule_storage)
    query = observation_window()
    import app.metrics as module
    monkeypatch.setattr(module.time, 'time', lambda: records[-1].plan.deadlineAt + 1)
    page = query_metrics(rule_storage, query)
    assert page.schemaVersion == 3
    summary = page.summary.postPublicationRegression
    assert summary.state == 'observed' and summary.observedRuns == summary.failedRuns == 0
    excluded = summary.excluded.test
    assert excluded.model_dump() == dict(observedRuns=4, passedRuns=1, failedRuns=1, incompleteRuns=1,
        pendingRuns=1, pendingExpiredRuns=1, plannedCases=4, attemptedCases=3, passedCases=1,
        counterexampleCases=1, errorCases=0, unsupportedCases=1, notAttemptedCases=1)
    assert summary.historicalBackfill is False and summary.windowStartsBeforeCoverage is False
    assert summary.sourceCoverageStart == query.start


def test_filters_apply_actual_published_version_and_keep_rollback_history(rule_storage):
    from app.candidate_review import CandidateReviewStore
    from app.candidate_review_contracts import CandidateRollback
    request, records = cohort(rule_storage)
    query = observation_window()
    with closing(db._connect()) as conn, conn:
        release = conn.execute('SELECT parent_id FROM rule_releases WHERE id=?', (request['publishedRuleVersion'],)).fetchone()[0]
    CandidateReviewStore(rule_storage).rollback(CandidateRollback(operationKey=str(uuid4()),
        expectedRuleVersion=request['publishedRuleVersion'], expectedPointerVersion=1,
        targetRuleVersion=release, reason='Synthetic metadata-only rollback'))
    target = query_metrics(rule_storage, query.model_copy(update={'ruleVersion': request['publishedRuleVersion']}))
    old = query_metrics(rule_storage, query.model_copy(update={'ruleVersion': release}))
    assert target.summary.postPublicationRegression.excluded.test.observedRuns == 4
    assert old.summary.postPublicationRegression.excluded.test.observedRuns == 0
    assert target.summary.postPublicationRegression.excluded.test.failedRuns == 1


def test_half_open_window_belongs_to_plan_start_not_later_finish(rule_storage):
    request = published(rule_storage)
    record = PostPublicationRegression(rule_storage).run(request)
    before_finish = MetricsQuery(start=record.plan.startedAt, end=record.result.finishedAt)
    page = query_metrics(rule_storage, before_finish)
    assert page.summary.postPublicationRegression.excluded.test.observedRuns == 1
    after_start = MetricsQuery(start=record.plan.startedAt + 0.000001, end=record.result.finishedAt + 1)
    assert query_metrics(rule_storage, after_start).summary.postPublicationRegression.excluded.test.observedRuns == 0


def test_pre_activation_window_is_partial_not_invented_history(rule_storage):
    cohort(rule_storage)
    query = observation_window()
    query = query.model_copy(update={'start': query.start - 1})
    summary = query_metrics(rule_storage, query).summary.postPublicationRegression
    assert summary.state == 'partial' and summary.windowStartsBeforeCoverage is True
    assert summary.historicalBackfill is False and summary.excluded.test.observedRuns == 4


def test_schema_four_reports_unknown_not_zero_and_does_not_migrate(metrics_runtime):
    page = query_metrics(metrics_runtime, MetricsQuery(start=1000.0, end=1100.0))
    value = page.summary.postPublicationRegression
    assert value.state == 'unknown' and value.observedRuns is value.failedRuns is None
    assert value.reason == 'schema_5_required' and page.schemaVersion == 3
    with closing(db._connect()) as conn, conn:
        assert conn.execute("SELECT name FROM sqlite_master WHERE name='post_publication_runs'").fetchone() is None


def test_damaged_necessary_publication_source_does_not_become_zero_observations(rule_storage):
    cohort(rule_storage)
    query = observation_window()
    with closing(db._connect()) as conn, conn:
        conn.execute("DELETE FROM audit_events WHERE event_type='rule_published'")
    summary = query_metrics(rule_storage, query).summary.postPublicationRegression
    assert summary.state == 'unknown' and summary.reason == 'source_unavailable'
    assert summary.observedRuns is summary.failedRuns is None


def test_export_keeps_same_totals_without_private_observation_ids(rule_storage):
    _, records = cohort(rule_storage)
    query = observation_window()
    exported = export_metrics(rule_storage, query)
    assert exported.schemaVersion == 3 and exported.summary.postPublicationRegression.excluded.test.observedRuns == 4
    raw = exported.model_dump_json()
    for record in records:
        assert record.plan.runId not in raw and record.plan.operationKey not in raw and record.plan.candidateId not in raw
    assert '小明' not in raw and 'expectedLabel' not in raw and 'caseResults' not in raw


def test_birth_proof_reconstructs_from_operation_digest_without_private_context(rule_storage):
    from app.agents.contracts import checked_model
    from app.candidate_review_contracts import CandidateOperationReceipt
    from app.post_publication_source import PostPublicationSourceResolver
    request = published(rule_storage)
    record = PostPublicationRegression(rule_storage).run(request)
    key = record.plan.publicationOperationKey
    with closing(db._connect()) as conn, conn:
        operation = checked_model(CandidateOperationReceipt, conn.execute(
            'SELECT value_json FROM runtime_meta WHERE key=?', ('candidate_operation:' + key,)).fetchone()[0], max_bytes=65536)
        events = PostPublicationSourceResolver._audits(conn, key)
    digest = baselines.digest(dict(operation=operation.model_dump(mode='json'),
        audits={kind: event.model_dump(mode='json') for kind, event in events.items()},
        publishedAt=record.plan.publishedAt, privateSourceDigest=operation.state.contextDigest))
    # This is a compatibility characterization of the existing birth verifier,
    # not a new metrics implementation or fabricated source certificate.
    assert digest == record.plan.publicationProofDigest


def test_batch_source_verifier_matches_actual_birth_proof(rule_storage, monkeypatch):
    import app.post_publication_metrics as module
    request = published(rule_storage)
    record = PostPublicationRegression(rule_storage).run(request)
    original = module._source
    observed, errors = [], []
    def capture(*values):
        try:
            result = original(*values)
            observed.append(baselines.strict_json(result)['proof'])
            return result
        except Exception as error:
            errors.append(error)
            raise
    monkeypatch.setattr(module, '_source', capture)
    page = query_metrics(rule_storage, observation_window())
    # Only synthetic fixture diagnostics stay in test output, never the API.
    assert errors == [], [repr(error) for error in errors]
    assert observed == [record.plan.publicationProofDigest]
    assert page.summary.postPublicationRegression.excluded.test.observedRuns == 1


@pytest.mark.parametrize('damage', ['operation_missing', 'operation_noncanonical', 'operation_version',
    'rule_operation_missing', 'rule_operation_payload', 'candidate_time', 'candidate_status',
    'audit_duplicate', 'audit_projection', 'audit_bad_json'])
def test_corrupt_birth_metadata_is_unknown_even_when_rule_filter_would_hide_it(rule_storage, damage):
    request = published(rule_storage)
    record = PostPublicationRegression(rule_storage).run(request)
    key = record.plan.publicationOperationKey
    with closing(db._connect()) as conn, conn:
        if damage == 'operation_missing':
            conn.execute('DELETE FROM runtime_meta WHERE key=?', ('candidate_operation:' + key,))
        elif damage == 'operation_noncanonical':
            conn.execute("UPDATE runtime_meta SET value_json=value_json||' ' WHERE key=?", ('candidate_operation:' + key,))
        elif damage == 'operation_version':
            conn.execute('UPDATE runtime_meta SET row_version=1 WHERE key=?', ('candidate_operation:' + key,))
        elif damage == 'rule_operation_missing':
            conn.execute('DELETE FROM runtime_meta WHERE key=?', ('rule_operation:' + key,))
        elif damage == 'rule_operation_payload':
            conn.execute("UPDATE runtime_meta SET value_json=json_set(value_json,'$.payloadDigest',?) WHERE key=?",
                ('0' * 64, 'rule_operation:' + key))
        elif damage == 'candidate_time':
            conn.execute('UPDATE rule_candidates SET reviewed_at=reviewed_at+1 WHERE id=?', (record.plan.candidateId,))
        elif damage == 'candidate_status':
            conn.execute("UPDATE rule_candidates SET status='approved' WHERE id=?", (record.plan.candidateId,))
        elif damage == 'audit_duplicate':
            from app.agents.contracts import checked_model
            from app.audit_events import AuditEvent
            from app.audit_store import insert_business_event
            row = conn.execute("SELECT details_json FROM audit_events WHERE event_type='candidate_published'").fetchone()
            event = checked_model(AuditEvent, row[0]).model_copy(update={'eventId': str(uuid4())})
            conn.execute('BEGIN IMMEDIATE')
            insert_business_event(conn, event)
        elif damage == 'audit_projection':
            conn.execute("UPDATE audit_events SET created_at=created_at+1 WHERE event_type='rule_published'")
        elif damage == 'audit_bad_json':
            conn.execute("UPDATE audit_events SET details_json='invalid' WHERE event_type='candidate_published'")
        old = conn.execute('SELECT parent_id FROM rule_releases WHERE id=?', (request['publishedRuleVersion'],)).fetchone()[0]
    for query in (observation_window(), observation_window().model_copy(update={'ruleVersion': old})):
        value = query_metrics(rule_storage, query).summary.postPublicationRegression
        assert value.state == 'unknown' and value.reason == 'source_unavailable'
        assert value.observedRuns is value.failedRuns is None


def test_batch_uses_one_source_verification_for_four_plans_and_no_private_source_query(rule_storage, monkeypatch):
    import app.post_publication_metrics as module
    import app.metrics as metrics
    cohort(rule_storage)
    original_source, original_execute = module._source, metrics._DeadlineConnection.execute
    calls, statements = [], []
    def source(*values):
        calls.append(1)
        return original_source(*values)
    def execute(connection, sql, parameters=()):
        statements.append(sql)
        return original_execute(connection, sql, parameters)
    monkeypatch.setattr(module, '_source', source)
    monkeypatch.setattr(metrics._DeadlineConnection, 'execute', execute)
    value = query_metrics(rule_storage, observation_window()).summary.postPublicationRegression
    assert value.excluded.test.observedRuns == 4 and len(calls) == 1
    reads = [sql for sql in statements if 'observation_window AS MATERIALIZED' in sql]
    assert len(reads) == 1
    assert all(word not in reads[0] for word in ('candidate_json', 'regression_json', 'source_json', 'agent_steps', 'messages'))


def mixed_cohort(active):
    _, records = cohort(active)
    now = time.time()
    # A synthetic, explicitly unknown-tagged pending plan exercises exclusions;
    # it is not relabeled real traffic or a fabricated successful result.
    plan = records[-1].plan.model_copy(update={'runId': str(uuid4()), 'operationKey': str(uuid4()),
        'startedAt': now, 'deadlineAt': now + 5, 'trafficClass': 'unknown'})
    unknown, created = PostPublicationRegression(active).store.reserve(plan)
    assert created and unknown.state == 'running'
    return records, unknown


def test_mixed_test_unknown_traffic_keeps_complete_separate_denominators(rule_storage):
    mixed_cohort(rule_storage)
    value = query_metrics(rule_storage, observation_window()).summary.postPublicationRegression
    assert value.observedRuns == value.failedRuns == value.plannedCases == 0
    assert value.excluded.test.observedRuns == value.excluded.test.plannedCases == 4
    assert value.excluded.unknown.observedRuns == value.excluded.unknown.pendingRuns == 1
    assert value.excluded.unknown.notAttemptedCases == 1
    assert value.excluded.synthetic.observedRuns == 0


def test_bad_first_cohort_with_another_pending_cohort_is_unknown_not_reader_error(rule_storage):
    mixed_cohort(rule_storage)
    with closing(db._connect()) as conn, conn:
        conn.execute("DELETE FROM audit_events WHERE event_type='rule_published'")
    value = query_metrics(rule_storage, observation_window()).summary.postPublicationRegression
    assert value.state == 'unknown' and value.reason == 'source_unavailable'
    assert value.observedRuns is value.failedRuns is None


@pytest.mark.parametrize('damage', ['plan_hash', 'plan_json', 'result_hash', 'result_json',
    'finished_at', 'case_projection', 'pending_plan_hash'])
def test_corrupt_observation_row_is_unknown_with_original_schema_restored(rule_storage, damage):
    records, _ = mixed_cohort(rule_storage)
    row_id = records[-1].plan.runId if damage == 'pending_plan_hash' else records[0].plan.runId
    # Fault injection is restricted to this test-owned database. Restore the
    # exact immutable triggers before querying: schema drift must not mask the
    # separate record-integrity check, and production guards remain unchanged.
    with closing(db._connect()) as conn, conn:
        triggers = conn.execute("SELECT name,sql FROM sqlite_master WHERE type='trigger' "
            "AND tbl_name='post_publication_runs'").fetchall()
        assert len(triggers) == 3
        for trigger in triggers:
            conn.execute('DROP TRIGGER ' + trigger['name'])
        if damage in ('plan_hash', 'pending_plan_hash'):
            conn.execute('UPDATE post_publication_runs SET plan_digest=? WHERE id=?', ('0' * 64, row_id))
        elif damage == 'plan_json':
            conn.execute("UPDATE post_publication_runs SET plan_json=plan_json||' ' WHERE id=?", (row_id,))
        elif damage == 'result_hash':
            conn.execute('UPDATE post_publication_runs SET result_digest=? WHERE id=?', ('0' * 64, row_id))
        elif damage == 'result_json':
            conn.execute("UPDATE post_publication_runs SET result_json=result_json||' ' WHERE id=?", (row_id,))
        elif damage == 'finished_at':
            conn.execute('UPDATE post_publication_runs SET finished_at=finished_at-0.001 WHERE id=?', (row_id,))
        elif damage == 'case_projection':
            conn.execute("UPDATE post_publication_runs SET state='incomplete',attempted_case_count=0,passed_case_count=0 WHERE id=?", (row_id,))
        for trigger in triggers:
            conn.execute(trigger['sql'])
    value = query_metrics(rule_storage, observation_window()).summary.postPublicationRegression
    assert value.state == 'unknown' and value.reason == 'source_unavailable'
    assert value.observedRuns is value.failedRuns is None


def test_observation_read_uses_one_snapshot_during_external_publication_audit_change(rule_storage, monkeypatch):
    import app.post_publication_metrics as module
    cohort(rule_storage)
    original, changed = module._source, []
    def source(*values):
        if not changed:
            with closing(db._connect()) as writer, writer:
                writer.execute("DELETE FROM audit_events WHERE event_type='rule_published'")
            changed.append(True)
        return original(*values)
    monkeypatch.setattr(module, '_source', source)
    query = observation_window()
    first = query_metrics(rule_storage, query).summary.postPublicationRegression
    second = query_metrics(rule_storage, query).summary.postPublicationRegression
    assert changed == [True]
    assert first.state == 'observed' and first.excluded.test.observedRuns == 4
    assert second.state == 'unknown' and second.reason == 'source_unavailable'


def test_window_query_uses_actual_started_index_and_constant_statement_count(rule_storage, monkeypatch):
    import app.metrics as metrics
    import app.post_publication_metrics as module
    cohort(rule_storage)
    original_execute, statements, plans = metrics._DeadlineConnection.execute, [], []
    def execute(connection, sql, parameters=()):
        statements.append(sql)
        if sql == module._SUMMARY_SQL:
            plans.extend(str(tuple(row)) for row in original_execute(
                connection, 'EXPLAIN QUERY PLAN ' + sql, parameters).fetchall())
        return original_execute(connection, sql, parameters)
    monkeypatch.setattr(metrics._DeadlineConnection, 'execute', execute)
    value = query_metrics(rule_storage, observation_window()).summary.postPublicationRegression
    count = len(statements)
    assert value.excluded.test.observedRuns == 4
    assert any('idx_post_publication_started' in plan for plan in plans)
    assert sum(sql == module._SUMMARY_SQL for sql in statements) == 1
    now = time.time()
    with closing(db._connect()) as conn, conn:
        row = conn.execute("SELECT plan_json FROM post_publication_runs WHERE state='running'").fetchone()
    from app.post_publication_contracts import PostPublicationPlan, checked_observation
    extra = checked_observation(PostPublicationPlan, row[0]).model_copy(update={
        'runId': str(uuid4()), 'operationKey': str(uuid4()), 'startedAt': now, 'deadlineAt': now + 5})
    PostPublicationRegression(rule_storage).store.reserve(extra)
    statements.clear()
    value = query_metrics(rule_storage, observation_window()).summary.postPublicationRegression
    assert value.excluded.test.observedRuns == 5 and len(statements) == count
    assert sum(sql == module._SUMMARY_SQL for sql in statements) == 1


def test_birth_counts_survive_corpus_withdrawal_without_authorizing_new_runs(rule_storage):
    from app.post_publication_contracts import PostPublicationError
    request = published(rule_storage)
    PostPublicationRegression(rule_storage).run(request)
    rule_storage.repair_corpus = None
    value = query_metrics(rule_storage, observation_window()).summary.postPublicationRegression
    assert value.excluded.test.observedRuns == 1
    with pytest.raises(PostPublicationError):
        PostPublicationRegression(rule_storage).run(request | {'operationKey': str(uuid4())})


def test_sql_source_deadline_is_busy_not_unknown_or_masked_success(rule_storage, monkeypatch):
    import app.post_publication_metrics as module
    from app.metrics_contracts import MetricsError
    published_request = published(rule_storage)
    PostPublicationRegression(rule_storage).run(published_request)
    original, clock = module._source, time.monotonic
    def source(*values):
        result = original(*values)
        monkeypatch.setattr(module.time, 'monotonic', lambda: clock() + 4)
        return result
    monkeypatch.setattr(module, '_source', source)
    with pytest.raises(MetricsError) as error:
        query_metrics(rule_storage, observation_window())
    assert (error.value.code, error.value.status) == ('metrics_busy', 503)


def test_export_observation_coverage_cannot_be_rebound_to_a_different_window():
    from pydantic import ValidationError
    from app.metrics_contracts import MetricsExport, MetricsObservedRegression, MetricsObservationExcluded, MetricsCoverage
    zero = {key: 0 for key in counter_body()}
    observed = MetricsObservedRegression(**zero, state='observed', sourceCoverageStart=1000.0,
        windowStartsBeforeCoverage=False, excluded=MetricsObservationExcluded(test=zero, synthetic=zero, unknown=zero))
    with pytest.raises(ValidationError):
        MetricsExport(window=dict(start=999.0, end=1100.0),
            filters=dict(soupId=None, puzzleVersion=None, ruleVersion=None),
            summary=dict(postPublicationRegression=observed.model_dump()), coverage=MetricsCoverage(),
            groups=(), generatedAt=1200.0)


def counter_body():
    return dict(observedRuns=4, passedRuns=1, failedRuns=1, incompleteRuns=1, pendingRuns=1,
        pendingExpiredRuns=1, plannedCases=4, attemptedCases=3, passedCases=1,
        counterexampleCases=1, errorCases=0, unsupportedCases=1, notAttemptedCases=1)


def counter_contract():
    import app.metrics_contracts as module
    cls = getattr(module, 'MetricsObservationCounts', None)
    assert cls is not None, 'Complete observation counters must have a closed contract'
    return cls


def test_observation_counts_keep_all_states_and_case_denominators():
    value = counter_contract()(**counter_body())
    assert value.model_dump() == counter_body()


@pytest.mark.parametrize('mutation', [dict(observedRuns=3), dict(pendingExpiredRuns=2), dict(plannedCases=3),
    dict(attemptedCases=2), dict(passedCases=True), dict(errorCases=-1), dict(accuracy=1.0)])
def test_invalid_observation_totals_never_become_closed_statistics(mutation):
    from pydantic import ValidationError
    cls = counter_contract()
    with pytest.raises(ValidationError): cls(**(counter_body() | mutation))


def test_missing_observation_counter_is_not_silently_filled_with_zero():
    from pydantic import ValidationError
    cls = counter_contract()
    body = counter_body()
    del body['errorCases']
    with pytest.raises(ValidationError): cls(**body)


@pytest.mark.parametrize('changes', [
    dict(passedRuns=1, notAttemptedCases=1),
    dict(failedRuns=1, attemptedCases=1, passedCases=1),
    dict(incompleteRuns=1, attemptedCases=1, counterexampleCases=1),
])
def test_run_status_must_have_its_required_case_evidence(changes):
    from pydantic import ValidationError
    body = dict.fromkeys(counter_body(), 0) | dict(observedRuns=1, plannedCases=1) | changes
    with pytest.raises(ValidationError): counter_contract()(**body)


def test_incomplete_run_can_keep_all_passed_cases_when_cleanup_or_deadline_failed():
    body = dict.fromkeys(counter_body(), 0) | dict(observedRuns=1, incompleteRuns=1,
        plannedCases=1, attemptedCases=1, passedCases=1)
    assert counter_contract()(**body).model_dump() == body


@pytest.mark.parametrize('body', [
    dict(observedRuns=0, passedRuns=0, failedRuns=0, incompleteRuns=0, pendingRuns=0, pendingExpiredRuns=0,
        plannedCases=4, attemptedCases=3, passedCases=1, counterexampleCases=1, errorCases=0, unsupportedCases=1, notAttemptedCases=1),
    dict(observedRuns=4, passedRuns=1, failedRuns=1, incompleteRuns=1, pendingRuns=1, pendingExpiredRuns=1,
        plannedCases=401, attemptedCases=400, passedCases=398, counterexampleCases=1, errorCases=0, unsupportedCases=1, notAttemptedCases=1),
    dict(observedRuns=4, passedRuns=0, failedRuns=0, incompleteRuns=0, pendingRuns=4, pendingExpiredRuns=4,
        plannedCases=4, attemptedCases=1, passedCases=1, counterexampleCases=0, errorCases=0, unsupportedCases=0, notAttemptedCases=3),
])
def test_case_totals_cannot_exist_outside_their_record_cohort(body):
    from pydantic import ValidationError
    cls = counter_contract()
    with pytest.raises(ValidationError): cls(**body)


def test_publication_helpers_release_owned_sqlite_connections(rule_storage, monkeypatch):
    import sqlite3

    opened = []
    original = db._connect

    def observe(*args, **kwargs):
        connection = original(*args, **kwargs)
        opened.append(connection)
        return connection

    monkeypatch.setattr(db, '_connect', observe)
    try:
        published(rule_storage)
        observation_window()
        assert len(opened) >= 2
        for connection in opened:
            with pytest.raises(sqlite3.ProgrammingError, match='closed'):
                connection.execute('SELECT 1')
    finally:
        for connection in opened:
            connection.close()
