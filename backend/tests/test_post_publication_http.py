"""Real private ASGI observations over genuine synthetic publications."""
from contextlib import closing
from dataclasses import replace
import json
from uuid import uuid4

from fastapi.testclient import TestClient
import pytest

from app import db, migrations
from app.audit_events import AuditEvent
from app.main import create_app
from app.runtime import runtime_context
from .test_post_publication_regression import published
from .test_rule_snapshots import rule_storage

PATH = '/api/feedback/admin/post-publication-regressions'
ADMIN = {'X-Admin-Token': 'synthetic-admin'}


@pytest.fixture
def api(rule_storage):
    request = published(rule_storage)
    settings = replace(rule_storage.settings, ENABLE_AGENT=False, ADMIN_TOKEN='synthetic-admin', SITE_PASSWORD='synthetic-site')
    app = create_app(settings, model=rule_storage.model, soups=rule_storage.soups, repair_corpus=rule_storage.repair_corpus)
    with TestClient(app, raise_server_exceptions=False) as client:
        yield app, client, request


def rows():
    with closing(db._connect()) as conn, conn:
        return [tuple(row) for row in conn.execute('SELECT * FROM post_publication_runs ORDER BY rowid')]


@pytest.mark.parametrize('headers', [{}, {'X-Admin-Token': 'wrong'}, {'X-Site-Token': 'synthetic-site'}])
def test_independent_admin_authority_required_before_admission(api, headers):
    _, client, request = api
    response = client.post(PATH, headers=headers, json=request)
    assert response.status_code == 401 and response.json()['code'] == 'admin_token_required'
    assert rows() == []


def test_actual_published_version_receipt_has_no_raw_material_or_provider_calls(api):
    app, client, request = api
    response = client.post(PATH, headers=ADMIN, json=request)
    assert response.status_code == 200, response.text
    body = response.json()
    assert set(body) == {'schemaVersion', 'plan', 'result', 'state'} and body['schemaVersion'] == 1
    assert body['state'] == 'passed' and body['plan']['publishedRuleVersion'] == request['publishedRuleVersion']
    assert len(body['plan']['cases']) == len(body['result']['caseResults']) == 1
    assert body['plan']['evidenceKind'] == 'synthetic_fixture' and body['plan']['trafficClass'] == 'test'
    assert '小明' not in response.text and 'expectedLabel' not in response.text and 'synthetic-admin' not in response.text
    assert response.headers['Cache-Control'] == 'no-store'
    assert app.state.runtime.model_gateway is None and app.state.runtime.agent_worker is None


@pytest.mark.parametrize('extra', [{'passed': True}, {'expectedLabel': 'PRIVATE'}, {'corpusPath': 'PRIVATE'},
    {'modelName': 'PRIVATE'}, {'codePath': 'PRIVATE'}, {'candidateId': 'PRIVATE'}])
def test_client_cannot_supply_result_labels_or_execution_paths(api, extra):
    _, client, request = api
    response = client.post(PATH, headers=ADMIN, json=request | extra)
    assert response.status_code == 422 and 'PRIVATE' not in response.text
    assert rows() == []


def test_duplicate_and_oversized_json_do_not_start_observation(api):
    _, client, request = api
    value = json.dumps(request)[:-1] + ',"operationKey":"' + str(uuid4()) + '"}'
    response = client.post(PATH, headers=ADMIN | {'Content-Type': 'application/json'}, content=value)
    assert response.status_code == 422
    response = client.post(PATH, headers=ADMIN, content='x' * 32769)
    assert response.status_code == 413 and rows() == []


def test_retry_returns_original_receipt_after_corpus_withdrawal(api):
    app, client, request = api
    first = client.post(PATH, headers=ADMIN, json=request)
    assert first.status_code == 200, first.text
    before = rows()
    app.state.runtime.repair_corpus = None
    again = client.post(PATH, headers=ADMIN, json=request)
    assert again.status_code == 200 and again.json() == first.json() and rows() == before


def test_same_key_different_candidate_conflicts_without_second_run(api):
    _, client, request = api
    assert client.post(PATH, headers=ADMIN, json=request).status_code == 200
    before = rows()
    response = client.post(PATH, headers=ADMIN, json=request | {'candidateId': str(uuid4())})
    assert response.status_code == 409 and response.json()['code'] == 'post_publication_conflict'
    assert rows() == before


def test_fixed_bucket_limits_five_attempts_even_with_changing_ids(api, monkeypatch):
    app, client, request = api
    monkeypatch.setattr(app.state.runtime, 'settings', replace(app.state.runtime.settings, RATE_LIMIT_ENABLED=True))
    for _ in range(5):
        response = client.post(PATH, headers=ADMIN, json=request | {'candidateId': str(uuid4()), 'operationKey': str(uuid4())})
        assert response.status_code == 409, response.text
    response = client.post(PATH, headers=ADMIN, json=request)
    assert response.status_code == 429 and int(response.headers['Retry-After']) > 0 and rows() == []


