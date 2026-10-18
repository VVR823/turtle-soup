"""Bounded owned worker shutdown never certifies a blocked adapter exited."""
from contextlib import closing
from dataclasses import replace
from threading import Event

import pytest

from .test_agent_store import agent_storage, create, raw_rows
from .test_feedback_storage import storage
from .test_agent_worker import configured


def timer(worker, monkeypatch, tick):
    def wait(stop):
        while not stop.is_set():
            if tick.wait(0.01): tick.clear(); return False
        return True
    monkeypatch.setattr(worker, "_wait_heartbeat", wait)


def test_zero_wait_shutdown_reports_blocked_local_owner_honestly_and_leaves_queue_unstarted(agent_storage):
    owner, worker, shared, transport = configured(agent_storage)
    _, _, first = create(agent_storage, owner=owner)
    _, _, second = create(agent_storage, owner=owner)
    entered, release = Event(), Event()
    def blocked(): entered.set(); assert release.wait(3)
    transport.before_return = blocked
    try:
        worker.start(); assert entered.wait(2)
        stopped = worker.close(wait_seconds=0)
        assert stopped.admissionClosed and not stopped.cleanupConfirmed
        assert shared.snapshot()["active_agent"] == 1 and shared.snapshot()["closed"] is False
        assert owner.read(second.id).checkpoint.deadlineAt is None
        assert owner.read(first.id).checkpoint.modelAttemptsUsed == 1
    finally:
        release.set()
        result = shared.close(wait_seconds=0.5)
        assert result["active"] == 0
        assert worker.close(wait_seconds=1).cleanupConfirmed


@pytest.mark.parametrize("change", ["heartbeat_failure", "takeover", "original_deadline", "admin_cancel"])
def test_failed_independent_heartbeat_cancels_work_without_overwriting_new_owner_or_deadline(agent_storage, monkeypatch, change):
    from app.agents.contracts import AgentError
    now = [1000.0]
    owner, worker, shared, transport = configured(agent_storage, clock=lambda: now[0])
    _, _, queued = create(agent_storage, owner=owner)
    entered, release, tick = Event(), Event(), Event()
    def blocked(): entered.set(); assert release.wait(3)
    transport.before_return = blocked; timer(worker, monkeypatch, tick)
    if change == "heartbeat_failure":
        def failed(*args): raise AgentError("agent_unavailable", 503)
        monkeypatch.setattr(owner, "heartbeat", failed)
    try:
        worker.start(); assert entered.wait(2)
        old = owner.read(queued.id)
        if change == "takeover":
            now[0] = 1061.0
            replacement = owner.claim(queued.id, expected_row_version=old.rowVersion)
        elif change == "original_deadline": now[0] = 1181.0
        elif change == "admin_cancel": owner.cancel(queued.id, expected_row_version=old.rowVersion)
        tick.set(); assert transport.cancel_requested.wait(2)
        stopped = worker.close(wait_seconds=1)
        assert stopped.admissionClosed and not stopped.cleanupConfirmed
        status = owner.read_status(queued.id)
        assert status.modelAttemptsUsed == 1 and status.toolAttemptsUsed == 0 and status.deadlineAt == 1180.0
        assert len(transport.calls) == 1 and raw_rows("rule_candidates") == []
        if change == "takeover":
            assert status.state == "running" and owner.read(queued.id).leaseToken == replacement.leaseToken
            assert raw_rows("agent_steps")[0]["state"] == "planned" and len(raw_rows("agent_steps")) == 1
        elif change == "original_deadline":
            assert status.state == "needs_human" and status.reason == "deadline"
            assert raw_rows("agent_steps")[0]["state"] == "planned"
        elif change == "admin_cancel":
            assert status.state == "cancelled" and status.reason == "cancellation"
            assert raw_rows("agent_steps")[0]["state"] == "planned" and len(raw_rows("agent_steps")) == 2
        else: assert status.state == "needs_human" and status.reason == "model_unavailable"
    finally:
        release.set(); tick.set()
        assert shared.close(wait_seconds=0.5)["active"] == 0
        assert worker.close(wait_seconds=1).cleanupConfirmed


