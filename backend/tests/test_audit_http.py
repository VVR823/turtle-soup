"""Real ASGI/SQLite boundaries; no private config or real provider calls."""
import json
import sqlite3
from dataclasses import replace
from uuid import uuid4

import pytest
from fastapi.testclient import TestClient

from app import db, game_service
from app.audit_events import AuditEvent
from app.config import Settings
from app.main import create_app
from app.runtime import runtime_context
from app.schemas import Checkpoint, DifficultyLimits, Soup
from app.testing import FakeModel


def puzzle():
    return Soup(id="audit-api", title="Public", surface="小明和小红。", bottom="PRIVATE FACT 小明是凶手。",
        checkpoints=[Checkpoint(key="小明是凶手", answer=True)],
        difficultyLimits=DifficultyLimits(xuermu=4, baozi=4, tianyi=4))


@pytest.fixture
def api(tmp_path):
    app = create_app(Settings.for_test(tmp_path / "audit-http"), model=FakeModel("是"), soups=[puzzle()])
    with TestClient(app, raise_server_exceptions=False) as client:
        yield app, client


def events(api, event_type="http_attempt"):
    with runtime_context(api[0].state.runtime):
        conn = db._connect()
        try:
            return [AuditEvent.model_validate_json(row[0]) for row in conn.execute(
                "SELECT details_json FROM audit_events WHERE event_type=? ORDER BY rowid", (event_type,))]
        finally:
            conn.close()


def create(api, request=None):
    response = api[1].post("/api/chat", json={"soupId": "audit-api", "requestId": request or str(uuid4())})
    assert response.status_code == 200, response.text
    return response.json()["sessionId"]


def ask(api, sid, question="小明是凶手吗？", request=None):
    return api[1].post("/api/chat", json={"sessionId": sid, "question": question, "requestId": request or str(uuid4())})


def test_two_same_http_requests_two_attempts_one_turn(api):
    sid = create(api); request = str(uuid4())
    first, second = ask(api, sid, request=request), ask(api, sid, request=request)
    assert first.status_code == second.status_code == 200 and first.content == second.content
    selected = [item for item in events(api) if item.requestId == request]
    assert len(selected) == 2 and selected[0].eventId != selected[1].eventId
    assert selected[0].turnId == selected[1].turnId == first.json()["turnId"]
    assert selected[0].sessionId == selected[1].sessionId == sid
    assert selected[0].details.replayed is False and selected[1].details.replayed is True
    assert selected[0].details.charged is selected[1].details.charged is True
    assert len(events(api, "turn_committed")) == 1
    with runtime_context(api[0].state.runtime):
        assert db.get_session(sid)["questionsAsked"] == 1


def test_creation_restore_reveal_attempts_link_actual_ids(api):
    request = str(uuid4()); sid = create(api, request)
    assert api[1].get(f"/api/session/{sid}").status_code == 200
    assert api[1].post("/api/evaluate", json={"sessionId": sid}).status_code == 200
    assert api[1].post("/api/evaluate", json={"sessionId": sid}).status_code == 200
    selected = events(api)
    assert len(selected) == 4 and all(item.sessionId == sid for item in selected)
    assert selected[0].requestId == request and selected[1].requestId is None
    assert selected[1].details.reasonCode == "session_restored"
    assert selected[1].details.versions.engineVersion == "unversioned"
    assert selected[2].details.reasonCode == "evaluation_created"
    assert not selected[2].details.replayed and selected[3].details.replayed
    assert len(events(api, "evaluation_created")) == 1
    assert all(item.turnId is None and item.details.usage.totalTokens is None for item in selected)


def test_cache_hit_and_replay_do_not_manufacture_model_calls(api):
    a, b = create(api), create(api)
    assert ask(api, a).status_code == 200
    request = str(uuid4()); response = ask(api, b, request=request)
    assert ask(api, b, request=request).content == response.content
    selected = [item for item in events(api) if item.requestId == request]
    assert len(selected) == 2 and all(item.details.cacheHit for item in selected)
    assert all(item.details.source == "deterministic" and item.details.modelCalls == () for item in selected)
    assert all(item.details.usage.totalTokens is None for item in selected)
    assert api[0].state.runtime.model.calls == []


