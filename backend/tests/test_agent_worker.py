"""One coordinator consumes actual SQLite tasks, not the legacy RAM queue."""
import time
from concurrent.futures import ThreadPoolExecutor
from dataclasses import replace
from threading import Event

import pytest

from .test_agent_store import agent_storage, create, store, raw_rows
from .test_feedback_storage import storage
from .test_repair_agent_loop import gateway


def configured(active, **changes):
    from app.agents.worker import AgentWorker
    from app.agents.repair_agent import RepairAgent
    from app.agents.tools import ToolExecutor
    active.settings = replace(active.settings, ENABLE_AGENT=True)
    owner = store(active, lease_seconds=60, **changes)
    shared, transport = gateway(active, [dict(action="finish", needsHumanReason="Synthetic worker handoff")])
    worker = AgentWorker(active, owner, RepairAgent(owner, ToolExecutor(owner), shared))
    return owner, worker, shared, transport


def test_worker_construction_is_inert_and_close_does_not_close_shared_online_gateway(agent_storage):
    owner, worker, shared, transport = configured(agent_storage)
    try:
        assert raw_rows("agent_runs") == [] and transport.calls == []
        assert worker.snapshot().coordinatorAlive is False
        result = worker.close(wait_seconds=0.1)
        assert result.admissionClosed and result.cleanupConfirmed and shared.snapshot()["closed"] is False
        assert worker.run_once() is None
    finally: assert shared.close(wait_seconds=0.1)["active"] == 0


def test_one_sqlite_task_is_claimed_while_other_queued_deadline_stays_unstarted(agent_storage):
    owner, worker, shared, transport = configured(agent_storage)
    _, _, first = create(agent_storage, owner=owner)
    _, _, second = create(agent_storage, owner=owner)
    try:
        status = worker.run_once()
        assert status.id == first.id and status.state == "needs_human" and status.modelAttemptsUsed == 1
        pending = owner.read(second.id)
        assert pending.state == "queued" and pending.checkpoint.deadlineAt is None
        assert agent_storage.pending_agents.snapshot()["queued"] == 0 and len(transport.calls) == 1
        worker.stop_admission()
        assert worker.run_once() is None and owner.read(second.id) == pending
    finally:
        assert worker.close(wait_seconds=0.1).cleanupConfirmed
        assert shared.close(wait_seconds=0.1)["active"] == 0


def test_busy_online_owner_delays_claim_without_starting_agent_deadline(agent_storage):
    from app.agents.worker import AgentWorker
    from app.agents.repair_agent import RepairAgent
    from app.agents.tools import ToolExecutor
    from app.model_gateway import ModelGateway
    from .test_model_gateway import ScriptedTransport
    import json
    agent_storage.settings = replace(agent_storage.settings, ENABLE_AGENT=True)
    owner = store(agent_storage, lease_seconds=60); _, _, queued = create(agent_storage, owner=owner)
    entered, release = Event(), Event()
    transport = ScriptedTransport(['{"answer":"是","reasoning":"synthetic"}',
        json.dumps(dict(action="finish", needsHumanReason="Synthetic handoff"))],
        before_return=lambda: (entered.set(), release.wait(3)))
    shared = ModelGateway(adapter_factory=lambda: transport); agent_storage.model_gateway = shared
    worker = AgentWorker(agent_storage, owner, RepairAgent(owner, ToolExecutor(owner), shared))
    try:
        with ThreadPoolExecutor(max_workers=1) as pool:
            future = pool.submit(shared.invoke, [], deadline=time.monotonic() + 3, max_attempts=1)
            try:
                assert entered.wait(2) and worker.run_once() is None
                unchanged = owner.read(queued.id)
                assert unchanged.state == "queued" and unchanged.checkpoint.firstStartedAt is None
                assert unchanged.checkpoint.modelAttemptsUsed == 0 and raw_rows("agent_steps") == []
            finally: release.set()
            assert future.result(timeout=3).answer == "是"
        assert worker.run_once().state == "needs_human" and len(transport.calls) == 2
    finally:
        release.set()
        assert worker.close(wait_seconds=0.1).cleanupConfirmed
        assert shared.close(wait_seconds=0.1)["active"] == 0


