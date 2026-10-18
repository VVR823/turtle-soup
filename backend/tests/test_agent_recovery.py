"""Actual interrupted ledgers inherit budgets, results and original deadline."""
import json

from app import baselines
from .test_agent_store import agent_storage, running, raw_rows, step_inputs
from .test_agent_decisions import identity, reserve, outcome
from .test_feedback_storage import storage
from .test_repair_agent_loop import gateway, drive, tool


def finish():
    return dict(action="finish", needsHumanReason="Synthetic recovery handoff")


def test_uncertain_planned_model_call_uses_new_attempt_and_same_episode(agent_storage):
    owner, _, run = running(agent_storage); execution = identity(run)
    reserve(owner, execution)
    shared, transport = gateway(agent_storage, [finish()])
    try:
        status = drive(owner, shared, run)
        steps = owner.steps(run.id)
        assert status.state == "needs_human" and status.modelAttemptsUsed == 2
        assert len(transport.calls) == 1 and steps[0].state == "planned"
        assert steps[1].action.correctionOf == steps[0].operationKey and steps[1].operationKey != steps[0].operationKey
    finally: assert shared.close(wait_seconds=0.1)["active"] == 0


def test_computed_tool_without_result_is_unknown_and_retry_spends_new_budget(agent_storage):
    owner, _, run = running(agent_storage); selected = tool(run, "get_turn_trace")
    decision = identity(run); reserve(owner, decision); owner.complete_decision(decision, outcome(action=selected))
    from app.agents.contracts import parse_tool_action
    from app.agents.tool_contracts import trace_result
    execution = identity(run, 1); owner.plan_step(execution, parse_tool_action(json.dumps(selected)))
    # Actual computation occurred but no completion transaction was committed.
    computed = trace_result(run.manifest.context)
    assert computed.tool == "get_turn_trace" and raw_rows("agent_steps")[1]["result_json"] is None
    shared, transport = gateway(agent_storage, [finish()])
    try:
        status = drive(owner, shared, run); steps = owner.steps(run.id)
        assert status.toolAttemptsUsed == 2 and status.modelAttemptsUsed == 2 and len(transport.calls) == 1
        assert steps[1].state == "planned" and steps[2].state == "completed" and steps[2].operationKey != execution.operationKey
        assert len(owner.read(run.id).checkpoint.retryCounts) == 1
    finally: assert shared.close(wait_seconds=0.1)["active"] == 0


def test_completed_tool_after_restart_is_replayed_as_history_not_another_execution(agent_storage):
    from app.agents.contracts import parse_tool_action
    from app.agents.tools import ToolExecutor
    owner, _, run = running(agent_storage); selected = tool(run, "get_turn_trace")
    decision = identity(run); reserve(owner, decision); owner.complete_decision(decision, outcome(action=selected))
    ToolExecutor(owner).execute(identity(run, 1), parse_tool_action(json.dumps(selected)))
    original = owner.steps(run.id)[1]
    shared, transport = gateway(agent_storage, [finish()])
    try:
        status = drive(owner, shared, run)
        assert status.toolAttemptsUsed == 1 and status.modelAttemptsUsed == 2 and len(transport.calls) == 1
        assert owner.steps(run.id)[1] == original and len([s for s in owner.steps(run.id) if s.action.action == "tool"]) == 1
    finally: assert shared.close(wait_seconds=0.1)["active"] == 0


def test_nine_model_seven_tool_actual_ledger_resumes_only_remaining_one_each(agent_storage):
    from app.agents.contracts import parse_tool_action
    from app.agents.tools import ToolExecutor
    owner, _, run = running(agent_storage); selected = tool(run, "get_turn_trace")
    for round_index in range(7):
        decision = identity(run, round_index * 2)
        reserve(owner, decision); owner.complete_decision(decision, outcome(action=selected))
        ToolExecutor(owner).execute(identity(run, round_index * 2 + 1), parse_tool_action(json.dumps(selected)))
    invalid = identity(run, 14); reserve(owner, invalid); owner.complete_decision(invalid, outcome(status="invalid"))
    corrected = identity(run, 15); reserve(owner, corrected, correction=invalid.operationKey)
    owner.complete_decision(corrected, outcome(action=selected))
    before = owner.read(run.id)
    assert before.checkpoint.modelAttemptsUsed == 9 and before.checkpoint.toolAttemptsUsed == 7
    shared, transport = gateway(agent_storage, [finish()])
    try:
        status = drive(owner, shared, run)
        from app.agents.agent_prompt import _history, _SYSTEM_PROMPT
        records = owner.steps(run.id)
        prompt_sizes = dict(system=len(_SYSTEM_PROMPT), context=len(baselines.canonical_json(
            before.manifest.context.model_dump(mode="json", exclude={"factScope"}))),
            history=len(baselines.canonical_json(_history(records[:-1]))),
            factScope=len(baselines.canonical_json([dict(id=f.id, sourcePath=f.sourcePath,
                category=f.category) for f in before.manifest.context.factScope])),
            budget=len(baselines.canonical_json(before.checkpoint.model_dump(mode="json"))))
        assert status.state == "needs_human" and status.reason is None, json.dumps(prompt_sizes)
        assert status.modelAttemptsUsed == 10 and status.toolAttemptsUsed == 8 and len(transport.calls) == 1
        assert status.deadlineAt == before.checkpoint.deadlineAt and len(owner.steps(run.id)) == 19
    finally: assert shared.close(wait_seconds=0.1)["active"] == 0
