"""Permanent review repros: usable retry, actual launch parsing and boundaries."""
import asyncio
import importlib
import importlib.util
from pathlib import Path
import re
import shlex
import tracemalloc

from click.testing import CliRunner
import pytest
from starlette.requests import Request
from uvicorn.middleware.proxy_headers import ProxyHeadersMiddleware

from app.config import Settings
from app.rate_limit import client_ip
from app.rate_policy import RatePolicy, SlidingWindowLimiter
from app.request_guards import BodyLimitMiddleware
from app.runtime import Runtime, runtime_context

ROOT = Path(__file__).resolve().parents[2]


def test_capacity_retry_counts_only_nonrequested_keys_that_release_net_room():
    now = [0.0]
    limiter = SlidingWindowLimiter(clock=lambda: now[0], max_keys=2)
    minute, hour = RatePolicy("minute", 30, 60), RatePolicy("hour", 300, 3600)
    assert limiter.check("returning", "/api/chat", (minute,)).allowed
    assert limiter.check("other", "/api/chat", (hour,)).allowed
    denied = limiter.check("returning", "/api/chat", (minute, hour))
    assert not denied.allowed and denied.retryAfterSeconds == 3600
    now[0] = 3599.999
    assert not limiter.check("returning", "/api/chat", (minute, hour)).allowed
    now[0] = 3600
    assert limiter.check("returning", "/api/chat", (minute, hour)).allowed


def test_full_window_and_capacity_report_the_combined_usable_retry():
    now = [0.0]
    limiter = SlidingWindowLimiter(clock=lambda: now[0], max_keys=2)
    minute, hour = RatePolicy("minute", 1, 60), RatePolicy("hour", 300, 3600)
    assert limiter.check("returning", "/api/chat", (minute,)).allowed
    assert limiter.check("other", "/api/chat", (hour,)).allowed
    denied = limiter.check("returning", "/api/chat", (minute, hour))
    assert not denied.allowed and denied.retryAfterSeconds == 3600
    now[0] = denied.retryAfterSeconds
    assert limiter.check("returning", "/api/chat", (minute, hour)).allowed


def test_impossible_policy_set_is_configuration_error_not_endless_retry_advice():
    limiter = SlidingWindowLimiter(max_keys=2)
    with pytest.raises(ValueError):
        limiter.check("synthetic", "/api/chat", tuple(RatePolicy(str(i), 1, 60) for i in range(3)))
    assert limiter.snapshot()["keys"] == 0


def launch_options(path, tmp_path, monkeypatch):
    text = path.read_text(encoding="utf-8")
    if path.suffix == ".md":
        command = re.search(r"`((?:uvicorn app\.main:app|python scripts/run-backend\.py)[^`]*)`", text)
        assert command, "No documented supported backend command"
        args = shlex.split(command.group(1))
    else:
        command = re.search(r"^ExecStart=(.+uvicorn app\.main:app[^\n]*)$", text, re.MULTILINE)
        assert command, "No service entry in historical template"
        args = shlex.split(command.group(1))
    if args[0] == "python":
        spec = importlib.util.spec_from_file_location("review_owned_launcher", ROOT / args[1])
        module = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(module)
        return module.build_launch_config(Settings.for_test(tmp_path))
    # Consume the real installed CLI parser, but replace only the service-start
    # boundary. No server/app/config/private files are loaded by this probe.
    cli = importlib.import_module("uvicorn.main")
    captured = {}
    monkeypatch.setattr(cli, "run", lambda app, **options: captured.update(options))
    result = CliRunner().invoke(cli.main, args[1:])
    assert result.exit_code == 0, result.output
    return captured


@pytest.mark.parametrize("relative", ["README.md", "backend/README.md", "deploy/finish.sh",
                                      "deploy/setup_server.sh", "deploy/server_setup.sh"])
def test_supported_launch_paths_do_not_pretrust_forged_proxy_identity(relative, tmp_path, monkeypatch):
    options = launch_options(ROOT / relative, tmp_path, monkeypatch)
    active = Runtime(Settings.for_test(tmp_path, RATE_LIMIT_ENABLED=True))
    identities, admitted = [], []

    async def downstream(scope, receive, send):
        identity = client_ip(Request(scope))
        identities.append(identity)
        admitted.append(active.limiter.check(identity, "POST:/api/chat", (RatePolicy("one", 1, 60),)).allowed)

    async def forbidden():
        raise AssertionError("Launch policy probe must not perform I/O")

    async def exercise():
        target = (ProxyHeadersMiddleware(downstream, trusted_hosts="127.0.0.1")
                  if options["proxy_headers"] else downstream)
        with runtime_context(active):
            for claimed in (b"198.51.100.1", b"198.51.100.2"):
                scope = {"type": "http", "client": ("127.0.0.1", 12345), "method": "POST",
                         "path": "/api/chat", "headers": [(b"x-forwarded-for", claimed)]}
                await target(scope, forbidden, forbidden)

    asyncio.run(exercise())
    assert identities == ["127.0.0.1", "127.0.0.1"]
    assert admitted == [True, False]


def test_known_reused_site_and_admin_secret_is_rejected_before_runtime(tmp_path):
    with pytest.raises(ValueError):
        Settings.for_test(tmp_path, SITE_PASSWORD="synthetic-reused", ADMIN_TOKEN="synthetic-reused")
    assert Settings.for_test(tmp_path).ADMIN_TOKEN == ""  # absent config remains disabled


def test_empty_asgi_frames_cannot_accumulate_unbounded_fragment_metadata():
    seen = []
    frames = 0

    async def receive():
        nonlocal frames
        frames += 1
        return {"type": "http.request", "body": b"" if frames <= 50000 else b"x",
                "more_body": frames <= 50000}

    async def downstream(scope, bounded_receive, send):
        seen.append((await bounded_receive())["body"])

    async def forbidden(message):
        raise AssertionError("A valid tiny body must not be rejected")

    middleware = BodyLimitMiddleware(downstream)
    # Warm event-loop/guard traceback source caches outside the measurement;
    # one-time imports are not middleware fragment memory.
    async def warm_receive():
        return {"type": "http.request", "body": b"x", "more_body": False}

    asyncio.run(middleware({"type": "http", "headers": []}, warm_receive, forbidden))
    seen.clear()
    tracemalloc.start()
    try:
        asyncio.run(middleware({"type": "http", "headers": []}, receive, forbidden))
        _, peak = tracemalloc.get_traced_memory()
    finally:
        tracemalloc.stop()
    assert seen == [b"x"] and frames == 50001
    assert peak < 131072, f"Empty-frame metadata exceeded bounded synthetic memory budget: {peak}"