def test_model_attempt_has_unknown_usage_without_fake_zero_and_replay_has_no_calls(api):
    sid = create(api); request = str(uuid4())
    first = ask(api, sid, "他是凶手吗？", request)
    assert first.status_code == 200
    assert ask(api, sid, "他是凶手吗？", request).content == first.content
    first_event, replay = [item for item in events(api) if item.requestId == request]
    assert len(first_event.details.modelCalls) == 1
    assert first_event.details.modelCalls[0].status == "succeeded"
    assert first_event.details.modelCalls[0].usageStatus == "unknown"
    assert first_event.details.usage.totalTokens is None
    assert replay.details.modelCalls == () and replay.details.usage.totalTokens is None
    assert first_event.details.source == replay.details.source == "llm"


def test_model_failure_is_a_recorded_noncharged_attempt(api, monkeypatch):
    sid = create(api)
    def unavailable(*args, **kwargs):
        raise RuntimeError("SECRET provider question")
    monkeypatch.setattr(game_service.ai_host, "handle_host_response", unavailable)
    response = ask(api, sid)
    assert response.status_code == 503
    item = events(api)[-1]
    assert item.details.statusCode == 503 and item.details.outcome == "error"
    assert item.details.charged is False and item.details.reasonCode == "model_unavailable"
    assert "SECRET" not in item.model_dump_json() and "SECRET" not in response.text


@pytest.mark.parametrize("method,path,kwargs,status", [
    ("post", "/api/chat", {"content": "{", "headers": {"content-type": "application/json"}}, 422),
    ("post", "/api/chat", {"json": {"question": "PRIVATE INVALID", "requestId": "bad"}}, 422),
    ("post", "/api/chat", {"json": {"soupId": "audit-api"}, "headers": {"content-length": "40000"}}, 413),
    ("get", "/api/session/SECRET-NOT-A-SESSION", {}, 404),
    ("get", "/unknown/SECRET-PATH?q=SECRET-QUERY", {}, 404),
])
def test_guard_body_validation_and_unmatched_paths_are_recorded_without_raw_text(api, method, path, kwargs, status):
    response = getattr(api[1], method)(path, **kwargs)
    assert response.status_code == status
    selected = events(api)
    assert len(selected) == 1
    item = selected[0]
    assert item.details.statusCode == status and item.details.outcome == "rejected"
    assert item.requestId is None and item.sessionId is None
    assert item.details.routeTemplate == ("unmatched" if path.startswith("/unknown") else
        "/api/session/{session_id}" if path.startswith("/api/session/") else "/api/chat")
    assert not any(value in item.model_dump_json() for value in ("SECRET", "PRIVATE INVALID"))


def test_wrong_auth_and_rate_rejections_each_leave_an_attempt(tmp_path):
    settings = replace(Settings.for_test(tmp_path), SITE_PASSWORD="synthetic-site", RATE_LIMIT_ENABLED=True)
    app = create_app(settings, model=FakeModel(), soups=[puzzle()])
    with TestClient(app) as client:
        api = app, client
        assert client.get("/api/soups", headers={"x-site-token": "PRIVATE WRONG"}).status_code == 401
        body = {"soupId": "audit-api", "requestId": str(uuid4())}
        responses = [client.post("/api/chat", json=body, headers={"x-site-token": "synthetic-site"}) for _ in range(31)]
        assert responses[-1].status_code == 429
        selected = events(api)
        assert len(selected) == 32 and [item.details.statusCode for item in selected] == [401] + [item.status_code for item in responses]
        assert "PRIVATE WRONG" not in str(selected)
        assert len(events(api, "session_created")) == 1


def test_cors_preflight_is_recorded_without_parsing_headers(api):
    response = api[1].options("/api/chat", headers={"origin": "http://localhost:3000", "access-control-request-method": "POST"})
    assert response.status_code == 200
    item = events(api)[0]
    assert item.details.method == "OPTIONS" and item.details.routeTemplate == "/api/chat"
    assert item.details.statusCode == 200 and item.requestId is None
    assert "localhost" not in item.model_dump_json()


def test_external_attempt_failure_after_commit_preserves_response_and_count(api, monkeypatch, capsys):
    sid = create(api); store = api[0].state.runtime.audit_store
    def fail_db():
        raise sqlite3.OperationalError("SECRET database question")
    def fail_file(*args):
        raise OSError("SECRET path reply")
    monkeypatch.setattr(store, "connect", fail_db)
    monkeypatch.setattr(store, "_append_fallback", fail_file)
    request = str(uuid4()); response = ask(api, sid, request=request)
    assert response.status_code == 200
    assert ask(api, sid, request=request).content == response.content
    with runtime_context(api[0].state.runtime):
        assert db.get_session(sid)["questionsAsked"] == 1
    assert len(events(api, "turn_committed")) == 1
    assert store.status().memoryCount == 2 and not store.status().complete
    assert "SECRET" not in response.text and "SECRET" not in capsys.readouterr().err