def test_started_coordinator_has_independent_heartbeat_while_model_is_blocked(agent_storage, monkeypatch):
    now = [1000.0]
    owner, worker, shared, transport = configured(agent_storage, clock=lambda: now[0])
    _, _, queued = create(agent_storage, owner=owner)
    entered, release, tick, beat = Event(), Event(), Event(), Event()
    def blocked():
        entered.set()
        assert release.wait(3)
    transport.before_return = blocked
    # Drive the owned timer via events rather than ten-second wall sleeps.
    def controlled_wait(stop):
        while not stop.is_set():
            if tick.wait(0.01):
                tick.clear()
                return False
        return True
    monkeypatch.setattr(worker, "_wait_heartbeat", controlled_wait)
    original = owner.heartbeat
    def observed(*args):
        result = original(*args); beat.set(); return result
    monkeypatch.setattr(owner, "heartbeat", observed)
    try:
        worker.start()
        assert entered.wait(2)
        started = owner.read(queued.id)
        assert started.leaseExpiresAt == 1060.0 and started.checkpoint.modelAttemptsUsed == 1
        now[0] = 1010.0; tick.set()
        assert beat.wait(2)
        renewed = owner.read(queued.id)
        assert renewed.leaseExpiresAt == 1070.0 and renewed.checkpoint == started.checkpoint
        assert renewed.rowVersion > started.rowVersion and renewed.leaseToken == started.leaseToken
        assert worker.snapshot().heartbeatAlive and worker.snapshot().coordinatorAlive
    finally:
        release.set(); tick.set()
        assert worker.close(wait_seconds=1).cleanupConfirmed
        assert shared.close(wait_seconds=0.1)["active"] == 0


def test_native_heartbeat_wait_requests_exactly_ten_seconds_without_adding_a_model_call(agent_storage):
    owner, worker, shared, transport = configured(agent_storage)
    waits = []
    class Stop:
        def wait(self, seconds): waits.append(seconds); return True
    try:
        assert worker._wait_heartbeat(Stop()) is True and waits == [10.0] and transport.calls == []
    finally:
        assert worker.close(wait_seconds=0.1).cleanupConfirmed
        assert shared.close(wait_seconds=0.1)["active"] == 0


def test_worker_executable_source_is_registered_in_fixed_process_identity(agent_storage, monkeypatch):
    import pytest
    from pathlib import Path
    from app.agents.contracts import AgentError
    from app.agents.regression import FixedRegression
    owner, worker, shared, transport = configured(agent_storage)
    try:
        FixedRegression(agent_storage)
        original = Path.read_bytes
        def changed(path):
            value = original(path)
            return value + b"\n# synthetic worker update\n" if path.name == "worker.py" else value
        monkeypatch.setattr(Path, "read_bytes", changed)
        with pytest.raises(AgentError) as caught: FixedRegression(agent_storage)
        assert caught.value.code == "agent_source_reload_required"
    finally:
        assert worker.close(wait_seconds=0.1).cleanupConfirmed
        assert shared.close(wait_seconds=0.1)["active"] == 0


def test_new_lifespan_main_dependency_is_in_fixed_execution_identity(agent_storage, monkeypatch):
    import pytest
    from pathlib import Path
    from app.agents.contracts import AgentError
    from app.agents.regression import FixedRegression
    FixedRegression(agent_storage); original = Path.read_bytes
    def changed(path):
        value = original(path)
        return value + b"\n# synthetic lifecycle update\n" if path.name == "main.py" else value
    monkeypatch.setattr(Path, "read_bytes", changed)
    with pytest.raises(AgentError) as caught: FixedRegression(agent_storage)
    assert caught.value.code == "agent_source_reload_required"


@pytest.mark.parametrize("filename", ["agent_runs.py", "admin_contracts.py", "request_contract.py"])
def test_admin_executable_dependencies_are_part_of_fixed_source_identity(agent_storage, monkeypatch, filename):
    from pathlib import Path
    from app.agents.contracts import AgentError
    from app.agents.regression import FixedRegression
    original = Path.read_bytes
    def changed(path):
        value = original(path)
        return value + b"\n# synthetic admin boundary update\n" if path.name == filename else value
    monkeypatch.setattr(Path, "read_bytes", changed)
    with pytest.raises(AgentError) as caught: FixedRegression(agent_storage)
    assert caught.value.code == "agent_source_reload_required"
