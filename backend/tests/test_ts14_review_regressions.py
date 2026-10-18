"""Actual TS14 review boundary regressions, synthetic inputs, no provider I/O."""
import json
import asyncio
import sqlite3
from concurrent.futures import ThreadPoolExecutor
from threading import Event

import httpx
import pytest

from app.config import Settings
from app.model_gateway import CompatibleAdapter, ModelGateway
from .test_agent_store import agent_storage, running
from .test_agent_store import create, raw_rows
from .test_feedback_storage import storage
from .test_repair_agent_loop import drive
from .test_agent_decisions import identity, reserve, outcome
from .test_feedback_storage import snapshot


def test_actual_repair_prompt_reaches_compatible_adapter_and_finishes_owned_run(agent_storage, tmp_path):
    """C1: passing message objects straight to HTTPX fails before any request."""
    owner, _, run = running(agent_storage)
    requests = []

    def respond(request):
        requests.append(json.loads(request.content))
        return httpx.Response(200, json={"choices": [{"message": {"content":
            '{"action":"finish","needsHumanReason":"Synthetic human review required"}'}}]})

    adapter = CompatibleAdapter(Settings.for_test(tmp_path, LLM_PROVIDER="ollama", ALLOW_REAL_MODEL=True),
        transport=httpx.MockTransport(respond))
    shared = ModelGateway(adapter_factory=lambda: adapter)
    agent_storage.model_gateway = shared
    try:
        status = drive(owner, shared, run)
        assert status.state == "needs_human" and status.reason is None
        assert status.modelAttemptsUsed == 1 and status.toolAttemptsUsed == 0
        assert len(requests) == 1
        messages = requests[0]["messages"]
        assert [message["role"] for message in messages] == ["system", "user"]
        assert all(set(message) == {"role", "content"} for message in messages)
        payload = json.loads(messages[1]["content"])
        assert payload["runId"] == run.id and payload["context"]["claimsAreGold"] is False
        assert "PRIVATE synthetic claim" not in messages[1]["content"]
        assert [step.action.action for step in owner.steps(run.id)] == ["model_decision", "finish"]
    finally:
        cleanup = shared.close(wait_seconds=0.5)
        assert cleanup["active"] == cleanup["cleanup_failed"] == 0
        assert adapter.closed is True


@pytest.mark.parametrize("closing_window", ["waiting_for_writer", "before_commit"])
def test_shutdown_fences_ordinary_decision_completion_at_sqlite_boundaries(
    agent_storage, monkeypatch, closing_window
):
    """I1: an admission check before BEGIN cannot authorize a later commit."""
    from app.agents.contracts import AgentError

    owner, _, run = running(agent_storage)
    execution = identity(run)
    reserve(owner, execution)
    before = snapshot()
    if closing_window == "waiting_for_writer":
        blocker = sqlite3.connect(agent_storage.settings.DATA_DIR / "sessions.db", timeout=2)
        blocker.execute("BEGIN IMMEDIATE")
        entered = Event()
        original_connect = sqlite3.connect

        class ObservedConnection(sqlite3.Connection):
            def execute(self, sql, parameters=()):
                if sql == "BEGIN IMMEDIATE":
                    entered.set()
                return super().execute(sql, parameters)

        def connect(*args, **kwargs):
            return original_connect(*args, **kwargs, factory=ObservedConnection)

        try:
            with monkeypatch.context() as patch, ThreadPoolExecutor(max_workers=1) as pool:
                patch.setattr(sqlite3, "connect", connect)
                future = pool.submit(owner.complete_decision, execution, outcome())
                try:
                    assert entered.wait(2), "Owned completion never reached BEGIN"
                    asyncio.run(agent_storage.aclose())
                finally:
                    blocker.rollback()
                with pytest.raises(AgentError) as caught:
                    future.result(timeout=3)
        finally:
            blocker.rollback()
            blocker.close()
    else:
        original_audit = owner._audit

        def close_after_actual_mutation(*args, **kwargs):
            original_audit(*args, **kwargs)
            asyncio.run(agent_storage.aclose())

        monkeypatch.setattr(owner, "_audit", close_after_actual_mutation)
        with pytest.raises(AgentError) as caught:
            owner.complete_decision(execution, outcome())
        monkeypatch.setattr(owner, "_audit", original_audit)
    assert caught.value.code == "agent_unavailable"
    assert snapshot() == before
    stopped = owner.stop(run.id, lease_token=run.leaseToken, state="needs_human", reason="shutting_down")
    assert stopped.reason == "shutting_down" and stopped.modelAttemptsUsed == 1
    assert stopped.steps[0].state == "planned" and stopped.steps[-1].action == "server_stop"