def test_default_lifespan_keeps_agent_disabled_and_does_not_create_phase_three(tmp_path):
    import sqlite3
    from fastapi.testclient import TestClient
    from app.config import Settings
    from app.main import create_app
    from app.testing import FakeModel
    from .test_migrations import puzzle
    model = FakeModel()
    path = tmp_path / "default-app"
    app = create_app(Settings.for_test(path), model=model, soups=[puzzle()])
    with TestClient(app) as client:
        assert client.get("/health").status_code == 200
        active = app.state.runtime
        assert active.agent_worker is None and active.agent_shutdown is None
        assert active.model_gateway is None and model.calls == []
    with closing(sqlite3.connect(path / "sessions.db")) as conn, conn:
        assert [r[0] for r in conn.execute("SELECT version FROM schema_migrations ORDER BY version")] == [1, 2]
        assert conn.execute("SELECT name FROM sqlite_master WHERE name='agent_runs'").fetchone() is None


def test_closed_worker_admission_is_rejected_before_creating_a_run(agent_storage):
    from app.agents.contracts import AgentError
    from app.routers.agent_runs import _worker
    from types import SimpleNamespace

    worker = SimpleNamespace(snapshot=lambda: SimpleNamespace(admissionClosed=True))
    original_settings = agent_storage.settings
    try:
        agent_storage.settings = replace(agent_storage.settings, ENABLE_AGENT=True)
        agent_storage.agent_worker = worker
        with pytest.raises(AgentError) as caught:
            _worker(admitting=True)
    finally:
        agent_storage.agent_worker = None
        agent_storage.settings = original_settings
    assert caught.value.code == "agent_unavailable"


def test_enabled_phase_two_startup_refuses_before_gateway_or_worker_without_hidden_migration(tmp_path):
    import sqlite3
    from fastapi.testclient import TestClient
    from app.config import Settings
    from app.main import create_app
    from app.agents.contracts import AgentError
    from .test_migrations import puzzle
    path = tmp_path / "unmigrated-app"
    app = create_app(Settings.for_test(path, ENABLE_AGENT=True), soups=[puzzle()])
    with pytest.raises(AgentError):
        with TestClient(app): pass
    assert app.state.runtime.closed and app.state.runtime.agent_worker is None
    assert app.state.runtime.model_gateway is None
    with closing(sqlite3.connect(path / "sessions.db")) as conn, conn:
        assert [r[0] for r in conn.execute("SELECT version FROM schema_migrations ORDER BY version")] == [1, 2]
        assert conn.execute("SELECT name FROM sqlite_master WHERE name='agent_runs'").fetchone() is None


def test_explicit_phase_three_enabled_lifespan_starts_one_owned_worker_without_model_calls(agent_storage):
    from dataclasses import replace
    from fastapi.testclient import TestClient
    from app.main import create_app
    from app.testing import FakeModel
    model = FakeModel()
    app = create_app(replace(agent_storage.settings, ENABLE_AGENT=True), model=model, soups=agent_storage.soups)
    with TestClient(app) as client:
        active = app.state.runtime
        assert client.get("/health").status_code == 200
        assert active.agent_worker is not None and active.agent_worker.store.lease_seconds == 60
        assert active.agent_worker.snapshot().coordinatorAlive and active.model_gateway is active.agent_worker.agent.gateway
        assert active.start_agent_worker() is active.agent_worker and model.calls == []
        assert active.model_gateway.snapshot()["active"] == 0
    assert active.closed and active.agent_shutdown.admissionClosed and active.agent_shutdown.cleanupConfirmed
    assert not active.agent_shutdown.coordinatorAlive and not active.agent_shutdown.heartbeatAlive
    assert active.model_shutdown["closed"] and active.model_shutdown["active"] == 0


