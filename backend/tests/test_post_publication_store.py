"""Storage-level synthetic FK fixtures are NOT verified publication evidence."""
from contextlib import closing
import sqlite3
from concurrent.futures import ThreadPoolExecutor

import pytest

from app import baselines, migrations, post_publication_store as store_module
from app.post_publication_contracts import PostPublicationError, PostPublicationPlan, checked_observation
from .test_agent_migrations import identities
from .test_migrations import puzzle
from .test_post_publication_contracts import plan_body, result_body


@pytest.fixture
def owned(runtime):
    path = runtime.settings.DATA_DIR / 'sessions.db'
    with closing(sqlite3.connect(path)) as conn, conn:
        report = migrations.migrate(conn, [puzzle()], target_version=5)
        _, _, _, candidate, _ = identities(conn)
        conn.commit()
        p = conn.execute('SELECT id FROM puzzle_versions LIMIT 1').fetchone()[0]
        r = conn.execute('SELECT id FROM rule_releases LIMIT 1').fetchone()[0]
    body = plan_body()
    start = report['phase005']['coverageStart'] + 0.01
    body.update(candidateId=candidate, puzzleVersion=p, publishedRuleVersion=r,
        startedAt=start, deadlineAt=start + 5)
    return runtime, path, checked_observation(PostPublicationPlan, body), start + 0.1


def store(owned, verify=None):
    Store = getattr(store_module, 'PostPublicationStore', None)
    assert Store is not None, 'Durable observation store must exist'
    runtime, _, _, now = owned
    return Store(runtime, verify_source=verify or (lambda conn, plan: True), clock=lambda: now)


def test_reservation_persists_complete_pending_plan_before_any_results(owned):
    _, path, plan, _ = owned
    record, created = store(owned).reserve(plan)
    assert created is True and record.state == 'running' and record.result is None
    assert record.plan.plannedCaseCount == 3
    with closing(sqlite3.connect(path)) as conn, conn:
        row = conn.execute('SELECT state,planned_case_count,attempted_case_count,result_json FROM post_publication_runs').fetchone()
        assert row == ('running', 3, 0, None)
    # A newly constructed store sees exactly the same pending plan after restart.
    assert store(owned).get(plan.operationKey).plan == plan


def test_replay_retains_original_identity_and_does_not_add_rows(owned):
    _, path, plan, _ = owned
    first, _ = store(owned).reserve(plan)
    retry = plan.model_copy(update={'runId': '00000000-0000-4000-8000-000000000008'})
    second, created = store(owned).reserve(retry)
    assert created is False and second == first
    with closing(sqlite3.connect(path)) as conn, conn:
        assert conn.execute('SELECT count(*) FROM post_publication_runs').fetchone()[0] == 1


def test_same_operation_different_payload_refused_without_writes(owned):
    _, path, plan, _ = owned
    store(owned).reserve(plan)
    changed = plan.model_copy(update={'datasetDigest': '3' * 64})
    with pytest.raises(PostPublicationError) as error:
        store(owned).reserve(changed)
    assert error.value.code == 'post_publication_conflict'
    assert store(owned).get(plan.operationKey).plan == plan


def test_two_concurrent_reservations_have_one_winner(owned):
    _, path, plan, _ = owned
    active = store(owned)
    with ThreadPoolExecutor(max_workers=2) as workers:
        results = list(workers.map(lambda _: active.reserve(plan), range(2)))
    assert sorted(created for _, created in results) == [False, True]
    assert results[0][0] == results[1][0]
    with closing(sqlite3.connect(path)) as conn, conn:
        assert conn.execute('SELECT count(*) FROM post_publication_runs').fetchone()[0] == 1