def test_failed_heartbeat_fences_blocked_actual_tool_before_still_valid_lease_expires(
    agent_storage, monkeypatch
):
    """I2: a failed renewal must deny late tool success, not just the next loop."""
    import app.agents.tools as module
    from app.agents.contracts import AgentError
    from .test_agent_shutdown import timer
    from .test_agent_worker import configured
    from .test_repair_agent_loop import tool

    owner, worker, shared, transport = configured(agent_storage, clock=lambda: 1000.0)
    _, _, queued = create(agent_storage, owner=owner)
    transport.values = iter([json.dumps(tool(queued, "retrieve_truth"))])
    entered, release, tick = Event(), Event(), Event()
    original = module.truth_result

    def blocked(*args):
        result = original(*args)
        entered.set()
        assert release.wait(3), "Owned tool was not released"
        return result

    def failed(*args):
        raise AgentError("agent_unavailable", 503)

    monkeypatch.setattr(module, "truth_result", blocked)
    monkeypatch.setattr(owner, "heartbeat", failed)
    timer(worker, monkeypatch, tick)
    try:
        with ThreadPoolExecutor(max_workers=1) as pool:
            future = pool.submit(worker.run_once)
            try:
                assert entered.wait(2)
                current = owner.read(queued.id)
                assert current.leaseExpiresAt == 1060.0
                assert current.checkpoint.toolAttemptsUsed == 1
                tick.set()
                assert worker._cancelled.wait(2), "Independent heartbeat did not revoke execution"
            finally:
                release.set()
            status = future.result(timeout=3)
        assert status.state == "needs_human" and status.reason == "model_unavailable"
        assert status.modelAttemptsUsed == status.toolAttemptsUsed == 1
        rows = raw_rows("agent_steps")
        assert rows[1]["state"] == "planned" and rows[1]["result_json"] is None
        assert [json.loads(row["action_json"])["action"] for row in rows] == [
            "model_decision", "tool", "server_stop"]
        assert len(transport.calls) == 1 and raw_rows("rule_candidates") == []
    finally:
        release.set()
        tick.set()
        assert worker.close(wait_seconds=1).cleanupConfirmed
        assert shared.close(wait_seconds=0.5)["active"] == 0


@pytest.mark.parametrize("mutation", ["candidate", "finish"])
def test_execution_cancellation_before_commit_rolls_back_candidate_and_finish(
    agent_storage, monkeypatch, mutation
):
    """I2 positive controls: the same fence protects all ordinary write paths.

    Candidate report inputs are declared synthetic storage receipts, not an
    independently reviewed corpus or proof of model/human correctness.
    """
    from app.agents.contracts import AgentError, FinishAction
    from .test_candidate_reports import prepared_report, save_inputs, report_run

    cancelled = Event()
    if mutation == "candidate":
        owner, _, run, report_identity, draft, _ = prepared_report(agent_storage)
        execution, action = save_inputs(run, draft, report_identity.operationKey)
        owner.plan_step(execution, action)
        mutate = lambda: owner.save_candidate(execution, draft, report_identity.operationKey)
    else:
        owner, _, run = report_run(agent_storage)
        execution = identity(run)
        mutate = lambda: owner.finish(execution, FinishAction(action="finish", needsHumanReason="Synthetic handoff"))
    before = snapshot()
    original = owner._audit

    def cancel_after_actual_write(*args, **kwargs):
        original(*args, **kwargs)
        with agent_storage.lock:
            cancelled.set()

    monkeypatch.setattr(owner, "_audit", cancel_after_actual_write)
    with owner.execution_scope(run.id, run.leaseToken, cancelled):
        with pytest.raises(AgentError) as caught:
            mutate()
    assert caught.value.code == "agent_execution_cancelled"
    assert snapshot() == before and raw_rows("rule_candidates") == []
    # Scope cleanup must not poison unrelated administration or terminal work.
    monkeypatch.setattr(owner, "_audit", original)
    status = owner.stop(run.id, lease_token=run.leaseToken, state="needs_human", reason="model_unavailable")
    assert status.reason == "model_unavailable"


@pytest.mark.parametrize("concurrent_state", ["fresh", "claimed", "cancelled"])
def test_queued_handoff_cannot_remove_fresh_work_or_overwrite_concurrent_state(agent_storage, concurrent_state):
    from app.agents.contracts import AgentError

    owner, _, queued = create(agent_storage)
    if concurrent_state == "claimed":
        owner.claim(queued.id, expected_row_version=0)
    elif concurrent_state == "cancelled":
        owner.cancel(queued.id, expected_row_version=0)
    before = snapshot()
    with pytest.raises(AgentError) as caught:
        owner.handoff_stale_queued(queued.id, expected_row_version=0)
    assert caught.value.code == "agent_run_conflict" and snapshot() == before


