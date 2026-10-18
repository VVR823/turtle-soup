"""Server-only tool retries conserve the same durable global budget."""
import json

import pytest

from .test_agent_store import agent_storage, running, step_inputs, raw_rows
from .test_agent_decisions import identity
from .test_feedback_storage import storage, snapshot


def failed(owner, run):
    execution, action = step_inputs(run)
    owner.plan_step(execution, action); owner.fail_step(execution, "agent_tool_failed")
    return execution, action


def test_one_retry_of_same_tool_is_durable_even_if_second_attempt_fails(agent_storage):
    from app.agents.contracts import AgentError
    owner, _, run = running(agent_storage); root, action = failed(owner, run)
    retry = identity(run, 1)
    value = owner.reserve_step(retry, action, retry_of=root.operationKey)
    assert value.newly_created and owner.read(run.id).checkpoint.toolAttemptsUsed == 2
    owner.fail_step(retry, "agent_tool_failed"); before = snapshot()
    for parent in (root.operationKey, retry.operationKey):
        with pytest.raises(AgentError): owner.reserve_step(identity(run, 2), action, retry_of=parent)
        assert snapshot() == before
    counts = owner.read(run.id).checkpoint.retryCounts
    assert len(counts) == 1 and counts[0].kind == "tool" and counts[0].used == 1


def test_uncertain_tool_retry_runs_new_reserved_attempt_and_completed_replay_is_not_reexecuted(agent_storage):
    from app.agents.tools import ToolExecutor
    owner, _, run = running(agent_storage); original, action = step_inputs(run)
    owner.plan_step(original, action)
    retry = identity(run, 1); executor = ToolExecutor(owner)
    result = executor.execute(retry, action, retry_of=original.operationKey)
    assert result.tool == "retrieve_truth" and owner.read(run.id).checkpoint.toolAttemptsUsed == 2
    before = snapshot()
    assert executor.execute(retry, action, retry_of=original.operationKey) == result and snapshot() == before
    assert [row["state"] for row in raw_rows("agent_steps")] == ["planned", "completed"]


def test_retry_cannot_use_other_input_or_a_successful_tool_as_parent(agent_storage):
    from app.agents.contracts import AgentError, parse_tool_action
    from app.agents.tools import ToolExecutor
    owner, _, run = running(agent_storage); root, action = failed(owner, run)
    changed = action.model_dump(mode="json"); changed["arguments"]["query"] = "Different input"
    before = snapshot()
    with pytest.raises(AgentError): owner.reserve_step(identity(run, 1), parse_tool_action(json.dumps(changed)), retry_of=root.operationKey)
    assert snapshot() == before
    success = identity(run, 1); ToolExecutor(owner).execute(success, action)
    before = snapshot()
    with pytest.raises(AgentError): owner.reserve_step(identity(run, 2), action, retry_of=success.operationKey)
    assert snapshot() == before


def test_retry_counter_and_reservation_roll_back_if_actual_audit_fails(agent_storage, monkeypatch):
    from app import audit_store
    from app.agents.contracts import AgentError
    owner, _, run = running(agent_storage); root, action = failed(owner, run); before = snapshot()
    def fail(*args, **kwargs): raise audit_store.AuditPersistenceError("Synthetic retry failure")
    monkeypatch.setattr(audit_store, "insert_business_event", fail)
    with pytest.raises(AgentError): owner.reserve_step(identity(run, 1), action, retry_of=root.operationKey)
    assert snapshot() == before and owner.read(run.id).checkpoint.toolAttemptsUsed == 1
    assert owner.read(run.id).checkpoint.retryCounts == ()
