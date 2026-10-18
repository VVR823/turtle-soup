"""Observe genuine synthetic publications through the actual host implementation."""
from contextlib import closing
from uuid import uuid4
import time

import pytest

from app import baselines, db, migrations, post_publication_regression as regression_module
from app.post_publication_contracts import PostPublicationError
from .test_candidate_review_publication import approved
from .test_candidate_validation import scope
from .test_repair_corpus import frozen_corpus
from .test_rule_snapshots import rule_storage


def published(active, *, answer='是'):
    owner, _, cid, intent = approved(active)
    release = owner.publish(cid, intent)
    # New server-selected dataset, not a replacement of the original report.
    active.repair_corpus = frozen_corpus(scope(), labels=(answer,))
    with closing(db._connect()) as conn, conn: migrations.migrate(conn, active.soups, target_version=5)
    return dict(operationKey=str(uuid4()), candidateId=cid, publishedRuleVersion=release.publishedRuleVersion)


def runner(active):
    cls = getattr(regression_module, 'PostPublicationRegression', None)
    assert cls is not None, 'Published host-path regression runner must exist'
    return cls(active)


def player_rows():
    with closing(db._connect()) as conn, conn:
        return {name: [tuple(row) for row in conn.execute(f'SELECT * FROM {name} ORDER BY rowid')]
            for name in ('sessions', 'messages', 'turns', 'rule_releases', 'runtime_meta', 'rule_candidates', 'audit_events')}


def test_published_exact_answer_runs_new_snapshot_without_provider_or_player_mutations(rule_storage, monkeypatch):
    request = published(rule_storage)
    before = player_rows()
    old_gateway = rule_storage.model_gateway
    old_cache = rule_storage.deterministic_host_cache
    def no_shared_gateway(*args, **kwargs):
        raise AssertionError('Shared runtime/provider must not be allocated or used')
    monkeypatch.setattr(rule_storage, 'get_model_gateway', no_shared_gateway)
    record = runner(rule_storage).run(request)
    assert record.state == 'passed' and record.plan.publishedRuleVersion == request['publishedRuleVersion']
    assert record.plan.plannedCaseCount == record.result.passedCaseCount == 1
    assert record.plan.trafficClass == 'test' and record.plan.evidenceKind == 'synthetic_fixture'
    assert rule_storage.model_gateway is old_gateway and rule_storage.deterministic_host_cache is old_cache
    assert player_rows() == before


def test_opposite_frozen_reference_detects_new_version_not_old_confusion_answer(rule_storage):
    # The old authored confusion answers 不是; the published replacement 是.
    # Deliberately opposite synthetic reference is a detector test, not gold truth.
    request = published(rule_storage, answer='不是')
    record = runner(rule_storage).run(request)
    assert record.state == 'failed' and record.result.counterexampleCaseCount == 1
    assert record.result.passedCaseCount == 0 and record.plan.plannedCaseCount == 1


def test_same_request_returns_saved_receipt_without_duplicate_observation(rule_storage):
    request = published(rule_storage)
    service = runner(rule_storage)
    first = service.run(request)
    assert service.run(request) == first
    with closing(db._connect()) as conn, conn: assert conn.execute('SELECT count(*) FROM post_publication_runs').fetchone()[0] == 1


def test_missing_server_corpus_cannot_manufacture_a_passing_report(rule_storage):
    request = published(rule_storage)
    rule_storage.repair_corpus = None
    with pytest.raises(PostPublicationError): runner(rule_storage).run(request)
    with closing(db._connect()) as conn, conn: assert conn.execute('SELECT count(*) FROM post_publication_runs').fetchone()[0] == 0


def test_client_cannot_supply_expected_answers_or_passed_flag(rule_storage):
    request = published(rule_storage)
    with pytest.raises(PostPublicationError): runner(rule_storage).run(request | {'passed': True, 'expectedLabel': '是'})
    with closing(db._connect()) as conn, conn: assert conn.execute('SELECT count(*) FROM post_publication_runs').fetchone()[0] == 0


