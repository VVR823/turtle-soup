"""Model-selected synthetic trajectories exercise the actual durable loop."""
import json
from threading import Event

import pytest

from app import baselines
from .test_agent_store import agent_storage, running, raw_rows, create, store
from .test_agent_decisions import identity, reserve, outcome
from .test_feedback_storage import storage
from .test_model_gateway import ScriptedTransport


def tool(run, name):
    context = run.manifest.context
    args = dict(turnId=context.turnId) if name == "get_turn_trace" else dict(
        soupId=context.soupId, puzzleVersion=context.observedPuzzleVersion, query="Truth")
    return dict(action="tool", tool=name, arguments=args)


def gateway(active, values):
    from app.model_gateway import ModelGateway
    transport = ScriptedTransport([json.dumps(value) if isinstance(value, dict) else value for value in values])
    shared = ModelGateway(adapter_factory=lambda: transport)
    active.model_gateway = shared
    return shared, transport


def drive(owner, shared, run):
    from app.agents.repair_agent import RepairAgent
    from app.agents.tools import ToolExecutor
    return RepairAgent(owner, ToolExecutor(owner), shared).drive(run.id, run.leaseToken, Event())


@pytest.mark.parametrize("order", [("retrieve_truth", "get_turn_trace"), ("get_turn_trace", "retrieve_truth")])
def test_model_selects_different_actual_tool_orders_then_handoff_not_product_fixed_sequence(agent_storage, order):
    owner, _, run = running(agent_storage)
    shared, transport = gateway(agent_storage, [*(tool(run, name) for name in order),
        dict(action="finish", needsHumanReason="Synthetic evidence requires human review")])
    try:
        status = drive(owner, shared, run)
        steps = owner.steps(run.id)
        assert status.state == "needs_human" and status.reason is None
        assert [step.action.tool for step in steps if step.action.action == "tool"] == list(order)
        assert status.modelAttemptsUsed == 3 and status.toolAttemptsUsed == 2 and len(transport.calls) == 3
        assert len(steps) == 6 and steps[-1].action.action == "finish"
        assert all(step.state == "completed" for step in steps)
        assert "PRIVATE" not in status.model_dump_json()
    finally:
        assert shared.close(wait_seconds=0.1)["active"] == 0


def test_invalid_outputs_have_one_recorded_correction_then_handoff(agent_storage):
    owner, _, run = running(agent_storage)
    shared, transport = gateway(agent_storage, ["PRIVATE malformed output", "Different invalid output"])
    try:
        status = drive(owner, shared, run)
        assert status.state == "needs_human" and status.reason == "model_output_invalid"
        assert status.modelAttemptsUsed == 2 and status.toolAttemptsUsed == 0 and len(transport.calls) == 2
        decisions = [s for s in owner.steps(run.id) if s.action.action == "model_decision"]
        assert decisions[1].action.correctionOf == decisions[0].operationKey
        assert all(baselines.strict_json(s.resultJson)["status"] == "invalid" for s in decisions)
        assert len(owner.read(run.id).checkpoint.retryCounts) == 1
    finally:
        assert shared.close(wait_seconds=0.1)["active"] == 0


def test_actual_failed_tool_has_one_new_reserved_retry_not_infinite_model_or_tool_calls(agent_storage, monkeypatch):
    import app.agents.tools as module
    owner, _, run = running(agent_storage)
    def fail(*args, **kwargs): raise RuntimeError("PRIVATE synthetic failed computation")
    monkeypatch.setattr(module, "truth_result", fail)
    shared, transport = gateway(agent_storage, [tool(run, "retrieve_truth")])
    try:
        status = drive(owner, shared, run)
        assert status.state == "needs_human" and status.reason == "tool_failed"
        assert status.modelAttemptsUsed == 1 and status.toolAttemptsUsed == 2 and len(transport.calls) == 1
        tools = [s for s in owner.steps(run.id) if s.action.action == "tool"]
        assert len(tools) == 2 and all(s.state == "failed" for s in tools)
        assert len(owner.read(run.id).checkpoint.retryCounts) == 1
    finally:
        assert shared.close(wait_seconds=0.1)["active"] == 0


def test_typed_foreign_action_is_recorded_but_never_executed_or_auto_corrected(agent_storage):
    owner, _, run = running(agent_storage); selected = tool(run, "retrieve_truth")
    selected["arguments"]["soupId"] = "foreign"
    shared, transport = gateway(agent_storage, [selected])
    try:
        status = drive(owner, shared, run)
        assert status.state == "needs_human" and status.modelAttemptsUsed == 1 and status.toolAttemptsUsed == 0
        assert len(transport.calls) == 1 and not any(s.action.action == "tool" for s in owner.steps(run.id))
    finally:
        assert shared.close(wait_seconds=0.1)["active"] == 0


def test_original_deadline_expired_makes_zero_new_model_or_tool_attempts(agent_storage):
    clock = [1000.0]; owner = store(agent_storage, clock=lambda: clock[0])
    _, _, queued = create(agent_storage, owner=owner); run = owner.claim(queued.id, expected_row_version=0)
    clock[0] = 1181.0; shared, transport = gateway(agent_storage, [])
    try:
        status = drive(owner, shared, run)
        assert status.state == "needs_human" and status.reason == "deadline" and status.deadlineAt == 1180.0
        assert status.modelAttemptsUsed == status.toolAttemptsUsed == 0 and transport.calls == []
    finally:
        assert shared.close(wait_seconds=0.1)["active"] == 0


def test_tenth_stored_valid_finish_can_finish_without_an_eleventh_attempt(agent_storage):
    owner, _, run = running(agent_storage)
    for seq in range(10):
        execution = identity(run, seq); reserve(owner, execution); owner.complete_decision(execution, outcome())
    shared, transport = gateway(agent_storage, [])
    try:
        status = drive(owner, shared, run)
        assert status.state == "needs_human" and status.reason is None
        assert status.modelAttemptsUsed == 10 and transport.calls == [] and owner.steps(run.id)[-1].action.action == "finish"
    finally:
        assert shared.close(wait_seconds=0.1)["active"] == 0


def test_last_stored_tool_decision_at_model_limit_executes_remaining_tool_then_blocks_new_model(agent_storage):
    owner, _, run = running(agent_storage)
    for seq in range(10):
        execution = identity(run, seq); reserve(owner, execution)
        owner.complete_decision(execution, outcome(action=tool(run, "get_turn_trace")))
    shared, transport = gateway(agent_storage, [])
    try:
        status = drive(owner, shared, run)
        assert status.reason == "budget_exhausted" and status.modelAttemptsUsed == 10 and status.toolAttemptsUsed == 1
        assert transport.calls == [] and len([s for s in owner.steps(run.id) if s.action.action == "tool"]) == 1
    finally:
        assert shared.close(wait_seconds=0.1)["active"] == 0


def test_loop_implementation_is_registered_in_fixed_loaded_source_identity(agent_storage, monkeypatch):
    from pathlib import Path
    from app.agents.repair_agent import RepairAgent
    from app.agents.regression import FixedRegression
    from app.agents.contracts import AgentError
    assert callable(RepairAgent.drive)
    FixedRegression(agent_storage); original = Path.read_bytes
    def changed(path):
        value = original(path)
        return value + b"\n# synthetic loop update\n" if path.name == "repair_agent.py" else value
    monkeypatch.setattr(Path, "read_bytes", changed)
    with pytest.raises(AgentError) as caught: FixedRegression(agent_storage)
    assert caught.value.code == "agent_source_reload_required"
