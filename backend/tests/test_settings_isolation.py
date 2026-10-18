"""TS-01 guardrails, not a model-quality or production-migration benchmark."""
from contextlib import closing
import asyncio
import builtins
import os
import socket
import sqlite3
import subprocess
import sys
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
from types import SimpleNamespace

import pytest
from fastapi.testclient import TestClient

from app import ai_host, config, db
from app.config import Settings, load_settings
from app.main import create_app
from app.runtime import Runtime, get_runtime, runtime_context
from app.testing import FakeModel
from testing.guards import NetworkGuard, TestAccessBlocked, protect_runtime_files, validate_basetemp
from .conftest import run_qa


@pytest.fixture
def network_guard():
    # Guard tests must remain safe even when the outer suite explicitly opts in.
    with pytest.MonkeyPatch.context() as patch:
        guard = NetworkGuard()
        guard.install(patch)
        yield guard


def test_config_explicit_does_not_read_dotenv(monkeypatch):
    import dotenv

    def forbidden(*args, **kwargs):
        raise AssertionError("dotenv must not be read")

    monkeypatch.setattr(dotenv, "dotenv_values", forbidden)
    settings = load_settings(environ={}, load_env=False)
    assert settings.ZHIPU_API_KEY == ""
    assert settings.SITE_PASSWORD == ""


@pytest.mark.parametrize("answer", ["", "不知道", "YES", None, True])
def test_fake_model_rejects_outputs_outside_the_five_class_contract(answer):
    with pytest.raises(ValueError, match="five-class"):
        FakeModel(answer)


def test_environment_precedence_without_process_mutation(tmp_path, monkeypatch):
    import dotenv
    backend = tmp_path / "backend"
    source = {
        tmp_path / ".env.local": {"ZHIPU_MODEL": "root-model", "SITE_PASSWORD": "root"},
        backend / ".env": {"ZHIPU_MODEL": "backend-model", "SITE_PASSWORD": "backend"},
    }
    monkeypatch.setattr(dotenv, "dotenv_values", lambda path, **kwargs: source[Path(path)])
    monkeypatch.delenv("SITE_PASSWORD", raising=False)
    settings = load_settings(environ={"ZHIPU_MODEL": "process-model"}, backend_dir=backend)
    assert settings.ZHIPU_MODEL == "process-model"
    assert settings.SITE_PASSWORD == "backend"
    assert "SITE_PASSWORD" not in os.environ


def test_interpolation_respects_explicit_environment_and_previous_file(tmp_path, monkeypatch):
    import dotenv
    backend = tmp_path / "backend"
    sources = {
        backend / ".env": {"OLLAMA_MODEL": "file-model", "QWEN_MODEL": "${OLLAMA_MODEL}"},
        tmp_path / ".env.local": {"ZHIPU_MODEL": "${QWEN_MODEL}", "SILICONFLOW_MODEL": "${UNDEFINED:-fallback}"},
    }
    monkeypatch.setenv("OLLAMA_MODEL", "inherited-but-not-supplied")
    monkeypatch.setattr(dotenv, "dotenv_values", lambda path, **kwargs: sources[Path(path)])
    settings = load_settings(environ={"OLLAMA_MODEL": "process-model"}, backend_dir=backend)
    assert settings.OLLAMA_MODEL == settings.QWEN_MODEL == settings.ZHIPU_MODEL == "process-model"
    assert settings.SILICONFLOW_MODEL == "fallback"
    assert os.environ["OLLAMA_MODEL"] == "inherited-but-not-supplied"


def test_blank_cors_preserves_local_development_defaults():
    settings = load_settings(environ={"CORS_ORIGINS": ""}, load_env=False)
    assert settings.CORS_ORIGINS == Settings().CORS_ORIGINS


def test_explicit_cli_crud_initializes_fresh_storage(runtime):
    assert not runtime.initialized
    session = db.create_session("xin")
    assert runtime.initialized
    assert db.get_session(session["id"])["soupId"] == "xin"