def test_terminal_result_written_once_and_identical_replay_is_read_only(owned):
    _, path, plan, now = owned
    active = store(owned)
    active.reserve(plan)
    body = result_body(plan)
    body['finishedAt'] = now
    first = active.finish(plan.operationKey, body)
    assert first.state == 'passed' and first.result.passedCaseCount == 3
    with closing(sqlite3.connect(path)) as conn, conn:
        before = '\n'.join(conn.iterdump())
    assert active.finish(plan.operationKey, body) == first
    with closing(sqlite3.connect(path)) as conn, conn:
        assert '\n'.join(conn.iterdump()) == before
    body['terminationCode'] = 'source_changed'
    with pytest.raises(PostPublicationError):
        active.finish(plan.operationKey, body)
    assert active.get(plan.operationKey) == first


def test_failed_and_unattempted_cases_remain_in_complete_plan(owned):
    _, _, plan, now = owned
    active = store(owned)
    active.reserve(plan)
    body = result_body(plan, ('counterexample', 'error', 'not_attempted'))
    body.update(finishedAt=now, terminationCode='error')
    record = active.finish(plan.operationKey, body)
    assert record.state == 'failed'
    assert record.plan.plannedCaseCount == 3
    assert (record.result.attemptedCaseCount, record.result.errorCaseCount, record.result.notAttemptedCaseCount) == (2, 1, 1)


@pytest.mark.parametrize('phase', ['reserve', 'finish', 'read'])
def test_missing_fresh_source_authority_denies_every_operation(owned, phase):
    _, path, plan, now = owned
    good = store(owned)
    if phase != 'reserve': good.reserve(plan)
    denied = store(owned, lambda conn, plan: False)
    with pytest.raises(PostPublicationError) as error:
        if phase == 'reserve': denied.reserve(plan)
        elif phase == 'read': denied.get(plan.operationKey)
        else:
            body = result_body(plan)
            body['finishedAt'] = now
            denied.finish(plan.operationKey, body)
    assert error.value.code == 'post_publication_source_invalid'
    with closing(sqlite3.connect(path)) as conn, conn:
        states = conn.execute('SELECT state FROM post_publication_runs').fetchall()
        assert states == ([] if phase == 'reserve' else [('running',)])


def test_source_revocation_at_commit_rolls_back_whole_reservation(owned):
    _, path, plan, _ = owned
    def source(conn, current):
        return conn.execute('SELECT count(*) FROM post_publication_runs').fetchone()[0] == 0
    with pytest.raises(PostPublicationError):
        store(owned, source).reserve(plan)
    with closing(sqlite3.connect(path)) as conn, conn:
        assert conn.execute('SELECT count(*) FROM post_publication_runs').fetchone()[0] == 0


@pytest.mark.parametrize('change', ['plan_digest', 'payload_digest', 'state', 'count'])
def test_persisted_projection_tampering_is_not_signed_as_a_valid_record(owned, change):
    _, path, plan, _ = owned
    store(owned).reserve(plan)
    with closing(sqlite3.connect(path)) as conn, conn:
        conn.execute('DROP TRIGGER post_publication_runs_plan_immutable')
        conn.execute('DROP TRIGGER post_publication_runs_terminal_immutable')
        if change == 'plan_digest': conn.execute("UPDATE post_publication_runs SET plan_digest=?", ('0' * 64,))
        elif change == 'payload_digest': conn.execute("UPDATE post_publication_runs SET payload_digest=?", ('0' * 64,))
        elif change == 'count': conn.execute('UPDATE post_publication_runs SET planned_case_count=2')
        else:
            body = result_body(plan)
            body['finishedAt'] = plan.startedAt + 0.1
            raw = baselines.canonical_json(body)
            conn.execute("UPDATE post_publication_runs SET state='incomplete',result_json=?,result_digest=?,finished_at=?",
                (raw, baselines.digest(body), body['finishedAt']))
        conn.commit()
        # Restore exact registered triggers so schema validation alone cannot
        # satisfy this test; it must reject the stored body/scalar discrepancy.
        for sql in migrations.POST_PUBLICATION_SQL[2:4]: conn.execute(sql)
        conn.commit()
    with pytest.raises(PostPublicationError) as error:
        store(owned).get(plan.operationKey)
    assert error.value.code == 'post_publication_record_invalid'


