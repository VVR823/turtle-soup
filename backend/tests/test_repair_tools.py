"""Actual closed tool dispatch on owned temporary storage; no real model."""
import json
from uuid import uuid4

import pytest

from .test_agent_store import agent_storage, running, raw_rows, step_inputs
from .test_feedback_storage import storage, snapshot
from .test_candidate_reports import inputs


def executable(run, name, *, seq=0, **changes):
    from app.agents.contracts import parse_tool_action
    identity, _ = step_inputs(run, seq=seq)
    context = run.manifest.context
    args = {"get_turn_trace": {"turnId": context.turnId},
        "retrieve_truth": {"soupId": context.soupId, "puzzleVersion": context.observedPuzzleVersion, "query": "Truth"}}
    if name == "find_rule_conflicts":
        _, draft, _ = inputs(run)
        args[name] = dict(baseRuleVersion=draft.baseRuleVersion, draft=draft.model_dump(mode="json"))
    action = dict(action="tool", tool=name, arguments={**args.get(name, {}), **changes})
    return identity, parse_tool_action(json.dumps(action))


@pytest.mark.parametrize("name", ["get_turn_trace", "retrieve_truth", "find_rule_conflicts"])
def test_read_tools_execute_once_store_typed_result_and_replay_without_new_attempt(agent_storage, name):
    from app.agents.tools import ToolExecutor
    owner, _, run = running(agent_storage)
    identity, action = executable(run, name)
    executor = ToolExecutor(owner)
    first = executor.execute(identity, action)
    before = snapshot()
    assert executor.execute(identity, action) == first and snapshot() == before
    assert first.tool == name and owner.read(run.id).checkpoint.toolAttemptsUsed == 1
    assert len(raw_rows("agent_steps")) == 1 and raw_rows("agent_steps")[0]["state"] == "completed"
    assert "PRIVATE synthetic claim" not in first.model_dump_json() and agent_storage.model.calls == []
    if name == "get_turn_trace": assert first.claimsOnly is True
    if name == "retrieve_truth": assert [f.sourcePath for f in first.facts] == ["bottom", "checkpoints[0]"]
    if name == "find_rule_conflicts": assert first.conflict.answerSupported is None


@pytest.mark.parametrize("name,args", [("shell", {"command": "synthetic"}), ("sql", {"query": "SELECT private"}),
    ("publish", {}), ("web_search", {"url": "https://synthetic.invalid"})])
def test_dispatch_never_maps_unknown_tool_to_python_or_external_effect(agent_storage, name, args):
    from app.agents.contracts import AgentError
    from app.agents.tools import ToolExecutor
    owner, _, run = running(agent_storage); identity, _ = step_inputs(run)
    before = snapshot()
    with pytest.raises(AgentError): ToolExecutor(owner).execute(identity,
        json.dumps(dict(action="tool", tool=name, arguments=args)))
    assert snapshot() == before and agent_storage.model.calls == []


@pytest.mark.parametrize("name,changes", [("get_turn_trace", {"turnId": str(uuid4())}),
    ("retrieve_truth", {"soupId": "foreign"}), ("retrieve_truth", {"puzzleVersion": "p1:" + "e" * 64})])
def test_dispatch_cannot_borrow_another_turn_or_puzzle(agent_storage, name, changes):
    from app.agents.contracts import AgentError
    from app.agents.tools import ToolExecutor
    owner, _, run = running(agent_storage); identity, action = executable(run, name, **changes)
    before = snapshot()
    with pytest.raises(AgentError): ToolExecutor(owner).execute(identity, action)
    assert snapshot() == before and raw_rows("agent_steps") == []


def test_existing_uncertain_intent_is_not_executed_again_under_same_attempt(agent_storage):
    from app.agents.contracts import AgentError
    from app.agents.tools import ToolExecutor
    owner, _, run = running(agent_storage); identity, action = executable(run, "retrieve_truth")
    owner.plan_step(identity, action); before = snapshot()
    with pytest.raises(AgentError) as caught: ToolExecutor(owner).execute(identity, action)
    assert caught.value.code == "agent_step_uncertain" and snapshot() == before
    assert owner.read(run.id).checkpoint.toolAttemptsUsed == 1