@pytest.mark.parametrize("key", ["TURTLE_SOUP_TESTING", "ENABLE_TRACE", "RATE_LIMIT_ENABLED"])
def test_invalid_boolean_rejected(key):
    with pytest.raises(ValueError, match="must be 0 or 1"):
        load_settings(environ={key: "maybe"}, load_env=False)


@pytest.mark.parametrize("path", [config.BACKEND_DIR / "data", config.PROJECT_ROOT / "data" / "nested"])
def test_test_settings_reject_runtime_directory(path):
    with pytest.raises(ValueError, match="temporary"):
        Settings.for_test(path)


@pytest.mark.skipif(os.name != "nt", reason="Windows extended paths only")
@pytest.mark.parametrize("namespace", ["?", "."])
def test_windows_path_aliases_cannot_bypass_settings_or_file_guard(namespace):
    prefix = f"{chr(92) * 2}{namespace}{chr(92)}"
    alias = Path(prefix + str(config.BACKEND_DIR / "data"))
    with pytest.raises(ValueError, match="temporary"):
        Settings.for_test(alias)
    with pytest.raises(TestAccessBlocked):
        builtins.open(alias / "sessions.db", "rb")


def test_windows_namespace_normalization_without_io():
    from app.paths import _strip_windows_namespace
    assert _strip_windows_namespace("\\\\?\\D:\\synthetic") == "D:\\synthetic"
    assert _strip_windows_namespace("\\\\.\\D:\\synthetic") == "D:\\synthetic"
    assert _strip_windows_namespace("\\\\?\\UNC\\server\\share") == "\\\\server\\share"
    assert _strip_windows_namespace("\\\\.\\nul") == "\\\\.\\NUL"
    with pytest.raises(ValueError, match="namespace"):
        _strip_windows_namespace("\\\\?\\GLOBALROOT\\Device\\synthetic")


def test_secret_fields_excluded_from_repr(tmp_path):
    settings = Settings.for_test(tmp_path, ZHIPU_API_KEY="synthetic-key", ADMIN_TOKEN="synthetic-admin")
    assert "synthetic-key" not in repr(settings)
    assert "synthetic-admin" not in repr(settings)


def test_testing_environment_forces_dotenv_off(tmp_path, monkeypatch):
    import dotenv
    def forbidden(*args, **kwargs):
        raise AssertionError("Testing environment must never load dotenv")
    monkeypatch.setattr(dotenv, "dotenv_values", forbidden)
    settings = load_settings(environ={
        "TURTLE_SOUP_TESTING": "1", "TURTLE_SOUP_DATA_DIR": str(tmp_path),
    })
    assert settings.TESTING and settings.LLM_PROVIDER == "fake"
    assert not settings.ALLOW_REAL_MODEL and not settings.LOAD_RUNTIME_PUZZLES


def test_factory_is_pure_and_lifespan_owns_storage(tmp_path):
    path = tmp_path / "isolated"
    app = create_app(Settings.for_test(path))
    assert not path.exists()
    assert app.state.runtime is None
    with TestClient(app) as client:
        assert client.get("/health").status_code == 200
        active = app.state.runtime
        assert active.initialized and not active.closed
        assert (path / "sessions.db").exists()
    assert active.closed
    assert not active.host_cache and not active.llm_cache


def test_request_without_lifespan_fails_closed(tmp_path):
    app = create_app(Settings.for_test(tmp_path / "unused"))
    client = TestClient(app)
    try:
        response = client.get("/health")
        assert response.status_code == 503
        assert response.json()["code"] == "app_not_started"
    finally:
        client.close()
    assert not (tmp_path / "unused").exists()


def test_startup_failure_closes_owned_runtime(tmp_path, monkeypatch):
    def fail():
        raise RuntimeError("synthetic initialization failure")
    monkeypatch.setattr(db, "initialize", fail)
    app = create_app(Settings.for_test(tmp_path / "unused"))
    with pytest.raises(RuntimeError, match="initialization failure"):
        with TestClient(app):
            pass
    assert app.state.runtime.closed
    assert not app.state.runtime.initialized