def test_unexpected_store_failure_cannot_turn_committed_answer_into_failure(api, monkeypatch, capsys):
    sid = create(api); store = api[0].state.runtime.audit_store
    async def broken(*args, **kwargs):
        raise RuntimeError("SECRET persistence internals")
    monkeypatch.setattr(store, "save_attempt", broken)
    response = ask(api, sid)
    assert response.status_code == 200
    with runtime_context(api[0].state.runtime):
        assert db.get_session(sid)["questionsAsked"] == 1
    assert store.status().permanentGap and store.status().dropped == 1
    assert "SECRET" not in capsys.readouterr().err


def test_unknown_error_status_not_fake_200(api, monkeypatch):
    sid = create(api)
    def broken(*args, **kwargs):
        raise RuntimeError("SECRET unhandled")
    monkeypatch.setattr(game_service, "ask", broken)
    response = ask(api, sid)
    assert response.status_code == 500
    item = events(api)[-1]
    assert item.details.statusCode is None and item.details.responseStarted is False
    assert item.details.outcome == "error" and item.details.charged is None
    assert "SECRET" not in response.text and "SECRET" not in item.model_dump_json()


def test_business_audit_failure_is_safe_503_and_rolls_back_creation(api, monkeypatch):
    from app import audit_store
    def denied(*args):
        raise audit_store.AuditPersistenceError("SECRET business database")
    monkeypatch.setattr(audit_store, "insert_business_event", denied)
    response = api[1].post("/api/chat", json={"soupId": "audit-api", "requestId": str(uuid4())})
    assert response.status_code == 503 and response.json()["code"] == "audit_unavailable"
    assert "SECRET" not in response.text
    item = events(api)[-1]
    assert item.details.statusCode == 503 and item.sessionId is None and item.details.charged is None
    assert events(api, "session_created") == []


def test_creation_replay_preserves_known_test_traffic_class(api):
    request = str(uuid4()); sid = create(api, request)
    assert create(api, request) == sid
    assert [item.details.trafficClass for item in events(api)] == ["test", "test"]


def test_startup_recovers_safe_fallback_without_manufacturing_old_http_coverage(runtime):
    from app.audit_context import AttemptCollector
    from app.audit_store import AuditStore
    runtime.soups = [puzzle()]; db.initialize()
    item = AttemptCollector(str(uuid4()), traffic_class="test").finish(status_code=200, method="GET",
        route_template="/health", response_started=True, disconnected=False)
    def fail_db():
        raise sqlite3.OperationalError("Synthetic offline outage")
    old = AuditStore(runtime.settings.DATA_DIR, connect=fail_db)
    assert old.record_attempt(item).storage == "fallback"
    app = create_app(runtime.settings, model=FakeModel(), soups=[puzzle()])
    with TestClient(app) as client:
        selected = events((app, client))
        assert len(selected) == 1 and selected[0] == item
        assert app.state.runtime.audit_store.status().fallbackCount == 0
        assert app.state.runtime.audit_store.status().coverageStart["historicalAttemptsBackfilled"] is False


def test_shutdown_flushes_owned_memory_with_explicit_runtime_not_standalone(tmp_path, monkeypatch):
    app = create_app(Settings.for_test(tmp_path / "owned-audit"), model=FakeModel(), soups=[puzzle()])
    with TestClient(app) as client:
        api = app, client; sid = create(api)
        store = app.state.runtime.audit_store; original = store.connect
        def fail_db():
            raise sqlite3.OperationalError("Synthetic offline outage")
        def fail_file(*args):
            raise OSError("Synthetic offline failure")
        monkeypatch.setattr(store, "connect", fail_db)
        monkeypatch.setattr(store, "_append_fallback", fail_file)
        assert ask(api, sid).status_code == 200
        assert store.status().memoryCount == 1
        monkeypatch.setattr(store, "connect", original)
    assert store.status().memoryCount == 0
    assert app.state.runtime.audit_shutdown["residualJobs"] == 0
    with runtime_context(app.state.runtime):
        conn = db._connect()
        try:
            assert conn.execute("SELECT COUNT(*) FROM audit_events WHERE event_type='http_attempt'").fetchone()[0] == 2
        finally:
            conn.close()
