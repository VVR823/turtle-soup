"""Private bounded audit reads and canonical pagination on synthetic records."""
import base64
import time
from dataclasses import replace
from uuid import UUID

import pytest
from fastapi.testclient import TestClient

from app import baselines, db
from app.audit_context import AttemptCollector
from app.config import Settings
from app.main import create_app
from app.runtime import runtime_context
from app.testing import FakeModel

ADMIN = {"x-admin-token": "synthetic-admin"}


@pytest.fixture
def api(tmp_path):
    settings = replace(Settings.for_test(tmp_path / "audit-admin"), ADMIN_TOKEN="synthetic-admin", SITE_PASSWORD="synthetic-site")
    app = create_app(settings, model=FakeModel())
    with TestClient(app, raise_server_exceptions=False) as client:
        yield app, client


def seed(api, count=80, *, stamp=None):
    stamp = time.time() - 3600 if stamp is None else stamp
    values = []
    for index in range(count):
        item = AttemptCollector(str(UUID(int=index + 1)), wall_clock=lambda: stamp, traffic_class="synthetic").finish(
            status_code=200, method="GET", route_template="/health", response_started=True, disconnected=False)
        values.append((item.eventId, item.eventType, baselines.canonical_json(item.model_dump(mode="json")), item.createdAt))
    with runtime_context(api[0].state.runtime):
        conn = db._connect()
        try:
            conn.executemany("INSERT INTO audit_events(id,event_type,details_json,created_at) VALUES(?,?,?,?)", values)
            conn.commit()
        finally:
            conn.close()
    return stamp


@pytest.mark.parametrize("method,path", [("get", "/api/audit/admin"), ("get", "/api/audit/admin/status"), ("post", "/api/audit/admin/recover")])
@pytest.mark.parametrize("headers", [{}, {"x-site-token": "synthetic-site"}, {"x-admin-token": "PRIVATE WRONG"}])
def test_private_audit_requires_independent_admin_credential(api, method, path, headers):
    response = getattr(api[1], method)(path, headers=headers)
    assert response.status_code == 401 and response.json()["code"] == "admin_token_required"
    assert not any(raw in response.text for raw in ("PRIVATE WRONG", "synthetic-admin", "fallback"))


def test_unconfigured_admin_token_is_safe_503(tmp_path):
    app = create_app(Settings.for_test(tmp_path), model=FakeModel())
    with TestClient(app) as client:
        response = client.get("/api/audit/admin", headers=ADMIN)
        assert response.status_code == 503 and response.json()["code"] == "admin_not_configured"


def test_missing_owned_audit_store_fails_closed(runtime):
    from app.audit_store import AuditPersistenceError
    from app.routers.audit import _store

    assert runtime.audit_store is None
    with pytest.raises(AuditPersistenceError, match="Audit store unavailable"):
        _store()


def test_default_fifty_and_explicit_hundred_are_bounded(api):
    seed(api, 130)
    first = api[1].get("/api/audit/admin", headers=ADMIN)
    assert first.status_code == 200
    body = first.json()
    assert len(body["events"]) == 50 and body["nextCursor"]
    assert all(row["details"]["usage"]["totalTokens"] is None for row in body["events"])
    second = api[1].get("/api/audit/admin", params={"limit": 100}, headers=ADMIN)
    assert second.status_code == 200 and len(second.json()["events"]) == 100
    assert "PRIVATE" not in first.text and "sessions.db" not in first.text


@pytest.mark.parametrize("params", [{"limit": 0}, {"limit": 101}, {"limit": "NaN"},
    {"start": "nan"}, {"end": "inf"}, {"start": -1}, {"start": 200, "end": 100},
    {"start": 0, "end": 2678401}, {"eventType": "SECRET ARBITRARY"}, {"cursor": "x" * 513}])
def test_invalid_or_unbounded_queries_are_safe_422(api, params):
    response = api[1].get("/api/audit/admin", params=params, headers=ADMIN)
    assert response.status_code == 422
    assert "SECRET" not in response.text


def test_default_time_range_excludes_older_than_seven_days(api):
    seed(api, 1, stamp=time.time() - 8 * 86400)
    response = api[1].get("/api/audit/admin", headers=ADMIN)
    assert response.status_code == 200 and response.json()["events"] == []


def test_equal_timestamp_cursor_pages_are_stable_without_skips_or_duplicates(api):
    seed(api, 5)
    observed, cursor = [], None
    for _ in range(3):
        params = {"limit": 2}
        if cursor:
            params["cursor"] = cursor
        response = api[1].get("/api/audit/admin", params=params, headers=ADMIN)
        assert response.status_code == 200
        body = response.json(); observed.extend(item["eventId"] for item in body["events"])
        cursor = body["nextCursor"]
    assert observed == ["00000000-0000-0000-0000-000000000005", "00000000-0000-0000-0000-000000000004",
        "00000000-0000-0000-0000-000000000003", "00000000-0000-0000-0000-000000000002",
        "00000000-0000-0000-0000-000000000001"]
    assert cursor is None