def unsupported_corpus(active):
    from eval.contracts import EvalPuzzle, case_digest
    from eval.grouping import audit_groups
    from eval.manifest import freeze_regression, load_repair_corpus
    from backend.eval.tests.test_dataset_grouping import sources
    frozen = active.repair_corpus
    case = load_repair_corpus(frozen)[0].model_copy(update={'question': '他昨晚是否梦见了紫色的鲸鱼？'})
    case = case.model_copy(update={'review': case.review.model_copy(update={'caseDigest': case_digest(case)})})
    cases = (case,)
    catalog = tuple(EvalPuzzle.model_validate_json(baselines.canonical_json(value))
        for value in baselines.strict_json(frozen.catalogJson))
    digests = sources(cases)
    audit = audit_groups((), repair_cases=cases, source_digests=digests, source_complete=True)
    return freeze_regression(cases, catalog=catalog, audit=audit, source_digests=digests,
        frozen_at=frozen.manifest.frozenAt)


def test_model_fallback_is_unsupported_not_a_fake_passing_answer(rule_storage):
    request = published(rule_storage)
    rule_storage.repair_corpus = unsupported_corpus(rule_storage)
    before = player_rows()
    record = runner(rule_storage).run(request)
    assert record.state == 'incomplete' and record.result.unsupportedCaseCount == 1
    assert record.result.passedCaseCount == record.result.counterexampleCaseCount == 0
    assert record.plan.plannedCaseCount == 1 and player_rows() == before


def test_deadline_retains_unattempted_case_in_complete_plan(rule_storage):
    request = published(rule_storage)
    ticks = iter((0.0, 6.0))
    service = regression_module.PostPublicationRegression(rule_storage, clock=lambda: next(ticks, 6.0))
    record = service.run(request)
    assert record.state == 'incomplete' and record.result.terminationCode == 'deadline'
    assert record.plan.plannedCaseCount == record.result.notAttemptedCaseCount == 1
    assert record.result.attemptedCaseCount == record.result.passedCaseCount == 0


def test_cleanup_exception_is_incomplete_not_a_pass_or_untyped_crash(rule_storage, monkeypatch):
    request = published(rule_storage)
    real_cleanup = regression_module.asyncio.run
    def cleanup_failure(coro):
        real_cleanup(coro)
        raise RuntimeError('Synthetic cleanup receipt failure')
    monkeypatch.setattr(regression_module.asyncio, 'run', cleanup_failure)
    record = runner(rule_storage).run(request)
    assert record.state == 'incomplete' and record.result.cleanupConfirmed is False
    assert record.result.terminationCode == 'cleanup_failed'
    assert record.plan.plannedCaseCount == record.result.passedCaseCount == 1


def test_corpus_removed_after_admission_keeps_pending_denominator_and_never_commits_pass(rule_storage):
    request = published(rule_storage)
    calls = [0]
    def clock():
        calls[0] += 1
        if calls[0] > 1: rule_storage.repair_corpus = None
        return time.monotonic()
    service = regression_module.PostPublicationRegression(rule_storage, clock=clock)
    with pytest.raises(PostPublicationError): service.run(request)
    with closing(db._connect()) as conn, conn:
        assert tuple(conn.execute('SELECT state,planned_case_count,result_json FROM post_publication_runs').fetchone()) == ('running', 1, None)


@pytest.mark.parametrize('boundary', [2, 6])
@pytest.mark.parametrize('change', ['corpus', 'source_identity'])
def test_fresh_commit_rechecks_non_database_inputs(rule_storage, monkeypatch, boundary, change):
    # UTC call 2 is admission's clock; 6 is the finishedAt read, after the
    # runner's final live-input check. Keep real DB, host and source verifiers.
    from app.agents import source_identity
    request = published(rule_storage)
    calls = [0]
    now = time.time()
    def clock():
        calls[0] += 1
        if calls[0] == boundary:
            if change == 'corpus':
                rule_storage.repair_corpus = None
            else:
                monkeypatch.setitem(source_identity._PINNED,
                    str(regression_module.Path(regression_module.__file__).resolve()), '0' * 64)
        return now
    service = regression_module.PostPublicationRegression(rule_storage, utc_clock=clock)
    with pytest.raises(PostPublicationError): service.run(request)
    assert calls[0] >= boundary
    with closing(db._connect()) as conn, conn:
        rows = [tuple(row) for row in conn.execute('SELECT state,planned_case_count,result_json FROM post_publication_runs')]
    assert rows == ([] if boundary == 2 else [('running', 1, None)])


