"""Actual private HTTP statistics on owned synthetic databases only."""
from contextlib import closing
from dataclasses import replace

import pytest
from fastapi.testclient import TestClient

from app import db, migrations
from app.config import Settings
from app.main import create_app
from app.runtime import runtime_context
from app.testing import FakeModel
from .test_migrations import puzzle


ADMIN = {"x-admin-token": "synthetic-metrics-admin"}


@pytest.fixture
def metrics_api(tmp_path):
    settings = replace(Settings.for_test(tmp_path / "metrics-http"),
        ADMIN_TOKEN="synthetic-metrics-admin", SITE_PASSWORD="synthetic-metrics-site")
    app = create_app(settings, model=FakeModel(), soups=[puzzle()])
    with TestClient(app, raise_server_exceptions=False) as client:
        with runtime_context(app.state.runtime):
            with closing(db._connect()) as conn, conn:
                migrations.migrate(conn, app.state.runtime.soups, target_version=4)
        yield app, client


def test_actual_private_metrics_route_returns_closed_empty_page(metrics_api):
    response = metrics_api[1].get("/api/metrics/admin", params={"start": 1000, "end": 1100}, headers=ADMIN)
    assert response.status_code == 200
    assert response.headers["cache-control"] == "no-store"
    data = response.json()
    assert data["schemaVersion"] == 3 and data["consistency"] == "fixed_window_live_snapshot"
    assert data["query"]["limit"] == 50 and data["groups"] == [] and data["nextCursor"] is None
    assert data["summary"]["counts"]["httpAttempts"] == 0
    assert data["summary"]["taskPublication"] == {"numerator": 0, "denominator": 0, "ratio": None}
    assert metrics_api[0].state.runtime.model.calls == []


@pytest.mark.parametrize("path", ["/api/metrics/admin", "/api/metrics/admin/export"])
@pytest.mark.parametrize("headers", [{}, {"x-site-token": "synthetic-metrics-site"}, {"x-admin-token": "PRIVATE_WRONG_TOKEN"}])
def test_metrics_requires_independent_admin_and_refusals_are_not_cached(metrics_api, path, headers):
    response = metrics_api[1].get(path, headers=headers)
    assert response.status_code == 401 and response.json()["code"] == "admin_token_required"
    assert "PRIVATE_WRONG_TOKEN" not in response.text and "synthetic-metrics-admin" not in response.text
    assert response.headers.get("cache-control") == "no-store"


@pytest.mark.parametrize("path", ["/api/metrics/admin", "/api/metrics/admin/export"])
@pytest.mark.parametrize("params", [[("limit", "50"), ("limit", "50")], [("PRIVATE_UNKNOWN_KEY", "PRIVATE_QUERY_VALUE")],
    [("start", "nan")], [("start", "0"), ("end", "2678401")]])
def test_metrics_rejects_closed_duplicate_and_unbounded_query(metrics_api, path, params):
    response = metrics_api[1].get(path, params=params, headers=ADMIN)
    assert response.status_code == 422 and response.json()["code"] == "metrics_query_invalid"
    assert response.headers.get("cache-control") == "no-store"
    assert "PRIVATE_UNKNOWN_KEY" not in response.text and "PRIVATE_QUERY_VALUE" not in response.text


@pytest.mark.parametrize("path", ["/api/metrics/admin", "/api/metrics/admin/export"])
def test_metrics_get_body_is_rejected_not_ignored(metrics_api, path):
    response = metrics_api[1].request("GET", path, content=b"PRIVATE_IGNORED_BODY", headers=ADMIN)
    assert response.status_code == 422 and response.json()["code"] == "metrics_query_invalid"
    assert response.headers.get("cache-control") == "no-store" and "PRIVATE_IGNORED_BODY" not in response.text


def test_empty_export_is_complete_attachment_not_page_slice(metrics_api):
    response = metrics_api[1].get("/api/metrics/admin/export", params={"start": 1000, "end": 1100}, headers=ADMIN)
    assert response.status_code == 200
    assert response.headers["content-disposition"] == 'attachment; filename="turtle-soup-metrics.json"'
    assert response.headers["cache-control"] == "no-store"
    data = response.json()
    assert set(data) == {"schemaVersion", "window", "filters", "summary", "coverage", "groups", "complete", "generatedAt"}
    assert data["complete"] is True and data["groups"] == [] and "nextCursor" not in data
    assert metrics_api[0].state.runtime.model.calls == []