def test_missing_corpus_regression_retains_safety_results_but_is_incomplete(agent_storage):
    from app.agents.tools import ToolExecutor
    owner, _, run = running(agent_storage); identity, _, action = inputs(run)
    value = ToolExecutor(owner).execute(identity, action)
    assert value.status == "incomplete" and value.cleanupConfirmed
    assert any(r.code == "needs_corpus" for r in value.caseResults)
    assert value.inputCaseCount >= value.attemptedCaseCount >= 1
    assert raw_rows("agent_steps")[0]["state"] == "completed" and agent_storage.model.calls == []


def test_executor_only_computes_outside_transaction_then_rechecks_permission(agent_storage, monkeypatch):
    from app.agents.contracts import AgentError
    from app.agents.tools import ToolExecutor
    from app.feedback_contract import PrivacyReview
    from app.feedback_store import set_model_permission
    import app.agents.tools as module
    owner, item, run = running(agent_storage); identity, action = executable(run, "get_turn_trace")
    original = module.trace_result
    def withdraw(context):
        # A separate real write transaction succeeds here only if execution
        # does not hold the store's computation transaction open.
        set_model_permission(item.id, item.rowVersion, review=PrivacyReview(safeForModel=False, reviewNote="Synthetic revoke"))
        return original(context)
    monkeypatch.setattr(module, "trace_result", withdraw)
    with pytest.raises(AgentError): ToolExecutor(owner).execute(identity, action)
    assert raw_rows("agent_steps")[0]["state"] == "planned"
    assert raw_rows("agent_steps")[0]["result_json"] is None


def test_actual_save_tool_uses_stored_owned_report_and_returns_pending_only(agent_storage):
    from app.agents.tools import ToolExecutor
    from .test_candidate_reports import prepared_report, save_inputs
    owner, _, run, regression, draft, _ = prepared_report(agent_storage)
    identity, action = save_inputs(run, draft, regression.operationKey)
    executor = ToolExecutor(owner)
    result = executor.execute(identity, action); before = snapshot()
    assert result.status == "pending" and result.runId == run.id
    assert executor.execute(identity, action) == result and snapshot() == before
    assert owner.read(run.id).checkpoint.toolAttemptsUsed == 2
    assert raw_rows("agent_steps")[1]["state"] == "completed"


def test_failed_tool_replay_keeps_stable_failure_without_recomputing(agent_storage, monkeypatch):
    from app.agents.contracts import AgentError
    from app.agents.tools import ToolExecutor
    import app.agents.tools as module
    owner, _, run = running(agent_storage); identity, action = executable(run, "get_turn_trace")
    def unavailable(context): raise RuntimeError("PRIVATE synthetic traceback")
    monkeypatch.setattr(module, "trace_result", unavailable)
    executor = ToolExecutor(owner)
    with pytest.raises(AgentError) as caught: executor.execute(identity, action)
    assert str(caught.value) == "agent_tool_failed"
    before = snapshot(); result = executor.execute(identity, action)
    assert result.code == "agent_tool_failed" and snapshot() == before
    assert owner.read(run.id).checkpoint.toolAttemptsUsed == 1


def test_same_owner_heartbeat_during_computation_does_not_invalidate_result(agent_storage, monkeypatch):
    from app.agents.tools import ToolExecutor
    import app.agents.tools as module
    owner, _, run = running(agent_storage); identity, action = executable(run, "get_turn_trace")
    original = module.trace_result
    def heartbeat(context):
        owner.heartbeat(run.id, run.leaseToken)
        return original(context)
    monkeypatch.setattr(module, "trace_result", heartbeat)
    result = ToolExecutor(owner).execute(identity, action)
    assert result.tool == "get_turn_trace" and raw_rows("agent_steps")[0]["state"] == "completed"
    assert owner.read(run.id).checkpoint.toolAttemptsUsed == 1