def test_historical_ack_does_not_depend_on_todays_corpus(rule_storage):
    request = published(rule_storage)
    service = runner(rule_storage)
    first = service.run(request)
    rule_storage.repair_corpus = None
    assert service.run(request) == first
    with closing(db._connect()) as conn, conn:
        assert conn.execute('SELECT count(*) FROM post_publication_runs').fetchone()[0] == 1


@pytest.mark.parametrize('elapsed', [5.0, 6.0])
def test_final_fresh_verification_cannot_commit_pass_after_monotonic_budget(rule_storage, monkeypatch, elapsed):
    request = published(rule_storage)
    before = player_rows()
    ticks, utc = [0.0], time.time()
    service = regression_module.PostPublicationRegression(rule_storage,
        clock=lambda: ticks[0], utc_clock=lambda: utc)
    original = service.store.verify_fresh
    final_checks = []
    def verify(conn, plan):
        valid = original(conn, plan)
        if conn.execute('SELECT state FROM post_publication_runs').fetchone()[0] == 'passed':
            final_checks.append(plan.planDigest)
            ticks[0] = elapsed
        return valid
    monkeypatch.setattr(service.store, 'verify_fresh', verify)
    record = service.run(request)
    assert final_checks == [record.plan.planDigest]
    assert record.state == 'incomplete' and record.result.terminationCode == 'deadline'
    assert record.plan.plannedCaseCount == record.result.attemptedCaseCount == record.result.passedCaseCount == 1
    assert record.result.cleanupConfirmed and record.plan.deadlineAt == utc + 5
    assert player_rows() == before
    def no_new_execution(*args):
        raise AssertionError('Historical receipt must not refresh clocks or execute fresh probes')
    service.clock = service.utc_clock = no_new_execution
    monkeypatch.setattr(service.store, 'verify_fresh', no_new_execution)
    assert service.run(request) == record
    with closing(db._connect()) as conn, conn:
        assert conn.execute('SELECT count(*) FROM post_publication_runs').fetchone()[0] == 1


def test_context_order_and_history_use_actual_new_host_answers_not_gold(rule_storage, monkeypatch):
    from eval.contracts import EvalPuzzle
    from eval.grouping import audit_groups
    from eval.manifest import freeze_regression, load_repair_corpus
    from backend.eval.tests.test_dataset_grouping import sources
    request = published(rule_storage)
    frozen = frozen_corpus(scope(), labels=('不是', '与此无关'), context_chain=True)
    cases = tuple(reversed(load_repair_corpus(frozen)))
    catalog = tuple(EvalPuzzle.model_validate_json(baselines.canonical_json(value))
        for value in baselines.strict_json(frozen.catalogJson))
    digests = sources(cases)
    audit = audit_groups((), repair_cases=cases, source_digests=digests, source_complete=True)
    rule_storage.repair_corpus = freeze_regression(cases, catalog=catalog, audit=audit,
        source_digests=digests, frozen_at=frozen.manifest.frozenAt)
    real_host, histories, questions = regression_module.handle_host_response, [], []
    def observe(soup, history, question, **kwargs):
        histories.append([dict(row) for row in history])
        questions.append(question)
        return real_host(soup, history, question, **kwargs)
    monkeypatch.setattr(regression_module, 'handle_host_response', observe)
    record = runner(rule_storage).run(request)
    assert record.state == 'failed' and record.result.counterexampleCaseCount == 1
    assert record.plan.plannedCaseCount == record.result.attemptedCaseCount == 3
    assert questions == ['小明是凶手吗？', '小红是凶手吗？', '小刚是凶手吗？']
    assert histories[0] == []
    assert histories[1] == [dict(role='user', content='小明是凶手吗？'),
        dict(role='host', content='是', answer='是', kind='answer', is_free_reminder=False)]
    # These two questions require a provider in this synthetic puzzle. The
    # offline runner must not invent gold answers or add them to history.
    assert record.result.unsupportedCaseCount == 2
    assert histories[2] == histories[1]