def test_stale_queue_audit_failure_is_retryable_and_does_not_fake_handoff(agent_storage, monkeypatch):
    from app import audit_store
    from .test_agent_worker import configured
    from .test_agent_stop import revoke

    owner, worker, shared, transport = configured(agent_storage)
    _, item, queued = create(agent_storage, owner=owner)
    revoke(item)
    before = snapshot()
    original = audit_store.insert_business_event

    def fail(*args, **kwargs):
        raise audit_store.AuditPersistenceError("Synthetic audit outage")

    try:
        monkeypatch.setattr(audit_store, "insert_business_event", fail)
        assert worker.run_once() is None and snapshot() == before
        assert owner.read_status(queued.id).state == "queued" and transport.calls == []
        monkeypatch.setattr(audit_store, "insert_business_event", original)
        status = worker.run_once()
        assert status.state == "needs_human" and status.reason == "source_changed"
        assert status.deadlineAt is None and status.modelAttemptsUsed == status.toolAttemptsUsed == 0
    finally:
        assert worker.close(wait_seconds=1).cleanupConfirmed
        assert shared.close(wait_seconds=0.5)["active"] == 0


@pytest.mark.parametrize("source_change", ["revoke", "heartbeat"])
def test_source_is_rechecked_after_adapter_construction_before_dispatch(
    agent_storage, tmp_path, source_change
):
    """I4: rejecting a returned answer cannot undo sending withdrawn input."""
    from .test_agent_stop import revoke

    owner, item, run = running(agent_storage)
    entered, release = Event(), Event()
    requests = []

    def respond(request):
        requests.append(request)
        return httpx.Response(200, json={"choices": [{"message": {"content":
            '{"action":"finish","needsHumanReason":"Synthetic handoff"}'}}]})

    adapter = CompatibleAdapter(Settings.for_test(tmp_path, LLM_PROVIDER="ollama", ALLOW_REAL_MODEL=True),
        transport=httpx.MockTransport(respond))

    def construct():
        entered.set()
        assert release.wait(3), "Owned adapter factory not released"
        return adapter

    shared = ModelGateway(adapter_factory=construct)
    agent_storage.model_gateway = shared
    try:
        with ThreadPoolExecutor(max_workers=1) as pool:
            future = pool.submit(drive, owner, shared, run)
            try:
                assert entered.wait(2)
                assert owner.read(run.id).checkpoint.modelAttemptsUsed == 1
                if source_change == "revoke":
                    revoke(item)
                else:
                    owner.heartbeat(run.id, run.leaseToken)
            finally:
                release.set()
            status = future.result(timeout=3)
        assert status.state == "needs_human" and status.modelAttemptsUsed == 1
        assert status.toolAttemptsUsed == 0 and raw_rows("rule_candidates") == []
        if source_change == "revoke":
            assert requests == []
            assert status.reason == "source_changed"
            assert raw_rows("agent_steps")[0]["state"] == "planned"
        else:
            assert len(requests) == 1 and status.reason is None
            assert raw_rows("agent_steps")[0]["state"] == "completed"
    finally:
        release.set()
        cleanup = shared.close(wait_seconds=0.5)
        assert cleanup["active"] == cleanup["cleanup_failed"] == 0 and adapter.closed


@pytest.mark.parametrize("change", ["revoke", "version_change"])
def test_stale_queued_source_hands_off_without_attempts_and_releases_queue_capacity(agent_storage, change):
    """I3: permanently stale tasks must not occupy all ten queue places forever."""
    from .test_agent_worker import configured
    from .test_agent_stop import revoke
    from .test_feedback_privacy import permission
    from app.feedback_store import set_model_permission

    owner, worker, shared, transport = configured(agent_storage)
    _, item, first = create(agent_storage, owner=owner)
    queued = [first, *(create(agent_storage, owner=owner, item=item)[2] for _ in range(9))]
    if change == "revoke":
        revoke(item)
    else:
        set_model_permission(item.id, item.rowVersion, review=permission())
    try:
        statuses = [worker.run_once() for _ in range(10)]
        assert all(status is not None for status in statuses)
        assert {status.id for status in statuses} == {run.id for run in queued}
        assert all(status.state == "needs_human" and status.reason == "source_changed" for status in statuses)
        assert all(status.deadlineAt is None and status.modelAttemptsUsed == status.toolAttemptsUsed == 0
            for status in statuses)
        assert all(row["lease_token"] is None and row["lease_expires_at"] is None for row in raw_rows("agent_runs"))
        assert transport.calls == []
        _, _, next_run = create(agent_storage, owner=owner)
        following = worker.run_once()
        assert following.id == next_run.id and following.state == "needs_human"
        assert following.modelAttemptsUsed == 1 and len(transport.calls) == 1
    finally:
        assert worker.close(wait_seconds=1).cleanupConfirmed
        assert shared.close(wait_seconds=0.5)["active"] == 0
