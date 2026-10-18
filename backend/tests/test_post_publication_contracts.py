"""Breaks caught: discarded case denominator, wrong version and forged pass."""
from copy import deepcopy

import pytest

from app import baselines, post_publication_contracts as contracts


def plan_body():
    return dict(schemaVersion=1, runId='00000000-0000-4000-8000-000000000001',
        operationKey='00000000-0000-4000-8000-000000000002',
        candidateId='00000000-0000-4000-8000-000000000003',
        publicationOperationKey='00000000-0000-4000-8000-000000000004',
        publicationProofDigest='a' * 64, soupId='synthetic', puzzleVersion='p1:' + 'b' * 64,
        publishedRuleVersion='r1:' + 'c' * 64, publishedAt=100.0, startedAt=101.0, deadlineAt=106.0,
        trafficClass='test', evidenceKind='synthetic_fixture', datasetDigest='d' * 64,
        suiteManifestDigest='e' * 64, cases=[
            dict(caseId='00000000-0000-4000-8000-000000000005', caseDigest='f' * 64),
            dict(caseId='00000000-0000-4000-8000-000000000006', caseDigest='1' * 64),
            dict(caseId='00000000-0000-4000-8000-000000000007', caseDigest='2' * 64)])


def api():
    values = [getattr(contracts, name, None) for name in
        ('PostPublicationPlan', 'PostPublicationResult', 'PostPublicationError', 'checked_observation', 'validate_result')]
    assert all(value is not None for value in values), 'Closed observation API must exist'
    return values


def result_body(plan, statuses=('passed', 'passed', 'passed'), **changes):
    return dict(schemaVersion=1, runId=plan.runId, planDigest=plan.planDigest, finishedAt=102.0,
        cleanupConfirmed=True, terminationCode='finished', caseResults=[
            dict(caseId=case.caseId, status=status) for case, status in zip(plan.cases, statuses)], **changes)


def test_valid_plan_retains_full_case_scope_and_stable_payload_identity():
    Plan, _, _, check, _ = api()
    plan = check(Plan, plan_body())
    assert plan.plannedCaseCount == 3
    assert plan.planDigest == baselines.digest(plan_body())
    retry = plan_body()
    retry.update(runId='00000000-0000-4000-8000-000000000008', startedAt=102.0, deadlineAt=107.0)
    assert check(Plan, retry).payloadDigest == plan.payloadDigest
    assert check(Plan, retry).planDigest != plan.planDigest


@pytest.mark.parametrize('change', [
    {'schemaVersion': True}, {'startedAt': True}, {'deadlineAt': 101.0}, {'deadlineAt': 106.1},
    {'startedAt': 99.0}, {'publishedAt': float('nan')}, {'deadlineAt': float('inf')},
    {'trafficClass': 'real'}, {'runId': 'private question'}, {'publishedRuleVersion': 'base'},
    {'cases': []}, {'expectedLabel': '是'}, {'cases': [plan_body()['cases'][0]] * 2},
    {'cases': [dict(caseId='00000000-0000-4000-8000-000000000005', caseDigest='f' * 64, question='private')]},
])
def test_plan_rejects_forged_or_unbounded_scope(change):
    Plan, _, Error, check, _ = api()
    body = plan_body() | change
    with pytest.raises(Error):
        check(Plan, body)


@pytest.mark.parametrize(('statuses', 'termination', 'cleanup', 'state', 'counts'), [
    (('passed', 'passed', 'passed'), 'finished', True, 'passed', (3, 3, 0, 0, 0, 0)),
    (('counterexample', 'error', 'not_attempted'), 'error', True, 'failed', (2, 0, 1, 1, 0, 1)),
    (('passed', 'unsupported', 'not_attempted'), 'deadline', True, 'incomplete', (2, 1, 0, 0, 1, 1)),
    (('not_attempted', 'not_attempted', 'not_attempted'), 'deadline', True, 'incomplete', (0, 0, 0, 0, 0, 3)),
    (('passed', 'passed', 'passed'), 'cleanup_failed', False, 'incomplete', (3, 3, 0, 0, 0, 0)),
])
def test_result_counts_all_planned_cases_without_turning_errors_into_wrong_answers(statuses, termination, cleanup, state, counts):
    Plan, _, _, check, validate = api()
    plan = check(Plan, plan_body())
    body = result_body(plan, statuses)
    body.update(terminationCode=termination, cleanupConfirmed=cleanup)
    result = validate(plan, body)
    assert result.state == state
    assert (result.attemptedCaseCount, result.passedCaseCount, result.counterexampleCaseCount,
        result.errorCaseCount, result.unsupportedCaseCount, result.notAttemptedCaseCount) == counts


@pytest.mark.parametrize('mutation', ['drop_case', 'reorder', 'duplicate', 'other_run', 'other_plan',
    'early', 'late_pass', 'false_cleanup', 'after_gap', 'extra_state', 'bool_schema'])
def test_result_cannot_forge_binding_or_complete_execution(mutation):
    Plan, _, Error, check, validate = api()
    plan = check(Plan, plan_body())
    body = result_body(plan)
    if mutation == 'drop_case': body['caseResults'].pop()
    elif mutation == 'reorder': body['caseResults'].reverse()
    elif mutation == 'duplicate': body['caseResults'][1] = deepcopy(body['caseResults'][0])
    elif mutation == 'other_run': body['runId'] = '00000000-0000-4000-8000-000000000008'
    elif mutation == 'other_plan': body['planDigest'] = '0' * 64
    elif mutation == 'early': body['finishedAt'] = 100.0
    elif mutation == 'late_pass': body['finishedAt'] = 107.0
    elif mutation == 'false_cleanup': body['cleanupConfirmed'] = 1
    elif mutation == 'after_gap': body['caseResults'][0]['status'] = 'not_attempted'
    elif mutation == 'extra_state': body['state'] = 'passed'
    elif mutation == 'bool_schema': body['schemaVersion'] = True
    with pytest.raises(Error):
        validate(plan, body)


def test_consumers_revalidate_unsafe_model_copy():
    Plan, _, Error, check, validate = api()
    plan = check(Plan, plan_body())
    unsafe = plan.model_copy(update={'deadlineAt': 9999.0})
    with pytest.raises(Error):
        validate(unsafe, result_body(plan))