def test_partial_startup_closes_transports_and_restores_context(runtime, tmp_path, monkeypatch):
    closed = []
    class SyncTransport:
        def close(self):
            closed.append("sync")
    class AsyncTransport:
        async def aclose(self):
            closed.append("async")
    def fail():
        active = get_runtime()
        active.http_client = SyncTransport()
        active.http_async_client = AsyncTransport()
        raise RuntimeError("partial startup")
    monkeypatch.setattr(db, "initialize", fail)
    app = create_app(Settings.for_test(tmp_path / "partial"))
    with pytest.raises(RuntimeError, match="partial startup"):
        with TestClient(app):
            pass
    assert closed == ["sync", "async"]
    assert app.state.runtime.closed
    assert get_runtime() is runtime


def test_lifespan_async_close_failure_still_clears_owned_state(runtime, tmp_path):
    class BrokenAsyncTransport:
        async def aclose(self):
            raise RuntimeError("async shutdown failure")
    app = create_app(Settings.for_test(tmp_path / "broken-close"))
    with pytest.raises(RuntimeError, match="async shutdown failure"):
        with TestClient(app):
            app.state.runtime.http_async_client = BrokenAsyncTransport()
            app.state.runtime.host_cache["synthetic"] = "value"
    assert app.state.runtime.closed and not app.state.runtime.host_cache
    assert get_runtime() is runtime


def test_closed_app_fails_closed_and_restart_owns_new_runtime(tmp_path):
    app = create_app(Settings.for_test(tmp_path / "restart"))
    with TestClient(app) as client:
        previous = app.state.runtime
        session = client.post("/api/chat", json={"soupId": "xin"}).json()["sessionId"]
        previous.host_cache["synthetic"] = "old"
    with TestClient(app) as client:
        active = app.state.runtime
        assert active is not previous and previous.closed
        assert active.model is not previous.model
        assert not active.host_cache
        assert client.get(f"/api/session/{session}").status_code == 200
    inactive = TestClient(app)
    try:
        assert inactive.get("/health").status_code == 503
    finally:
        inactive.close()


def test_injected_catalog_is_copied_for_each_app(tmp_path):
    soup = db.get_soup_by_id("xin").model_copy(deep=True)
    original = soup.title
    first = create_app(Settings.for_test(tmp_path / "first"), soups=[soup])
    second = create_app(Settings.for_test(tmp_path / "second"), soups=[soup])
    with TestClient(first), TestClient(second):
        first.state.runtime.soups[0].title = "synthetic changed title"
        assert second.state.runtime.soups[0].title == original
        assert soup.title == original


def test_cors_and_site_credentials_are_app_local(tmp_path):
    first = create_app(Settings.for_test(
        tmp_path / "first", SITE_PASSWORD="first-site", CORS_ORIGINS=("http://first.invalid",),
    ))
    second = create_app(Settings.for_test(
        tmp_path / "second", SITE_PASSWORD="second-site", CORS_ORIGINS=("http://second.invalid",),
    ))
    with TestClient(first) as a, TestClient(second) as b:
        for client, allowed, forbidden, token in (
            (a, "http://first.invalid", "http://second.invalid", "first-site"),
            (b, "http://second.invalid", "http://first.invalid", "second-site"),
        ):
            headers = {"Origin": allowed, "X-Site-Token": token}
            response = client.get("/api/soups", headers=headers)
            assert response.status_code == 200
            assert response.headers["access-control-allow-origin"] == allowed
            assert "access-control-allow-origin" not in client.get("/health", headers={"Origin": forbidden}).headers
            assert client.get("/api/soups", headers={"X-Site-Token": "wrong"}).status_code == 401