def test_missing_corpus_refuses_with_fixed_error_not_private_paths(api):
    app, client, request = api
    app.state.runtime.repair_corpus = None
    response = client.post(PATH, headers=ADMIN, json=request)
    assert response.status_code == 422 and response.json()['code'] == 'post_publication_corpus_invalid'
    assert 'Traceback' not in response.text and 'sessions.db' not in response.text and rows() == []


def test_registered_attempt_has_no_model_calls_and_does_not_echo_token(api):
    app, client, request = api
    assert client.post(PATH, headers=ADMIN, json=request).status_code == 200
    with closing(db._connect()) as conn, conn:
        events = [AuditEvent.model_validate_json(row[0]) for row in conn.execute(
            "SELECT details_json FROM audit_events WHERE event_type='http_attempt'")]
    event = next(item for item in events if item.requestId == request['operationKey'])
    assert event.details.routeTemplate == PATH and event.details.modelCalls == ()
    assert 'synthetic-admin' not in event.model_dump_json()
    assert app.state.runtime.model_gateway is None


def test_unconfigured_admin_refuses_before_any_plan(api, monkeypatch):
    app, client, request = api
    monkeypatch.setattr(app.state.runtime, 'settings', replace(app.state.runtime.settings, ADMIN_TOKEN=''))
    response = client.post(PATH, headers=ADMIN, json=request)
    assert response.status_code == 503 and response.json()['code'] == 'admin_not_configured' and rows() == []


def test_schema4_route_never_migrates_to_five(rule_storage, tmp_path):
    from app.config import Settings
    app = create_app(Settings.for_test(tmp_path / 'schema4-api', ADMIN_TOKEN='synthetic-admin'),
        model=rule_storage.model, soups=rule_storage.soups)
    with TestClient(app, raise_server_exceptions=False) as client:
        with runtime_context(app.state.runtime), closing(db._connect()) as conn, conn:
            migrations.migrate(conn, app.state.runtime.soups, target_version=4)
        response = client.post(PATH, headers=ADMIN, json=dict(operationKey=str(uuid4()), candidateId=str(uuid4()),
            publishedRuleVersion='r1:' + 'a' * 64))
        assert response.status_code == 503, response.text
        with runtime_context(app.state.runtime), closing(db._connect()) as conn, conn:
            assert conn.execute("SELECT name FROM sqlite_master WHERE name='post_publication_runs'").fetchone() is None
        assert app.state.runtime.model_gateway is None


def test_normal_game_requests_do_not_automatically_run_post_publication_check(api):
    _, client, _ = api
    assert client.get('/api/soups', headers={'X-Site-Token': 'synthetic-site'}).status_code == 200
    response = client.post('/api/chat', headers={'X-Site-Token': 'synthetic-site'}, json={'soupId': 'synthetic'})
    assert response.status_code == 200 and rows() == []


def test_concurrent_same_key_observations_have_one_durable_plan(api):
    from concurrent.futures import ThreadPoolExecutor
    app, client, request = api
    with ThreadPoolExecutor(max_workers=2) as pool:
        responses = list(pool.map(lambda _: client.post(PATH, headers=ADMIN, json=request), range(2)))
    assert [response.status_code for response in responses] == [200, 200]
    receipts = [response.json() for response in responses]
    assert len({receipt['plan']['runId'] for receipt in receipts}) == 1
    assert all(receipt['state'] in {'running', 'passed'} for receipt in receipts)
    final = client.post(PATH, headers=ADMIN, json=request)
    assert final.status_code == 200 and final.json()['state'] == 'passed' and len(rows()) == 1
    assert app.state.runtime.model_gateway is None


def test_corrupt_publication_source_returns_fixed_error_without_echoing_raw_json(api):
    _, client, request = api
    with closing(db._connect()) as conn, conn:
        conn.execute("UPDATE audit_events SET details_json=? WHERE event_type='candidate_published'",
            ('{"PRIVATE_SOURCE":"synthetic-private-token"}',))
    response = client.post(PATH, headers=ADMIN, json=request)
    assert response.status_code == 409 and response.json()['code'] == 'post_publication_source_invalid'
    assert 'PRIVATE_SOURCE' not in response.text and 'synthetic-private-token' not in response.text and rows() == []


@pytest.mark.parametrize('mutation', ['state', 'extra', 'bool_schema'])
def test_closed_receipt_rejects_inconsistent_state_or_extra_fields(api, mutation):
    from app.post_publication_contracts import ObservationReceipt, PostPublicationError, checked_observation
    _, client, request = api
    response = client.post(PATH, headers=ADMIN, json=request)
    assert response.status_code == 200
    body = response.json()
    if mutation == 'state': body['state'] = 'running'
    elif mutation == 'extra': body['passed'] = True
    else: body['schemaVersion'] = True
    with pytest.raises(PostPublicationError): checked_observation(ObservationReceipt, body)