def test_old005_absence_is_not_auto_migrated(runtime):
    path = runtime.settings.DATA_DIR / 'sessions.db'
    with closing(sqlite3.connect(path)) as conn, conn:
        migrations.migrate(conn, [puzzle()], target_version=4)
        before = '\n'.join(conn.iterdump())
    owned = (runtime, path, checked_observation(PostPublicationPlan, plan_body()), 102.0)
    with pytest.raises(PostPublicationError): store(owned).reserve(owned[2])
    with closing(sqlite3.connect(path)) as conn, conn:
        assert '\n'.join(conn.iterdump()) == before


def test_expired_pending_plan_survives_restart_without_running_again(owned):
    runtime, _, plan, now = owned
    first, _ = store(owned).reserve(plan)
    Store = store_module.PostPublicationStore
    restarted = Store(runtime, verify_source=lambda conn, plan: True, clock=lambda: now + 30)
    assert restarted.get(plan.operationKey) == first
    replay, created = restarted.reserve(plan)
    assert replay == first and created is False and replay.plan.plannedCaseCount == 3


def test_final_authority_revocation_rolls_back_finish_to_original_pending_plan(owned):
    _, path, plan, now = owned
    store(owned).reserve(plan)
    def source(conn, current):
        return conn.execute('SELECT result_json FROM post_publication_runs').fetchone()[0] is None
    body = result_body(plan)
    body['finishedAt'] = now
    with pytest.raises(PostPublicationError): store(owned, source).finish(plan.operationKey, body)
    assert store(owned).get(plan.operationKey).state == 'running'
    with closing(sqlite3.connect(path)) as conn, conn:
        assert conn.execute('SELECT attempted_case_count,result_json FROM post_publication_runs').fetchone() == (0, None)


def test_commit_failure_leaves_no_half_written_result(owned, monkeypatch):
    _, _, plan, now = owned
    store(owned).reserve(plan)
    connect = sqlite3.connect
    class FaultConnection(sqlite3.Connection):
        hits = 0
        def commit(self):
            self.hits += 1
            raise sqlite3.OperationalError('synthetic commit failure')
    connections = []
    def owned_connect(*args, **kwargs):
        conn = connect(*args, **kwargs, factory=FaultConnection)
        connections.append(conn)
        return conn
    body = result_body(plan)
    body['finishedAt'] = now
    with monkeypatch.context() as patch:
        patch.setattr(sqlite3, 'connect', owned_connect)
        with pytest.raises(PostPublicationError): store(owned).finish(plan.operationKey, body)
    assert len(connections) == 1 and connections[0].hits == 1
    record = store(owned).get(plan.operationKey)
    assert record.state == 'running' and record.result is None


def test_runtime_closed_by_final_source_check_cannot_commit(owned):
    runtime, path, plan, _ = owned
    def source(conn, current):
        if conn.execute('SELECT count(*) FROM post_publication_runs').fetchone()[0]:
            runtime.closed = True
        return True
    with pytest.raises(PostPublicationError): store(owned, source).reserve(plan)
    with closing(sqlite3.connect(path)) as conn, conn:
        assert conn.execute('SELECT count(*) FROM post_publication_runs').fetchone()[0] == 0


def test_source_check_finishing_after_deadline_cannot_commit_a_pass(owned):
    runtime, _, plan, now = owned
    store(owned).reserve(plan)
    current_time = [now]
    def source(conn, current):
        if conn.execute('SELECT state FROM post_publication_runs').fetchone()[0] == 'passed':
            current_time[0] = plan.deadlineAt + 1
        return True
    active = store_module.PostPublicationStore(runtime, verify_source=source, clock=lambda: current_time[0])
    body = result_body(plan)
    body['finishedAt'] = now
    with pytest.raises(PostPublicationError) as error:
        active.finish(plan.operationKey, body)
    assert error.value.code == 'post_publication_deadline'
    assert store(owned).get(plan.operationKey).state == 'running'