def test_import_has_no_configuration_db_or_transport_side_effects(tmp_path):
    # A fresh child interpreter avoids a falsely passing already-imported module.
    script = '''
import builtins, io, pathlib, sqlite3, dotenv, httpx
import pytest
from testing.guards import NetworkGuard, protect_runtime_files
patch = pytest.MonkeyPatch()
NetworkGuard().install(patch)
protect_runtime_files(patch, pathlib.Path.cwd())
def forbidden(*args, **kwargs):
    raise AssertionError('Import performed I/O initialization')
dotenv.load_dotenv = forbidden
dotenv.dotenv_values = forbidden
sqlite3.connect = forbidden
httpx.Client.__init__ = forbidden
httpx.AsyncClient.__init__ = forbidden
original = builtins.open
def guarded(path, *args, **kwargs):
    if not isinstance(path, int):
        name = str(path).replace(chr(92), '/')
        if '/backend/data/' in name or name.endswith(('/.env', '/.env.local')):
            raise AssertionError('Import read real data/configuration')
    return original(path, *args, **kwargs)
builtins.open = guarded
io.open = guarded
import app.main
assert app.main.app.state.runtime is None
'''
    environment = dict(os.environ, PYTHONDONTWRITEBYTECODE="1", TURTLE_SOUP_DATA_DIR=str(tmp_path / "unused"))
    result = subprocess.run([sys.executable, "-c", script], env=environment, capture_output=True, text=True, timeout=30)
    assert result.returncode == 0, result.stderr
    assert not (tmp_path / "unused").exists()


def test_two_apps_do_not_share_database_credentials_cache_or_model(tmp_path, monkeypatch):
    def scripted_host(soup, history, question, *, versions=None):
        from app.schemas import HostResult
        return HostResult(kind="answer", answer=get_runtime().model.answer, chargeable=True,
                          source="deterministic", reply=get_runtime().model.answer, matchedCheckpoint="test-rule",
                          versions=versions)

    monkeypatch.setattr(ai_host, "handle_host_response", scripted_host)
    first = create_app(Settings.for_test(tmp_path / "first", ADMIN_TOKEN="first"), model=FakeModel("是"))
    second = create_app(Settings.for_test(tmp_path / "second", ADMIN_TOKEN="second"), model=FakeModel("不是"))
    with TestClient(first) as a, TestClient(second) as b:
        a_id = a.post("/api/chat", json={"soupId": "xin", "level": "tianyi"}).json()["sessionId"]
        b_id = b.post("/api/chat", json={"soupId": "xin", "level": "tianyi"}).json()["sessionId"]
        assert b.get(f"/api/session/{a_id}").status_code == 404
        assert a.get("/api/feedback/admin", headers={"X-Admin-Token": "second"}).status_code == 401
        assert b.get("/api/feedback/admin", headers={"X-Admin-Token": "second"}).status_code == 200
        def ask(client, session_id):
            return client.post("/api/chat", json={"sessionId": session_id, "question": "相同测试问题吗？"}).json()["reply"]
        with ThreadPoolExecutor(max_workers=2) as pool:
            ra = pool.submit(ask, a, a_id)
            rb = pool.submit(ask, b, b_id)
            assert ra.result() == "是"
            assert rb.result() == "不是"
        assert first.state.runtime.host_cache is not second.state.runtime.host_cache
        assert first.state.runtime.limiter is not second.state.runtime.limiter


def test_model_substitute_uses_scripted_output_not_gold_labels(runtime):
    soup = db.get_soup_by_id("xin")
    response = ai_host.call_llm(soup, [], "用于测试模型传输的合成问题吗？")
    assert response["reply"] == "与此无关"
    assert len(runtime.model.calls) == 1
    assert runtime.http_client is None
    assert runtime.http_async_client is None


def test_real_model_disabled_without_injected_model(runtime):
    runtime.model = None
    with pytest.raises(RuntimeError, match="disabled"):
        ai_host._get_llm()
    assert runtime.http_client is None


def test_runtime_context_is_restored(runtime, tmp_path):
    other = Runtime(Settings.for_test(tmp_path / "other"), model=FakeModel())
    with runtime_context(other):
        assert get_runtime() is other
        assert config.DATA_DIR == other.settings.DATA_DIR
    assert get_runtime() is runtime