def test_runtime_shutdown_signals_owned_worker_and_never_saves_late_result(agent_storage):
    import asyncio
    import json
    owner, worker, shared, transport = configured(agent_storage)
    agent_storage.agent_worker = worker  # Explicit injected owner; lifespan is tested above.
    _, _, queued = create(agent_storage, owner=owner)
    entered, release = Event(), Event()
    def blocked(): entered.set(); assert release.wait(3)
    transport.before_return = blocked
    try:
        worker.start(); assert entered.wait(2)
        # Native gateway requests cancellation; release on that actual signal,
        # not on a guessed sleep. The adapter stays controlled/offline.
        from concurrent.futures import ThreadPoolExecutor
        with ThreadPoolExecutor(max_workers=1) as pool:
            closing = pool.submit(asyncio.run, agent_storage.aclose())
            try:
                assert transport.cancel_requested.wait(2)
            finally: release.set()
            closing.result(timeout=4)
        assert agent_storage.agent_shutdown.admissionClosed and agent_storage.agent_shutdown.cleanupConfirmed
        assert shared.snapshot()["closed"] and shared.snapshot()["active"] == 0
        rows = raw_rows("agent_steps")
        assert rows[0]["state"] == "planned" and rows[0]["result_json"] is None
        assert json.loads(rows[-1]["result_json"])["reason"] == "shutting_down"
        assert not any(json.loads(s["action_json"])["action"] == "finish" for s in rows)
    finally:
        release.set()
        assert worker.close(wait_seconds=1).cleanupConfirmed
        assert shared.close(wait_seconds=0.1)["active"] == 0


def refuse_threads(monkeypatch):
    import app.agents.worker as module
    from threading import Thread
    class RefusedThread(Thread):
        def start(self): raise RuntimeError("PRIVATE synthetic operating-system thread refusal")
    monkeypatch.setattr(module, "Thread", RefusedThread)


def test_refused_coordinator_start_is_controlled_and_close_never_joins_unstarted_thread(agent_storage, monkeypatch):
    from app.agents.contracts import AgentError
    owner, worker, shared, transport = configured(agent_storage)
    refuse_threads(monkeypatch)
    try:
        with pytest.raises(AgentError) as caught: worker.start()
        assert caught.value.code == "agent_unavailable" and "PRIVATE" not in str(caught.value)
        assert worker.close(wait_seconds=0.1).cleanupConfirmed and transport.calls == []
        assert raw_rows("agent_runs") == []
    finally:
        worker.close(wait_seconds=0.1)
        assert shared.close(wait_seconds=0.1)["active"] == 0


def test_refused_heartbeat_start_records_handoff_and_closes_without_any_model_or_tool_call(agent_storage, monkeypatch):
    owner, worker, shared, transport = configured(agent_storage)
    _, _, queued = create(agent_storage, owner=owner)
    refuse_threads(monkeypatch)
    try:
        status = worker.run_once()
        assert status.id == queued.id and status.state == "needs_human" and status.reason == "model_unavailable"
        assert status.modelAttemptsUsed == status.toolAttemptsUsed == 0 and transport.calls == []
        assert worker.snapshot().admissionClosed and worker.close(wait_seconds=0.1).cleanupConfirmed
    finally:
        worker.close(wait_seconds=0.1)
        assert shared.close(wait_seconds=0.1)["active"] == 0


def test_lifespan_worker_start_failure_closes_partial_runtime_without_raw_error_or_extra_model(agent_storage, monkeypatch):
    from dataclasses import replace
    from fastapi.testclient import TestClient
    from app.main import create_app
    from app.testing import FakeModel
    from app.agents.contracts import AgentError
    refuse_threads(monkeypatch)
    model = FakeModel()
    app = create_app(replace(agent_storage.settings, ENABLE_AGENT=True), model=model, soups=agent_storage.soups)
    with pytest.raises(AgentError) as caught:
        with TestClient(app): pass
    assert caught.value.code == "agent_unavailable" and "PRIVATE" not in str(caught.value)
    active = app.state.runtime
    assert active.closed and active.agent_shutdown.admissionClosed and active.agent_shutdown.cleanupConfirmed
    assert active.model_shutdown["closed"] and active.model_shutdown["active"] == 0 and model.calls == []
