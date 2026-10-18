"""Raw bounded-body behavior and independent token checks on synthetic inputs."""
import asyncio
import json
from uuid import UUID

import pytest
from fastapi import HTTPException
from starlette.middleware.cors import CORSMiddleware


def run_body(chunks, *, declared=None, cors=False):
    from app.request_guards import BodyLimitMiddleware
    called, received, sent = [], [], []

    async def downstream(scope, receive, send):
        called.append(1)
        while True:
            message = await receive()
            received.append(message.get("body", b""))
            if not message.get("more_body"):
                break
        await send({"type": "http.response.start", "status": 200, "headers": []})
        await send({"type": "http.response.body", "body": b"ok"})

    async def exercise():
        events = iter([{"type": "http.request", "body": body, "more_body": i < len(chunks) - 1}
                       for i, body in enumerate(chunks)])

        async def receive():
            return next(events)

        async def send(event):
            sent.append(event)

        headers = [] if declared is None else [(b"content-length", declared.encode())]
        if cors:
            headers.append((b"origin", b"http://synthetic.test"))
        scope = {"type": "http", "method": "POST", "path": "/api/chat", "headers": headers}
        guarded = BodyLimitMiddleware(downstream, max_bytes=32768)
        if cors:
            guarded = CORSMiddleware(guarded, allow_origins=["http://synthetic.test"])
        await guarded(scope, receive, send)

    asyncio.run(exercise())
    start = next(item for item in sent if item["type"] == "http.response.start")
    body = b"".join(item.get("body", b"") for item in sent if item["type"] == "http.response.body")
    return start, body, called, b"".join(received)


@pytest.mark.parametrize("chunks,declared", [
    ([b"x" * 32769], None), ([b"x" * 16384, b"y" * 16385], None),
    ([b"x" * 32769], "1"), ([b"small"], "32769"),
])
def test_oversized_declared_or_fragmented_actual_body_never_reaches_business_handler(chunks, declared):
    start, body, called, received = run_body(chunks, declared=declared)
    assert start["status"] == 413 and called == [] and received == b""
    parsed = json.loads(body)
    assert parsed["code"] == "request_body_too_large"
    UUID(parsed["requestId"])
    assert isinstance(parsed["detail"], str)
    assert b"xxxxxxxx" not in body


@pytest.mark.parametrize("chunks", [[b"x" * 32768], [b"x" * 16384, b"y" * 16384]])
def test_exact_body_boundary_is_preserved_and_forwarded_once(chunks):
    start, _, called, received = run_body(chunks, declared="32768")
    assert start["status"] == 200 and called == [1]
    assert received == b"".join(chunks)


@pytest.mark.parametrize("declared", ["-1", "NaN", "not-a-size"])
def test_invalid_content_length_is_safe_rejection_without_handler_side_effect(declared):
    start, body, called, _ = run_body([b"small"], declared=declared)
    assert start["status"] == 400 and called == []
    parsed = json.loads(body)
    assert parsed["code"] == "request_body_invalid"
    assert set(parsed) == {"detail", "code", "requestId"}
    assert declared not in parsed["detail"]


def test_body_rejection_retains_cors_when_guard_is_inside_cors_layer():
    start, _, called, _ = run_body([b"x" * 32769], cors=True)
    assert start["status"] == 413 and called == []
    assert (b"access-control-allow-origin", b"http://synthetic.test") in start["headers"]


@pytest.mark.parametrize("provided", [None, "", "synthetic-site", "wrong", "非 ASCII 猜测"])
def test_site_credential_and_wrong_admin_credential_never_grant_admin(runtime, provided):
    from app.config import Settings
    from app.request_guards import require_admin_token
    settings = Settings.for_test(runtime.settings.DATA_DIR, SITE_PASSWORD="synthetic-site", ADMIN_TOKEN="synthetic-admin")
    with pytest.raises(HTTPException) as error:
        require_admin_token(provided, settings)
    assert error.value.status_code == 401
    assert "synthetic-admin" not in error.value.detail


def test_absent_admin_configuration_disables_management_even_with_a_site_token(runtime):
    from app.config import Settings
    from app.request_guards import require_admin_token
    settings = Settings.for_test(runtime.settings.DATA_DIR, SITE_PASSWORD="synthetic-site")
    with pytest.raises(HTTPException) as error:
        require_admin_token("synthetic-site", settings)
    assert error.value.status_code == 503


def test_correct_admin_and_optional_site_unlock_are_separate(runtime):
    from app.config import Settings
    from app.request_guards import require_admin_token, require_site_token
    settings = Settings.for_test(runtime.settings.DATA_DIR, SITE_PASSWORD="synthetic-site", ADMIN_TOKEN="synthetic-admin")
    assert require_admin_token("synthetic-admin", settings) is None
    assert require_site_token("synthetic-site", settings) is None
    with pytest.raises(HTTPException) as error:
        require_site_token("synthetic-admin", settings)
    assert error.value.status_code == 401
    assert require_site_token(None, Settings.for_test(runtime.settings.DATA_DIR)) is None