@pytest.mark.parametrize("path", ["/api/metrics/admin", "/api/metrics/admin/export"])
def test_unconfigured_metrics_admin_is_closed_503(tmp_path, path):
    app = create_app(Settings.for_test(tmp_path / "unconfigured"), model=FakeModel(), soups=[puzzle()])
    with TestClient(app) as client:
        response = client.get(path, headers=ADMIN)
        assert response.status_code == 503 and response.json()["code"] == "admin_not_configured"
        assert response.headers.get("cache-control") == "no-store"
        assert app.state.runtime.model.calls == []


@pytest.mark.parametrize("path", ["/api/metrics/admin", "/api/metrics/admin/export"])
def test_http_old_phase_never_auto_migrates(tmp_path, path):
    settings = replace(Settings.for_test(tmp_path / "old-phase"), ADMIN_TOKEN="synthetic-metrics-admin")
    app = create_app(settings, model=FakeModel(), soups=[puzzle()])
    with TestClient(app) as client:
        with runtime_context(app.state.runtime):
            with closing(db._connect()) as conn, conn:
                before = list(conn.execute("SELECT version,checksum FROM schema_migrations ORDER BY version"))
                schema = list(conn.execute("SELECT name,sql FROM sqlite_master ORDER BY name"))
        response = client.get(path, headers=ADMIN)
        assert response.status_code == 503 and response.json()["code"] == "metrics_unavailable"
        assert response.headers.get("cache-control") == "no-store" and "004" in response.json()["detail"]
        with runtime_context(app.state.runtime):
            with closing(db._connect()) as conn, conn:
                assert list(conn.execute("SELECT version,checksum FROM schema_migrations ORDER BY version")) == before
                assert list(conn.execute("SELECT name,sql FROM sqlite_master ORDER BY name")) == schema
        assert app.state.runtime.model.calls == []


@pytest.mark.parametrize("path,limit,other", [("/api/metrics/admin", 30, "/api/metrics/admin/export"),
    ("/api/metrics/admin/export", 5, "/api/metrics/admin")])
def test_statistics_rate_limits_are_independent_and_keep_retry_after(metrics_api, path, limit, other):
    metrics_api[0].state.runtime.settings = replace(metrics_api[0].state.runtime.settings, RATE_LIMIT_ENABLED=True)
    for _ in range(limit):
        assert metrics_api[1].get(path, headers=ADMIN).status_code == 200
    denied = metrics_api[1].get(path, headers=ADMIN)
    assert denied.status_code == 429 and denied.json()["code"] == "rate_limited"
    assert int(denied.headers["retry-after"]) > 0 and denied.headers.get("cache-control") == "no-store"
    assert metrics_api[1].get(other, headers=ADMIN).status_code == 200
    assert metrics_api[0].state.runtime.model.calls == []


@pytest.mark.parametrize("path", ["/api/metrics/admin", "/api/metrics/admin/export"])
def test_actual_metrics_attempt_audit_has_fixed_template_without_query_or_token(metrics_api, path):
    from app.audit_events import AuditEvent
    response = metrics_api[1].get(path, params={"PRIVATE_QUERY_KEY": "PRIVATE_QUERY_VALUE"}, headers=ADMIN)
    assert response.status_code == 422
    with runtime_context(metrics_api[0].state.runtime):
        with closing(db._connect()) as conn, conn:
            rows = list(conn.execute("SELECT details_json FROM audit_events WHERE event_type='http_attempt'"))
    assert len(rows) == 1
    event = AuditEvent.model_validate_json(rows[0]["details_json"])
    assert event.details.routeTemplate == path and event.details.statusCode == 422
    assert event.details.trafficClass == "test"
    assert all(secret not in event.model_dump_json() for secret in
        ("PRIVATE_QUERY_KEY", "PRIVATE_QUERY_VALUE", "synthetic-metrics-admin", "synthetic-metrics-site"))
    assert metrics_api[0].state.runtime.model.calls == []


