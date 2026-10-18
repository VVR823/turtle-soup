"""Private start/status/cancel use actual owned rows and strict admin inputs."""
from contextlib import closing
import json
import time
from concurrent.futures import ThreadPoolExecutor
from dataclasses import replace
from threading import Event
from uuid import uuid4

import pytest
from fastapi.testclient import TestClient

from app.main import create_app
from app.runtime import runtime_context
from .test_agent_store import agent_storage, raw_rows
from .test_feedback_storage import storage
from .test_task_context import prepared

PATH = "/api/feedback/admin/agent-runs"
ADMIN = {"X-Admin-Token": "synthetic-admin"}
SITE = {"X-Site-Token": "synthetic-site"}


@pytest.fixture
def api(agent_storage):
    from langchain_core.messages import AIMessage
    entered, release = Event(), Event()
    class OnlineBlock:
        def invoke(self, messages):
            entered.set()
            assert release.wait(10), "Owned synthetic online call was not released"
            return AIMessage(content='{"answer":"是","reasoning":"synthetic"}')
    settings = replace(agent_storage.settings, ENABLE_AGENT=True,
        ADMIN_TOKEN="synthetic-admin", SITE_PASSWORD="synthetic-site")
    app = create_app(settings, model=OnlineBlock(), soups=agent_storage.soups)
    with TestClient(app, raise_server_exceptions=False) as client:
        active = app.state.runtime
        with runtime_context(active): item = prepared()
        # Use actual online occupancy, not a fake paused product scheduler.
        with ThreadPoolExecutor(max_workers=1) as pool:
            online = pool.submit(active.get_model_gateway().invoke, [], deadline=time.monotonic() + 10, max_attempts=1)
            try:
                assert entered.wait(2)
                yield active, client, item
            finally:
                active.agent_worker.stop_admission()
                release.set()
                assert online.result(timeout=2).answer == "是"


def body(item, **changes):
    return {**dict(feedbackId=item.id, requestId=str(uuid4()), expectedFeedbackVersion=item.rowVersion), **changes}


def start(api, **changes):
    active, client, item = api
    response = client.post(PATH, headers=ADMIN, json=body(item, **changes))
    assert response.status_code == 202, response.text
    assert set(response.json()) == {"runId"}
    return response.json()["runId"]


def agent_http_attempts(active):
    from app.audit_events import AuditEvent
    with runtime_context(active):
        return [AuditEvent.model_validate_json(row["details_json"]) for row in raw_rows("audit_events")
            if row["event_type"] == "http_attempt"]


def test_actual_start_status_cancel_persist_closed_route_templates(api):
    active, client, _ = api
    identity = start(api)
    status = client.get(PATH + "/" + identity, headers=ADMIN)
    assert status.status_code == 200
    cancelled = client.post(PATH + "/" + identity + "/cancel", headers=ADMIN,
        json={"expectedRowVersion": status.json()["rowVersion"]})
    assert cancelled.status_code == 200 and cancelled.json()["state"] == "cancelled"
    assert cancelled.json()["modelAttemptsUsed"] == cancelled.json()["toolAttemptsUsed"] == 0
    selected = agent_http_attempts(active)
    assert [(item.details.routeTemplate, item.details.statusCode) for item in selected] == [
        (PATH, 202), (PATH + "/{run_id}", 200), (PATH + "/{run_id}/cancel", 200)]
    assert all(identity not in item.details.routeTemplate for item in selected)


@pytest.mark.parametrize("suffix,method", [("", "POST"), ("/PRIVATE_RAW_RUN", "GET"),
    ("/PRIVATE_RAW_RUN/cancel", "POST")])
@pytest.mark.parametrize("boundary,want_status", [("cors", 200), ("oversized", 413), ("unauthorized", 401)])
def test_agent_audit_pre_routing_and_auth_keep_templates_without_raw_paths(api, suffix, method, boundary, want_status):
    active, client, item = api
    path = PATH + suffix + "?private=PRIVATE_RAW_QUERY"
    if boundary == "cors":
        response = client.options(path, headers={"origin": "http://localhost:3000",
            "access-control-request-method": method})
    else:
        headers = {"content-length": "40000"} if boundary == "oversized" else {"X-Admin-Token": "PRIVATE_WRONG_ADMIN"}
        response = client.request(method, path, headers=headers,
            json=body(item) if suffix == "" else {"expectedRowVersion": 0})
    assert response.status_code == want_status
    selected = agent_http_attempts(active)
    assert len(selected) == 1
    record = selected[0]
    expected = PATH if suffix == "" else PATH + ("/{run_id}/cancel" if suffix.endswith("cancel") else "/{run_id}")
    assert (record.details.routeTemplate, record.details.statusCode) == (expected, want_status)
    assert "PRIVATE" not in record.model_dump_json()
    with runtime_context(active):
        assert raw_rows("agent_runs") == []