def test_async_transport_closed_even_if_sync_close_fails(runtime):
    closed = []
    class Broken:
        def close(self):
            raise RuntimeError("synthetic close failure")
    class AsyncTransport:
        async def aclose(self):
            closed.append(True)
    runtime.http_client = Broken()
    runtime.http_async_client = AsyncTransport()
    try:
        with pytest.raises(RuntimeError, match="synthetic close"):
            asyncio.run(runtime.aclose())
        assert closed == [True]
        assert runtime.closed
    finally:
        runtime.http_client = runtime.http_async_client = None


@pytest.mark.parametrize("operation", [
    lambda: builtins.open(config.BACKEND_DIR / "data" / "sessions.db", "rb"),
    lambda: (config.BACKEND_DIR / ".env").read_text(),
    lambda: sqlite3.connect(database=str(config.BACKEND_DIR / "data" / "sessions.db")),
    lambda: sqlite3.connect(database=(config.BACKEND_DIR / "data" / "sessions.db").as_uri(), uri=True),
    lambda: sqlite3.connect(database="file:backend/data/sessions.db?mode=ro", uri=True),
    lambda: sqlite3.connect(database=(config.BACKEND_DIR / "data" / "sessions.db").as_uri().replace("data", "d%61ta"), uri=True),
])
def test_runtime_file_content_access_blocked(operation):
    with pytest.raises(TestAccessBlocked):
        operation()


def test_socketpair_allowed_and_external_access_blocked(network_guard):
    first, second = socket.socketpair()
    try:
        first.sendall(b"test")
        assert second.recv(4) == b"test"
    finally:
        first.close()
        second.close()
    with socket.socket() as conn:
        with pytest.raises(TestAccessBlocked):
            conn.connect(("203.0.113.1", 443))
        with pytest.raises(TestAccessBlocked):
            conn.connect_ex(("127.0.0.1", 11434))
    with pytest.raises(TestAccessBlocked):
        socket.getaddrinfo("example.invalid", 443)


def test_owned_loopback_service_allowed(network_guard):
    with socket.socket() as server, socket.socket() as client:
        server.bind(("127.0.0.1", 0))
        server.listen(1)
        client.connect(server.getsockname())
        peer, _ = server.accept()
        try:
            client.sendall(b"local")
            assert peer.recv(5) == b"local"
        finally:
            peer.close()


def test_closed_loopback_port_is_not_still_allowed(network_guard):
    server = socket.socket()
    server.bind(("127.0.0.1", 0))
    address = server.getsockname()
    server.close()
    with socket.socket() as client:
        with pytest.raises(TestAccessBlocked):
            client.connect_ex(address)


def test_udp_bind_does_not_authorize_tcp_connections(network_guard):
    with socket.socket(type=socket.SOCK_DGRAM) as udp, socket.socket() as tcp:
        udp.bind(("127.0.0.1", 0))
        with pytest.raises(TestAccessBlocked):
            tcp.connect_ex(udp.getsockname())


def test_localhost_alias_must_match_actual_bound_address(network_guard, monkeypatch):
    monkeypatch.setattr(network_guard, "resolve", lambda *args: [
        (socket.AF_INET, socket.SOCK_STREAM, 6, "", ("127.0.0.2", args[1])),
    ])
    with socket.socket() as server, socket.socket() as client:
        server.bind(("127.0.0.1", 0))
        with pytest.raises(TestAccessBlocked):
            client.connect_ex(("localhost", server.getsockname()[1]))


@pytest.mark.skipif(not hasattr(socket, "AF_UNIX"), reason="Unix sockets unavailable")
def test_unowned_unix_socket_is_blocked(network_guard):
    try:
        conn = socket.socket(socket.AF_UNIX)
    except OSError:
        pytest.skip("Unix socket implementation unavailable")
    with conn:
        with pytest.raises(TestAccessBlocked):
            conn.connect("synthetic-unowned-socket")