@pytest.mark.parametrize("raw", ["not-base64!", "=", "e30", "eyJjcmVhdGVkQXQiOk5hTn0",
    base64.urlsafe_b64encode(b'{"createdAt":1,"eventId":"bad"}').decode().rstrip("="),
    base64.urlsafe_b64encode(b'{"createdAt":1,"eventId":"00000000-0000-0000-0000-000000000001","path":"SECRET"}').decode().rstrip("=")])
def test_cursor_rejects_noncanonical_or_unknown_fields(api, raw):
    response = api[1].get("/api/audit/admin", params={"cursor": raw}, headers=ADMIN)
    assert response.status_code == 422 and "SECRET" not in response.text


def test_status_shows_known_permanent_gap_and_unpersisted_count(api):
    store = api[0].state.runtime.audit_store
    store.note_failure("00000000-0000-0000-0000-000000000001")
    response = api[1].get("/api/audit/admin/status", headers=ADMIN)
    assert response.status_code == 200
    status = response.json()
    assert status["permanentGap"] and not status["complete"] and status["dropped"] == 1
    assert status["coverageStart"]["historicalAttemptsBackfilled"] is False
    assert not any(raw in response.text for raw in ("sessions.db", "audit-fallback.jsonl", "00000000-0000"))


def test_recover_accepts_no_arbitrary_file_path_and_preserves_gap(api):
    response = api[1].post("/api/audit/admin/recover", json={"path": "SECRET"}, headers=ADMIN)
    assert response.status_code == 422 and "SECRET" not in response.text
    response = api[1].post("/api/audit/admin/recover", headers=ADMIN)
    assert response.status_code == 200 and response.json()["remaining"] == 0


def test_inconsistent_mirrored_row_is_safe_unavailable_not_silently_returned(api):
    seed(api, 1)
    with runtime_context(api[0].state.runtime):
        conn = db._connect()
        try:
            conn.execute("UPDATE audit_events SET session_id='SECRET foreign session'"); conn.commit()
        finally:
            conn.close()
    response = api[1].get("/api/audit/admin", headers=ADMIN)
    assert response.status_code == 503 and response.json()["code"] == "audit_unavailable"
    assert "SECRET" not in response.text


def test_admin_recover_replays_real_safe_backlog_only_once(api, monkeypatch):
    import sqlite3
    store = api[0].state.runtime.audit_store; original = store.connect
    def unavailable():
        raise sqlite3.OperationalError("Synthetic offline outage")
    monkeypatch.setattr(store, "connect", unavailable)
    assert api[1].get("/health").status_code == 200
    assert store.status().fallbackCount == 1
    monkeypatch.setattr(store, "connect", original)
    first = api[1].post("/api/audit/admin/recover", headers=ADMIN)
    second = api[1].post("/api/audit/admin/recover", headers=ADMIN)
    assert first.status_code == second.status_code == 200
    assert first.json()["recovered"] == 1 and second.json()["recovered"] == 0
    assert first.json()["remaining"] == second.json()["remaining"] == 0
    assert store.status().fallbackCount == 0


def test_filtered_private_list_does_not_leak_events_into_public_catalog(api):
    seed(api, 3)
    private = api[1].get("/api/audit/admin", params={"eventType": "session_created"}, headers=ADMIN)
    assert private.status_code == 200 and private.json()["events"] == []
    public = api[1].get("/api/soups", headers={"x-site-token": "synthetic-site"})
    assert public.status_code == 200
    assert not any(field in public.text for field in ("eventId", "modelCalls", "reasonCode", "coverageStart", "details_json"))


def test_pending_admin_recovery_reports_actual_live_io_not_completed(api, monkeypatch):
    from threading import Event
    entered, release = Event(), Event(); store = api[0].state.runtime.audit_store
    original = store.recover_fallback
    def slow():
        entered.set(); assert release.wait(2)
        return original()
    monkeypatch.setattr(store, "recover_fallback", slow)
    try:
        response = api[1].post("/api/audit/admin/recover", headers=ADMIN)
        assert entered.is_set() and response.status_code == 202
        assert response.json() == {"state": "pending", "persisted": False}
        assert store.status().activeIO == 1 and not store.status().complete
    finally:
        release.set()


def test_exact_thirty_one_day_range_is_accepted_without_infinite_history(api):
    response = api[1].get("/api/audit/admin", params={"start": 100, "end": 2678500}, headers=ADMIN)
    assert response.status_code == 200 and response.json()["events"] == []
