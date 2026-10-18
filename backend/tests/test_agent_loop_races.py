"""Owned event-controlled loop races; no provider or real user data."""
import json
from concurrent.futures import ThreadPoolExecutor
from threading import Event

import pytest

from app import baselines
from .test_agent_store import agent_storage, create, running, store, raw_rows
from .test_feedback_storage import storage
from .test_model_gateway import ScriptedTransport
from .test_repair_agent_loop import drive, gateway, tool


@pytest.mark.parametrize("change", ["heartbeat", "cancel", "revoke", "takeover", "shutdown"])
def test_blocked_loop_late_model_result_obeys_current_authority(agent_storage, change):
    from app.model_gateway import ModelGateway
    from .test_agent_stop import revoke
    clock = [1000.0]
    owner, item, queued = create(agent_storage, owner=store(agent_storage, clock=lambda: clock[0]))
    run = owner.claim(queued.id, expected_row_version=0)
    entered, release = Event(), Event()
    def blocked():
        entered.set()
        assert release.wait(3), "Owned test did not release transport"
    transport = ScriptedTransport([json.dumps(dict(action="finish", needsHumanReason="Synthetic handoff"))],
        before_return=blocked)
    shared = ModelGateway(adapter_factory=lambda: transport); agent_storage.model_gateway = shared
    try:
        with ThreadPoolExecutor(max_workers=1) as pool:
            future = pool.submit(drive, owner, shared, run)
            try:
                assert entered.wait(2)
                current = owner.read(run.id)
                assert current.checkpoint.modelAttemptsUsed == 1 and owner.steps(run.id)[0].state == "planned"
                if change == "heartbeat": owner.heartbeat(run.id, run.leaseToken)
                elif change == "cancel": owner.cancel(run.id, expected_row_version=current.rowVersion)
                elif change == "revoke": revoke(item)
                elif change == "takeover":
                    clock[0] += 31
                    replacement = owner.claim(run.id, expected_row_version=current.rowVersion)
                else: agent_storage.closed = True
            finally: release.set()
            status = future.result(timeout=3)
        assert status.modelAttemptsUsed == 1 and status.toolAttemptsUsed == 0 and len(transport.calls) == 1
        rows = raw_rows("agent_steps")
        if change == "heartbeat":
            assert status.state == "needs_human" and status.reason is None and rows[0]["state"] == "completed"
        else:
            assert rows[0]["state"] == "planned" and rows[0]["result_json"] is None
            assert not any(baselines.strict_json(row["action_json"])["action"] == "finish" for row in rows)
            if change == "takeover":
                assert status.state == "running" and owner.read(run.id).leaseToken == replacement.leaseToken
                assert len(rows) == 1 and status.deadlineAt == run.checkpoint.deadlineAt
            elif change == "cancel": assert status.state == "cancelled" and status.reason == "cancellation"
            elif change == "shutdown": assert status.state == "needs_human" and status.reason == "shutting_down"
            else: assert status.state == "needs_human" and status.reason == "source_changed"
        assert raw_rows("rule_candidates") == []
    finally:
        release.set()
        assert shared.close(wait_seconds=0.1)["active"] == 0


def test_unknown_transport_cleanup_blocks_later_model_work_without_refund(agent_storage):
    from app.model_gateway import ModelGateway
    owner, _, run = running(agent_storage)
    transport = ScriptedTransport([json.dumps(tool(run, "get_turn_trace"))], broken_close=True)
    shared = ModelGateway(adapter_factory=lambda: transport); agent_storage.model_gateway = shared
    try:
        first = drive(owner, shared, run)
        assert first.reason == "model_unavailable" and first.modelAttemptsUsed == 1 and first.toolAttemptsUsed == 0
        assert shared.snapshot()["cleanup_failed"] == 1
        _, _, queued = create(agent_storage, owner=owner)
        second_run = owner.claim(queued.id, expected_row_version=0)
        second = drive(owner, shared, second_run)
        assert second.reason == "model_unavailable" and second.modelAttemptsUsed == second.toolAttemptsUsed == 0
        assert len(transport.calls) == 1 and owner.steps(run.id)[0].state == "completed"
    finally:
        result = shared.close(wait_seconds=0.1)
        # "active" includes a conservatively retained reservation even after
        # the local invocation thread exits; close failure is NOT clean.
        assert result["active"] == 1 and result["cleanup_failed"] == 1