def test_start_is_persisted_idempotent_and_response_contains_only_server_run_id(api):
    active, client, item = api; value = body(item)
    first = client.post(PATH, headers=ADMIN, json=value)
    assert first.status_code == 202, first.text
    assert set(first.json()) == {"runId"} and "PRIVATE" not in first.text
    again = client.post(PATH, headers=ADMIN, json=value)
    assert again.status_code == 202 and again.json() == first.json()
    with runtime_context(active):
        rows = raw_rows("agent_runs")
        assert len(rows) == 1 and rows[0]["id"] == first.json()["runId"] and rows[0]["state"] == "queued"
        assert json.loads(rows[0]["checkpoint_json"])["firstStartedAt"] is None
        assert raw_rows("agent_steps") == []


@pytest.mark.parametrize("headers", [{}, SITE, {"X-Admin-Token": "wrong"}])
def test_agent_admin_auth_remains_independent_from_player_site_password(api, headers):
    active, client, item = api
    response = client.post(PATH, headers=headers, json=body(item))
    assert response.status_code == 401 and response.json()["code"] == "admin_token_required"
    with runtime_context(active): assert raw_rows("agent_runs") == []


@pytest.mark.parametrize("extra", [dict(trafficClass="real"), dict(allowedTools=[]), dict(model="paid-model"),
    dict(leaseSeconds=180), dict(approve=True)])
def test_http_caller_cannot_supply_execution_privileges_or_model_selection(api, extra):
    active, client, item = api
    response = client.post(PATH, headers=ADMIN, json={**body(item), **extra})
    assert response.status_code == 422 and "paid-model" not in response.text
    with runtime_context(active): assert raw_rows("agent_runs") == []


def test_status_and_cancel_are_minimal_current_version_controls_not_source_material(api):
    active, client, _ = api; identity = start(api)
    response = client.get(PATH + "/" + identity, headers=ADMIN)
    assert response.status_code == 200, response.text
    status = response.json()
    assert status["id"] == identity and status["state"] == "queued" and status["deadlineAt"] is None
    assert status["modelAttemptsUsed"] == status["toolAttemptsUsed"] == 0 and status["steps"] == []
    assert not {"manifest", "leaseToken", "question", "facts", "rawTrace"} & set(status)
    cancelled = client.post(PATH + "/" + identity + "/cancel", headers=ADMIN,
        json=dict(expectedRowVersion=status["rowVersion"]))
    assert cancelled.status_code == 200 and cancelled.json()["state"] == "cancelled"
    assert cancelled.json()["reason"] == "cancellation"
    stale = client.post(PATH + "/" + identity + "/cancel", headers=ADMIN, json=dict(expectedRowVersion=0))
    assert stale.status_code == 409


def test_default_disabled_agent_http_never_creates_or_migrates_a_run(tmp_path):
    import sqlite3
    from app.config import Settings
    from .test_migrations import puzzle
    app = create_app(Settings.for_test(tmp_path / "disabled", ADMIN_TOKEN="synthetic-admin"), soups=[puzzle()])
    with TestClient(app, raise_server_exceptions=False) as client:
        response = client.post(PATH, headers=ADMIN, json=dict(feedbackId=str(uuid4()), requestId=str(uuid4()), expectedFeedbackVersion=0))
        assert response.status_code == 503 and response.json()["code"] == "agent_disabled"
        assert app.state.runtime.model_gateway is None and app.state.runtime.agent_worker is None
    with closing(sqlite3.connect(app.state.runtime.settings.DATA_DIR / "sessions.db")) as conn, conn:
        assert conn.execute("SELECT name FROM sqlite_master WHERE name='agent_runs'").fetchone() is None


def test_status_after_permission_revocation_is_safe_and_cancel_does_not_restore_model_access(api):
    from .test_agent_stop import revoke
    active, client, item = api; identity = start(api)
    with runtime_context(active): revoke(item)
    shown = client.get(PATH + "/" + identity, headers=ADMIN)
    assert shown.status_code == 200 and "PRIVATE" not in shown.text
    assert not {"manifest", "leaseToken", "facts", "question"} & set(shown.json())
    cancelled = client.post(PATH + "/" + identity + "/cancel", headers=ADMIN,
        json=dict(expectedRowVersion=shown.json()["rowVersion"]))
    assert cancelled.status_code == 200 and cancelled.json()["state"] == "cancelled"
    refused = client.post(PATH, headers=ADMIN, json=body(item))
    assert refused.status_code == 409 and "runId" not in refused.json()
    with runtime_context(active): assert len(raw_rows("agent_runs")) == 1


def test_changed_payload_cannot_reuse_an_existing_request_identity(api):
    active, client, item = api; value = body(item)
    first = client.post(PATH, headers=ADMIN, json=value)
    assert first.status_code == 202
    changed = client.post(PATH, headers=ADMIN, json={**value, "expectedFeedbackVersion": item.rowVersion + 1})
    assert changed.status_code == 409 and "runId" not in changed.json()
    with runtime_context(active): assert len(raw_rows("agent_runs")) == 1


@pytest.mark.parametrize("version", [True, -1, 0.0, "0", 9223372036854775808])
def test_admin_versions_are_real_bounded_integers(api, version):
    active, client, item = api
    response = client.post(PATH, headers=ADMIN, json=body(item, expectedFeedbackVersion=version))
    assert response.status_code == 422
    with runtime_context(active): assert raw_rows("agent_runs") == []