def test_parent_shutdown_after_admission_stops_before_any_host_probe(rule_storage, monkeypatch):
    request = published(rule_storage)
    calls, probes = [0], []
    now, real_host = time.time(), regression_module.handle_host_response
    def clock():
        calls[0] += 1
        if calls[0] == 3:
            regression_module.asyncio.run(rule_storage.aclose())
        return now
    def observe(*args, **kwargs):
        probes.append(True)
        return real_host(*args, **kwargs)
    monkeypatch.setattr(regression_module, 'handle_host_response', observe)
    service = regression_module.PostPublicationRegression(rule_storage, utc_clock=clock)
    with pytest.raises(PostPublicationError): service.run(request)
    assert probes == []
    # Closed parents refuse ordinary readers; use the owned test path directly.
    import sqlite3
    with closing(sqlite3.connect(rule_storage.settings.DATA_DIR / 'sessions.db')) as conn, conn:
        assert conn.execute('SELECT state,planned_case_count,result_json FROM post_publication_runs').fetchone() == ('running', 1, None)


@pytest.mark.parametrize('bad', [True, float('nan'), float('inf'), -1.0])
def test_invalid_server_clock_never_creates_observation(rule_storage, bad):
    request = published(rule_storage)
    service = regression_module.PostPublicationRegression(rule_storage, clock=lambda: bad)
    with pytest.raises(PostPublicationError) as error: service.run(request)
    assert error.value.code == 'post_publication_clock_invalid'
    with closing(db._connect()) as conn, conn:
        assert conn.execute('SELECT count(*) FROM post_publication_runs').fetchone()[0] == 0


def test_hard_stop_retains_pending_plan_and_replay_never_auto_resumes(rule_storage):
    request = published(rule_storage)
    calls = [0]
    def clock():
        calls[0] += 1
        if calls[0] > 1: raise KeyboardInterrupt('Synthetic hard stop')
        return time.monotonic()
    service = regression_module.PostPublicationRegression(rule_storage, clock=clock)
    with pytest.raises(KeyboardInterrupt): service.run(request)
    recovered = runner(rule_storage).run(request)
    assert recovered.state == 'running' and recovered.result is None and recovered.plan.plannedCaseCount == 1
    with closing(db._connect()) as conn, conn:
        assert conn.execute('SELECT count(*) FROM post_publication_runs').fetchone()[0] == 1


@pytest.mark.parametrize('invalid', ['holdout', 'oversize', 'catalog', 'formal_synthetic'])
def test_ineligible_server_corpus_is_refused_before_plan_admission(rule_storage, invalid):
    from dataclasses import replace
    request = published(rule_storage)
    frozen = rule_storage.repair_corpus
    original_gateway = rule_storage.model_gateway
    original_calls = list(rule_storage.model.calls)
    if invalid == 'holdout':
        rule_storage.repair_corpus = frozen.model_copy(update={
            'manifest': frozen.manifest.model_copy(update={'splitRole': 'holdout'})})
    elif invalid == 'oversize':
        rule_storage.repair_corpus = frozen_corpus(scope(), extra_cases=99)
    elif invalid == 'catalog':
        rule_storage.repair_corpus = frozen.model_copy(update={'catalogJson': '[]'})
    else:
        rule_storage.settings = replace(rule_storage.settings, TESTING=False)
    with pytest.raises(PostPublicationError): runner(rule_storage).run(request)
    with closing(db._connect()) as conn, conn:
        assert conn.execute('SELECT count(*) FROM post_publication_runs').fetchone()[0] == 0
    assert rule_storage.model_gateway is original_gateway and rule_storage.model.calls == original_calls


def test_maximum_corpus_retains_all_hundred_cases_even_if_budget_expires(rule_storage):
    request = published(rule_storage)
    rule_storage.repair_corpus = frozen_corpus(scope(), extra_cases=98)
    ticks = iter((0.0, 6.0))
    service = regression_module.PostPublicationRegression(rule_storage, clock=lambda: next(ticks, 6.0))
    record = service.run(request)
    assert record.state == 'incomplete' and record.result.terminationCode == 'deadline'
    assert record.plan.plannedCaseCount == record.result.notAttemptedCaseCount == 100
    assert len(record.result.caseResults) == 100 and record.result.attemptedCaseCount == 0
