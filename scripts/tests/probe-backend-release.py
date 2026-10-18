"""Fresh-process LOCAL demo smoke; no dependency install or provider quality claim."""
import json
from pathlib import Path
import socket
import sqlite3
import sys
from threading import local
from uuid import uuid4

backend, data = (Path(value).resolve() for value in sys.argv[1:])
assert backend.is_dir() and data.is_dir() and not any(data.iterdir())
assert not any(name == "app" or name.startswith("app.") for name in sys.modules)
sys.path.insert(0, str(backend))
network_attempts = []
internal_pair = local()
original_connect = socket.socket.connect
original_pair = socket.socketpair


def no_network(*_args, **_kwargs):
    network_attempts.append(True)
    raise RuntimeError("Outbound network forbidden in LOCAL artifact smoke")


def guarded_connect(sock, address):
    # Windows asyncio creates its self-pipe via stdlib's local socketpair.
    # Permit only that synchronous trusted construction in its own thread,
    # not arbitrary loopback/provider connections made by application code.
    if getattr(internal_pair, "constructing", False):
        return original_connect(sock, address)
    return no_network()


def local_socketpair(*args, **kwargs):
    internal_pair.constructing = True
    try:
        return original_pair(*args, **kwargs)
    finally:
        internal_pair.constructing = False


socket.socket.connect = guarded_connect
socket.socketpair = local_socketpair
socket.socket.connect_ex = no_network
socket.create_connection = no_network
socket.getaddrinfo = no_network

from fastapi.testclient import TestClient
from app.config import Settings
from app.main import create_app
from app.testing import FakeModel
from app.agents.regression import FixedRegression

model = FakeModel()
settings = Settings.for_test(data)
application = create_app(settings, model=model)
with TestClient(application) as client:
    runtime = application.state.runtime
    health = client.get("/health")
    assert health.status_code == 200
    assert health.json()["status"] == "ok" and health.json()["soups"] == 1
    assert health.json()["testing"] is True and health.json()["provider"] == "fake"
    public = client.get("/api/soups")
    assert public.status_code == 200
    soups = public.json()["soups"]
    assert len(soups) == 1 and soups[0]["id"] == "demo-synthetic"
    assert soups[0]["title"] == "合成本地示例" and soups[0]["source"] == "synthetic_demo"
    assert "bottom" not in soups[0] and "不代表真实题库" not in public.text
    start = dict(soupId="demo-synthetic", requestId=str(uuid4()), level="tianyi")
    created = client.post("/api/chat", json=start)
    assert created.status_code == 200
    assert client.post("/api/chat", json=start).content == created.content
    question = dict(sessionId=created.json()["sessionId"], requestId=str(uuid4()), question="今天下雨了吗？")
    answered = client.post("/api/chat", json=question)
    assert answered.status_code == 200 and answered.json()["reply"] == "与此无关"
    assert client.post("/api/chat", json=question).content == answered.content
    assert len(model.calls) == 1
    # This exercises every registered app/eval dependency, not merely main.py.
    fixed = FixedRegression(runtime)
    assert len(fixed.suite_manifest_digest) == 64
    origins = [module for name, module in sys.modules.items()
        if name in {"app", "eval"} or name.startswith(("app.", "eval."))]
    assert len(origins) > 30
    assert all(Path(module.__file__).resolve().is_relative_to(backend) for module in origins)

assert runtime.closed and runtime.agent_worker is None
state = runtime.model_gateway.snapshot()
assert state["closed"] and state["active"] == state["waiting_online"] == state["cleanup_failed"] == 0
assert runtime.audit_shutdown["residualJobs"] == runtime.audit_shutdown["unpersistedCount"] == 0
assert runtime.audit_store.status().activeIO == runtime.audit_store.status().memoryCount == 0
assert runtime.http_client is None or runtime.http_client.is_closed
assert runtime.http_async_client is None or runtime.http_async_client.is_closed
with sqlite3.connect(data / "sessions.db") as database:
    assert database.execute("SELECT count(*) FROM sessions").fetchone()[0] == 1
    assert database.execute("SELECT count(*) FROM turns").fetchone()[0] == 1
    assert database.execute("SELECT count(*) FROM messages").fetchone()[0] == 2
assert not network_attempts
print(json.dumps(dict(status="passed", localOnly=True, productionReady=False,
    dataKind="synthetic_demo", health=True, publicSeed=True, chatReplay=True,
    moduleOriginsVerified=True, fixedSuiteSourcesVerified=True,
    ownedResourcesClosed=True, networkAttempts=0)))