@pytest.mark.parametrize("raw", ['{"feedbackId":"PRIVATE","feedbackId":"duplicate","requestId":"bad","expectedFeedbackVersion":0}',
    '{"feedbackId":"PRIVATE","requestId":"bad","expectedFeedbackVersion":NaN}',
    '{"feedbackId":"PRIVATE","requestId":"bad","expectedFeedbackVersion":Infinity}'], ids=["duplicate", "nan", "infinity"])
def test_duplicate_nonfinite_or_invalid_ids_are_refused_without_raw_input_echo(api, raw):
    active, client, _ = api
    response = client.post(PATH, headers={**ADMIN, "Content-Type": "application/json"}, content=raw)
    assert response.status_code == 422 and "PRIVATE" not in response.text
    with runtime_context(active): assert raw_rows("agent_runs") == []


def test_oversize_admin_body_is_refused_before_any_run_is_created(api):
    active, client, _ = api
    response = client.post(PATH, headers={**ADMIN, "Content-Type": "application/json"}, content=b"x" * 32769)
    assert response.status_code == 413 and response.json()["code"] == "request_body_too_large"
    with runtime_context(active): assert raw_rows("agent_runs") == []


def test_missing_admin_configuration_is_never_replaced_by_site_token(api):
    active, client, item = api
    active.settings = replace(active.settings, ADMIN_TOKEN="")
    response = client.post(PATH, headers=SITE, json=body(item))
    assert response.status_code == 503 and response.json()["code"] == "admin_not_configured"
    with runtime_context(active): assert raw_rows("agent_runs") == []


def test_status_and_cancel_reject_player_credentials_even_for_known_run_identity(api):
    active, client, _ = api; identity = start(api)
    shown = client.get(PATH + "/" + identity, headers=SITE)
    cancelled = client.post(PATH + "/" + identity + "/cancel", headers=SITE, json=dict(expectedRowVersion=0))
    assert shown.status_code == cancelled.status_code == 401
    with runtime_context(active): assert raw_rows("agent_runs")[0]["state"] == "queued"


def test_unknown_run_and_invalid_path_are_controlled_and_do_not_borrow_other_run(api):
    active, client, _ = api; identity = start(api)
    unknown = client.get(PATH + "/" + str(uuid4()), headers=ADMIN)
    assert unknown.status_code == 404 and unknown.json()["code"] == "agent_run_not_found"
    invalid = client.get(PATH + "/PRIVATE-invalid-id", headers=ADMIN)
    assert invalid.status_code == 422 and "PRIVATE" not in invalid.text
    with runtime_context(active): assert len(raw_rows("agent_runs")) == 1 and raw_rows("agent_runs")[0]["id"] == identity


def test_queue_ten_is_durable_and_eleventh_http_request_never_reserves_a_model(api):
    active, client, item = api
    identities = []
    for _ in range(10): identities.append(start(api))
    response = client.post(PATH, headers=ADMIN, json=body(item))
    assert response.status_code == 429 and response.json()["code"] == "agent_queue_full"
    with runtime_context(active):
        assert len(set(identities)) == len(raw_rows("agent_runs")) == 10 and raw_rows("agent_steps") == []
        assert all(json.loads(row["checkpoint_json"])["modelAttemptsUsed"] == 0 for row in raw_rows("agent_runs"))


def test_status_rate_limit_uses_route_template_not_user_selected_run_id(api):
    active, client, _ = api
    active.settings = replace(active.settings, RATE_LIMIT_ENABLED=True)
    for _ in range(30):
        assert client.get(PATH + "/" + str(uuid4()), headers=ADMIN).status_code == 404
    response = client.get(PATH + "/" + str(uuid4()), headers=ADMIN)
    assert response.status_code == 429 and int(response.headers["Retry-After"]) > 0
    with runtime_context(active): assert raw_rows("agent_runs") == []


def test_approved_private_review_without_linked_trace_does_not_invent_a_task(api):
    from app.feedback_store import submit_feedback, review_feedback, set_model_permission
    from .test_feedback_storage import body as feedback_body
    from .test_feedback_privacy import permission
    active, client, _ = api
    with runtime_context(active):
        legacy = submit_feedback(feedback_body())
        legacy = review_feedback(legacy.id, legacy.rowVersion, status="approved")
        legacy = set_model_permission(legacy.id, legacy.rowVersion, review=permission())
    response = client.post(PATH, headers=ADMIN, json=body(legacy))
    assert response.status_code == 409 and "runId" not in response.json() and "PRIVATE" not in response.text
    with runtime_context(active): assert raw_rows("agent_runs") == []


def test_no_admin_approval_or_publication_is_added_by_agent_run_endpoints(api):
    _, client, _ = api; identity = start(api)
    for suffix in ("approve", "publish"):
        response = client.post(PATH + "/" + identity + "/" + suffix, headers=ADMIN, json={})
        assert response.status_code == 404