def test_saved_candidate_restart_uses_stored_synthetic_proof_and_only_awaits_review(agent_storage):
    # The inherited fixture seeds a declared synthetic regression receipt via
    # actual store transactions; this is replay proof, not real suite quality.
    from .test_candidate_reports import saved
    owner, _, run, candidate = saved(agent_storage)
    original = tuple(owner.steps(run.id))
    shared, transport = gateway(agent_storage, [dict(action="finish", candidateId=candidate.id)])
    try:
        status = drive(owner, shared, run)
        assert status.state == "awaiting_review" and status.candidateId == candidate.id and status.reason is None
        assert status.modelAttemptsUsed == 1 and status.toolAttemptsUsed == 2 and len(transport.calls) == 1
        assert owner.steps(run.id)[:2] == original and len(raw_rows("rule_candidates")) == 1
        assert raw_rows("rule_candidates")[0]["status"] == "pending"
    finally: assert shared.close(wait_seconds=0.1)["active"] == 0


@pytest.mark.parametrize("change", ["heartbeat", "cancel", "revoke", "takeover", "shutdown"])
def test_blocked_actual_tool_computation_cannot_commit_after_losing_authority(agent_storage, monkeypatch, change):
    import app.agents.tools as module
    from .test_agent_stop import revoke
    clock = [1000.0]
    owner, item, queued = create(agent_storage, owner=store(agent_storage, clock=lambda: clock[0]))
    run = owner.claim(queued.id, expected_row_version=0)
    entered, release = Event(), Event(); original = module.truth_result
    def blocked(*args):
        result = original(*args)
        entered.set()
        assert release.wait(3), "Owned test did not release actual computation"
        return result
    monkeypatch.setattr(module, "truth_result", blocked)
    shared, transport = gateway(agent_storage, [tool(run, "retrieve_truth"),
        dict(action="finish", needsHumanReason="Synthetic handoff")])
    try:
        with ThreadPoolExecutor(max_workers=1) as pool:
            future = pool.submit(drive, owner, shared, run)
            try:
                assert entered.wait(2)
                current = owner.read(run.id)
                assert current.checkpoint.toolAttemptsUsed == 1 and owner.steps(run.id)[1].state == "planned"
                if change == "heartbeat": owner.heartbeat(run.id, run.leaseToken)
                elif change == "cancel": owner.cancel(run.id, expected_row_version=current.rowVersion)
                elif change == "revoke": revoke(item)
                elif change == "takeover":
                    clock[0] += 31
                    replacement = owner.claim(run.id, expected_row_version=current.rowVersion)
                else: agent_storage.closed = True
            finally: release.set()
            status = future.result(timeout=3)
        rows = raw_rows("agent_steps")
        assert status.toolAttemptsUsed == 1
        if change == "heartbeat":
            assert rows[1]["state"] == "completed" and status.modelAttemptsUsed == 2 and len(transport.calls) == 2
            assert status.state == "needs_human" and status.reason is None
        else:
            assert rows[1]["state"] == "planned" and rows[1]["result_json"] is None
            assert status.modelAttemptsUsed == 1 and len(transport.calls) == 1
            if change == "takeover":
                assert status.state == "running" and owner.read(run.id).leaseToken == replacement.leaseToken
                assert len(rows) == 2 and status.deadlineAt == run.checkpoint.deadlineAt
            elif change == "cancel": assert status.state == "cancelled"
            elif change == "shutdown": assert status.reason == "shutting_down"
            else: assert status.reason == "source_changed"
        assert raw_rows("rule_candidates") == []
    finally:
        release.set()
        assert shared.close(wait_seconds=0.1)["active"] == 0