@pytest.fixture
def metrics_volume_api(tmp_path):
    soups = [puzzle().model_copy(update={"id": f"synthetic-{index}"}) for index in range(4)]
    settings = replace(Settings.for_test(tmp_path / "metrics-volume-http"), ADMIN_TOKEN="synthetic-metrics-admin")
    app = create_app(settings, model=FakeModel(), soups=soups)
    with TestClient(app) as client:
        with runtime_context(app.state.runtime):
            with closing(db._connect()) as conn, conn:
                migrations.migrate(conn, soups, target_version=4)
        yield app, client


@pytest.mark.parametrize("count", [100, 101])
def test_http_complete_export_refuses_instead_of_silently_truncating(metrics_volume_api, count):
    from .test_metrics_query_plan import seed_sessions
    app, client = metrics_volume_api
    with runtime_context(app.state.runtime):
        seed_sessions(app.state.runtime, count)  # Declared synthetic volume, not actual users.
        with closing(db._connect()) as conn, conn:
            private_ids = [row[0] for row in conn.execute("SELECT id FROM sessions")]
    params = {"start": 0, "end": 31 * 86400}
    page = client.get("/api/metrics/admin", params=params, headers=ADMIN)
    assert page.status_code == 200 and len(page.json()["groups"]) == 50 and page.json()["nextCursor"]
    exported = client.get("/api/metrics/admin/export", params=params, headers=ADMIN)
    assert exported.headers["cache-control"] == "no-store"
    assert all(identity not in exported.text and identity not in page.text for identity in private_ids)
    if count == 101:
        assert exported.status_code == 409 and exported.json()["code"] == "metrics_export_too_large"
        assert "content-disposition" not in exported.headers and "groups" not in exported.json()
    else:
        assert exported.status_code == 200 and exported.json()["complete"] is True
        assert len(exported.json()["groups"]) == 100
        assert exported.json()["summary"]["counts"]["sessionsCreated"] == 100
        assert sum(group["counts"]["sessionsCreated"] for group in exported.json()["groups"]) == 100
    assert app.state.runtime.model.calls == []


@pytest.mark.parametrize("param", [{"limit": 50}, {"cursor": "PRIVATE_CURSOR"}])
def test_http_export_cannot_request_a_page_slice(metrics_api, param):
    response = metrics_api[1].get("/api/metrics/admin/export", params=param, headers=ADMIN)
    assert response.status_code == 422 and response.json()["code"] == "metrics_query_invalid"
    assert "PRIVATE_CURSOR" not in response.text and "content-disposition" not in response.headers


def test_http_byte_guard_refuses_file_before_attachment(metrics_api, monkeypatch):
    from app import metrics_contracts
    assert metrics_contracts.MAX_EXPORT_BYTES == 512 * 1024
    # Controlled low test ceiling exercises the real projection/HTTP path, not
    # fabricated evidence that an empty export reaches the real 512 KiB limit.
    monkeypatch.setattr(metrics_contracts, "MAX_EXPORT_BYTES", 1)
    response = metrics_api[1].get("/api/metrics/admin/export", headers=ADMIN)
    assert response.status_code == 409 and response.json()["code"] == "metrics_export_too_large"
    assert response.headers["cache-control"] == "no-store" and "content-disposition" not in response.headers


@pytest.mark.parametrize("path", ["/api/metrics/admin", "/api/metrics/admin/export"])
def test_oversize_get_body_refusal_is_private_and_not_cached(metrics_api, path):
    response = metrics_api[1].request("GET", path, content=b"PRIVATE_BODY" * 3000, headers=ADMIN)
    assert response.status_code == 413 and response.json()["code"] == "request_body_too_large"
    assert "PRIVATE_BODY" not in response.text
    assert response.headers.get("cache-control") == "no-store"


@pytest.mark.parametrize("cursor", ["PRIVATE_CURSOR", "x" * 2049])
def test_http_summary_cursor_malformed_or_oversized_is_closed_422(metrics_api, cursor):
    response = metrics_api[1].get("/api/metrics/admin", params={"cursor": cursor}, headers=ADMIN)
    assert response.status_code == 422 and response.json()["code"] == "metrics_query_invalid"
    assert response.headers["cache-control"] == "no-store" and "PRIVATE_CURSOR" not in response.text
