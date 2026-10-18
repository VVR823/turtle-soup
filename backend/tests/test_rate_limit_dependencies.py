"""Real isolated HTTP limits, no repeated accounting or route cross-talk."""
from contextlib import closing
from uuid import UUID

import pytest
from fastapi import HTTPException
from fastapi.testclient import TestClient

from app import db
from app.config import Settings
from app.main import create_app
from app.runtime import runtime_context
from .test_rate_limit_windows import FakeClock


def test_api_allows_thirty_not_fifteen_chat_requests_then_returns_retry_metadata(tmp_path):
    from app.rate_limit import SlidingWindowLimiter
    clock = FakeClock()
    app = create_app(Settings.for_test(tmp_path, RATE_LIMIT_ENABLED=True))
    with TestClient(app) as client:
        app.state.runtime.limiter = SlidingWindowLimiter(clock=clock)
        created = [client.post("/api/chat", json={"soupId": "xin"}) for _ in range(30)]
        assert all(response.status_code == 200 for response in created)
        denied = client.post("/api/chat", json={"soupId": "xin"})
        assert denied.status_code == 429 and denied.headers["Retry-After"] == "60"
        assert denied.json()["code"] == "rate_limited"
        UUID(denied.json()["requestId"])
        session_id = created[0].json()["sessionId"]
        assert client.get(f"/api/session/{session_id}").status_code == 200
        clock.now = 60
        assert client.post("/api/chat", json={"soupId": "xin"}).status_code == 200


def test_repeated_same_dependency_on_one_scope_is_counted_only_once(runtime):
    from starlette.requests import Request
    from dataclasses import replace
    from app.rate_limit import RatePolicy, SlidingWindowLimiter, rate_limits
    from app.runtime import Runtime
    active = Runtime(replace(runtime.settings, RATE_LIMIT_ENABLED=True), model=runtime.model)
    active.limiter = SlidingWindowLimiter(clock=FakeClock())
    dependency = rate_limits((RatePolicy("single", 1, 60),))

    def request():
        return Request({"type": "http", "method": "GET", "path": "/api/synthetic",
                        "headers": [], "client": ("198.51.100.1", 10000)})

    with runtime_context(active):
        same = request()
        assert dependency(same) is None
        assert dependency(same) is None
        with pytest.raises(HTTPException) as error:
            dependency(request())
        assert error.value.status_code == 429


@pytest.mark.parametrize("size,status", [(32768, 200), (32769, 413)])
def test_actual_app_rejects_oversized_input_before_schema_or_game_creation(tmp_path, size, status):
    app = create_app(Settings.for_test(tmp_path))
    head = b'{"soupId":"xin"}'
    body = head + b" " * (size - len(head))
    with TestClient(app) as client:
        response = client.post("/api/chat", content=body, headers={"Content-Type": "application/json"})
        assert response.status_code == status
        if status == 413:
            assert response.json()["code"] == "request_body_too_large"
        with runtime_context(app.state.runtime), closing(db._connect()) as conn, conn:
            assert conn.execute("SELECT COUNT(*) FROM sessions").fetchone()[0] == (1 if status == 200 else 0)


@pytest.mark.parametrize("network", ["not-a-network", "0.0.0.0/0", "::/0"])
def test_invalid_or_trust_all_proxy_config_is_not_silently_enabled(tmp_path, network):
    with pytest.raises(ValueError):
        Settings.for_test(tmp_path, TRUSTED_PROXY_CIDRS=(network,))
