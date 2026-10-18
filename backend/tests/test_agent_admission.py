"""Actual shared admission wins races; reservations are not provider receipts."""
import json
import time
from concurrent.futures import ThreadPoolExecutor
from dataclasses import replace
from threading import Event

from .test_agent_store import agent_storage, create, store, raw_rows
from .test_feedback_storage import storage
from .test_model_gateway import ScriptedTransport


def setup(active, transport, *, max_active=2):
    from app.model_gateway import ModelGateway
    from app.agents.worker import AgentWorker
    from app.agents.repair_agent import RepairAgent
    from app.agents.tools import ToolExecutor
    active.settings = replace(active.settings, ENABLE_AGENT=True)
    shared = ModelGateway(adapter_factory=lambda: transport, max_active=max_active)
    active.model_gateway = shared
    owner = store(active, lease_seconds=60)
    return owner, AgentWorker(active, owner, RepairAgent(owner, ToolExecutor(owner), shared)), shared


def test_online_arrival_after_idle_snapshot_still_wins_atomic_admission_without_refund(agent_storage, monkeypatch):
    entered, release = Event(), Event()
    def blocked(): entered.set(); assert release.wait(3)
    transport = ScriptedTransport(['{"answer":"是","reasoning":"synthetic"}'], before_return=blocked)
    owner, worker, shared = setup(agent_storage, transport, max_active=1)
    _, _, queued = create(agent_storage, owner=owner)
    original = owner.claim
    try:
        with ThreadPoolExecutor(max_workers=1) as pool:
            online = []
            def raced_claim(*args, **kwargs):
                result = original(*args, **kwargs)
                online.append(pool.submit(shared.invoke, [], deadline=time.monotonic() + 3, max_attempts=1))
                assert entered.wait(2)
                return result
            monkeypatch.setattr(owner, "claim", raced_claim)
            try:
                status = worker.run_once()
                assert status.state == "needs_human" and status.reason == "model_unavailable"
                assert status.modelAttemptsUsed == 1 and status.toolAttemptsUsed == 0
                assert len(transport.calls) == 1 and shared.snapshot()["active_online"] == 1
                decision = json.loads(raw_rows("agent_steps")[0]["result_json"])
                assert decision["status"] == "unavailable" and decision["errorCode"] == "model_busy"
                assert decision["action"] is None  # Actual local refusal, not proof of a provider call.
            finally: release.set()
            assert online[0].result(timeout=3).answer == "是"
    finally:
        release.set()
        assert worker.close(wait_seconds=0.1).cleanupConfirmed
        assert shared.close(wait_seconds=0.1)["active"] == 0


def test_unknown_cleanup_holds_next_sqlite_task_without_starting_its_budget_or_deadline(agent_storage):
    transport = ScriptedTransport([json.dumps(dict(action="finish", needsHumanReason="Synthetic handoff"))], broken_close=True)
    owner, worker, shared = setup(agent_storage, transport)
    _, _, first = create(agent_storage, owner=owner)
    _, _, second = create(agent_storage, owner=owner)
    try:
        stopped = worker.run_once()
        assert stopped.id == first.id and stopped.reason == "model_unavailable" and stopped.modelAttemptsUsed == 1
        assert shared.snapshot()["active_agent"] == shared.snapshot()["cleanup_failed"] == 1
        assert worker.run_once() is None
        pending = owner.read(second.id)
        assert pending.state == "queued" and pending.checkpoint.firstStartedAt is None
        assert pending.checkpoint.modelAttemptsUsed == pending.checkpoint.toolAttemptsUsed == 0
        assert len(transport.calls) == 1 and raw_rows("rule_candidates") == []
    finally:
        assert not worker.close(wait_seconds=0.1).cleanupConfirmed
        result = shared.close(wait_seconds=0.1)
        assert result["active"] == result["cleanup_failed"] == 1


def test_expired_running_task_stops_at_original_deadline_without_new_claim_or_model_call(agent_storage):
    transport = ScriptedTransport([])
    owner, worker, shared = setup(agent_storage, transport)
    clock = [1000.0]; owner.clock = lambda: clock[0]
    _, _, queued = create(agent_storage, owner=owner)
    running = owner.claim(queued.id, expected_row_version=0)
    clock[0] = 1181.0
    try:
        stopped = worker.run_once()
        assert stopped.state == "needs_human" and stopped.reason == "deadline" and stopped.deadlineAt == 1180.0
        assert stopped.modelAttemptsUsed == stopped.toolAttemptsUsed == 0 and transport.calls == []
        assert running.checkpoint.deadlineAt == stopped.deadlineAt and worker.run_once() is None
    finally:
        assert worker.close(wait_seconds=0.1).cleanupConfirmed
        assert shared.close(wait_seconds=0.1)["active"] == 0