@pytest.mark.parametrize("relative", ["backend/data", ".cache/pytest", "outside", ".cache/pytest/nonempty"])
def test_destructive_basetemp_is_rejected_before_cleanup(tmp_path, relative):
    project = tmp_path / "synthetic-project"
    target = project / relative
    target.mkdir(parents=True)
    sentinel = target / "synthetic-sentinel.txt"
    sentinel.write_text("Only synthetic test content")
    with pytest.raises(ValueError):
        validate_basetemp(target, project)
    assert sentinel.read_text() == "Only synthetic test content"


def test_dedicated_new_basetemp_is_allowed(tmp_path):
    assert validate_basetemp(tmp_path / ".cache/pytest/new-run", tmp_path) == tmp_path / ".cache/pytest/new-run"


def test_protected_symlink_entry_and_target(tmp_path):
    project = tmp_path / "project"
    backend = project / "backend"
    backend.mkdir(parents=True)
    synthetic = tmp_path / "synthetic.env"
    synthetic.write_text("ONLY_SYNTHETIC_TEST_VALUE=1")
    entry = backend / ".env"
    try:
        entry.symlink_to(synthetic)
    except OSError as error:
        pytest.skip(f"Symlink privilege unavailable: {error.errno}")
    with pytest.MonkeyPatch.context() as patch:
        protect_runtime_files(patch, project)
        for path in (entry, synthetic):
            with pytest.raises(TestAccessBlocked):
                path.read_text()


@pytest.mark.parametrize("reply", ["是也不是", "算是", "不是", "是，可能不是"])
def test_loose_is_does_not_accept_another_answer_class(reply):
    def post(path, json):
        payload = {"sessionId": "synthetic-session"} if "soupId" in json else {"reply": reply}
        return SimpleNamespace(status_code=200, text="", json=lambda: payload)
    hard, soft = run_qa(SimpleNamespace(post=post), "xin", [("问题吗", "是")], loose_is=True)
    assert len(hard) == 1
    assert not soft


def test_feedback_trace_and_retired_merge_stay_in_temporary_storage(tmp_path, monkeypatch):
    import json
    def forbidden(*args, **kwargs):
        raise AssertionError("Tests must not restart a real service")
    monkeypatch.setattr(subprocess, "run", forbidden)
    settings = Settings.for_test(tmp_path / "data", ADMIN_TOKEN="test-admin", ENABLE_TRACE=True)
    app = create_app(settings)
    with TestClient(app) as client:
        feedback = client.post("/api/feedback", json={
            "soupId": "xin", "question": "合成测试问题吗", "hostAnswer": "不是",
            "expectedAnswer": "是", "reason": "synthetic test only",
        })
        assert feedback.status_code == 200
        headers = {"X-Admin-Token": "test-admin"}
        assert client.post(f"/api/feedback/admin/{feedback.json()['id']}/approve", headers=headers,
            json={"expectedRowVersion": 0}).status_code == 200
        merged = client.post("/api/feedback/admin/merge-verified", headers=headers)
        assert merged.status_code == 410
        assert merged.json()["code"] == "legacy_writer_disabled"
        sid = client.post("/api/chat", json={"soupId": "xin"}).json()["sessionId"]
        assert client.post("/api/chat", json={"sessionId": sid, "question": "测试问题有蓝色卫星吗？"}).status_code == 200
    assert not (settings.DATA_DIR / "feedback.jsonl").exists()
    with closing(sqlite3.connect(settings.DATA_DIR / "sessions.db")) as conn, conn:
        saved = conn.execute("SELECT payload_json,status,safe_for_model,row_version FROM feedback_items WHERE id=?",
            (feedback.json()["id"],)).fetchone()
        assert json.loads(saved[0])["question"] == "合成测试问题吗"
        assert saved[1:] == ("approved", 0, 1)
    assert not (settings.DATA_DIR / "verified_qa_pairs.jsonl").exists()
    assert list((settings.DATA_DIR / "traces").glob("*.jsonl"))
