"""Prompt reconstruction from actual safe owned records, not gold history."""
import json

import pytest

from app import baselines
from .test_agent_store import agent_storage, running, step_inputs
from .test_agent_decisions import identity, reserve, outcome
from .test_feedback_storage import storage


def prepared(run, steps=()):
    from app.agents.agent_prompt import build_decision_messages
    return build_decision_messages(run, steps)


def test_prompt_exposes_actual_safe_scope_and_diagnostic_not_raw_feedback_or_fact_payload(agent_storage):
    owner, _, run = running(agent_storage)
    value = prepared(run)
    assert len(value.messages) == 2 and value.messages[0].type == "system" and value.messages[1].type == "human"
    payload = baselines.strict_json(value.messages[1].content)
    context = payload["context"]
    assert context["turnId"] == run.manifest.context.turnId and context["soupId"] == "synthetic"
    assert context["programDiagnostic"]["answer"] == "是"
    assert context["claimsAreGold"] is False and context["sanitizedInput"]["expectedClaim"] == "不知道"
    assert all(set(fact) == {"id", "sourcePath", "category"} for fact in context["factScope"])
    text = "".join(message.content for message in value.messages)
    assert "PRIVATE synthetic claim" not in text and "rawTrace" not in text and "holdout" not in value.messages[1].content
    assert len(text) <= 8000 and value.inputDigest == baselines.digest(payload)
    assert owner.read(run.id).checkpoint.modelAttemptsUsed == 0


def test_prompt_contains_actual_failed_tool_not_a_fabricated_answer_or_success(agent_storage):
    owner, _, run = running(agent_storage); execution, action = step_inputs(run)
    owner.plan_step(execution, action); owner.fail_step(execution, "agent_tool_failed")
    value = prepared(owner.read(run.id), owner.steps(run.id))
    payload = baselines.strict_json(value.messages[1].content)
    assert payload["steps"][0]["seq"] == 0 and payload["steps"][0]["state"] == "failed"
    assert payload["steps"][0]["result"] == {"schemaVersion": 1, "code": "agent_tool_failed"}
    assert "answer" not in payload["steps"][0]["result"]
    assert payload["budget"]["modelAttemptsUsed"] == 0 and payload["budget"]["toolAttemptsUsed"] == 1


def test_prompt_retains_uncertain_decision_as_planned_and_input_digest_changes_after_actual_result(agent_storage):
    owner, _, run = running(agent_storage); execution = identity(run)
    reserve(owner, execution)
    first = prepared(owner.read(run.id), owner.steps(run.id))
    payload = baselines.strict_json(first.messages[1].content)
    assert payload["steps"][0]["state"] == "planned" and payload["steps"][0]["result"] is None
    owner.complete_decision(execution, outcome(status="invalid"))
    second = prepared(owner.read(run.id), owner.steps(run.id))
    assert first.inputDigest != second.inputDigest and first.promptDigest == second.promptDigest
    actual = baselines.strict_json(second.messages[1].content)["steps"][0]["result"]
    assert actual["status"] == "invalid" and actual["action"] is None and actual["errorCode"] == "model_output_invalid"


def test_prompt_rejects_foreign_gap_or_duplicate_execution_history(agent_storage):
    from app.agents.contracts import AgentError
    owner, _, run = running(agent_storage); execution = identity(run)
    reserve(owner, execution); step = owner.steps(run.id)[0]
    for steps in ((step.model_copy(update={"runId": identity(run).operationKey}),),
        (step.model_copy(update={"seq": 1}),), (step, step)):
        with pytest.raises(AgentError): prepared(owner.read(run.id), steps)


def test_prompt_does_not_truncate_large_actual_decision_history_to_fake_a_success(agent_storage):
    from app.agents.contracts import AgentError
    owner, _, run = running(agent_storage)
    for seq in range(9):
        execution = identity(run, seq); reserve(owner, execution)
        result = outcome(action=dict(action="finish", needsHumanReason=str(seq) + "x" * 999))
        owner.complete_decision(execution, result)
    with pytest.raises(AgentError) as caught: prepared(owner.read(run.id), owner.steps(run.id))
    assert caught.value.code == "agent_context_too_large" and len(owner.steps(run.id)) == 9


def test_prompt_report_summary_retains_full_denominator_and_every_failure_without_gold(agent_storage):
    from app.agents.contracts import parse_tool_action
    from .test_fixed_regression import regression_inputs, invoke
    from app.agents.regression import FixedRegression
    values = regression_inputs(agent_storage); owner, run, execution, draft, _, _ = values
    owner.plan_step(execution, parse_tool_action(json.dumps(dict(action="tool", tool="run_regression",
        arguments=dict(draft=draft.model_dump(mode="json"))))))
    report = invoke(FixedRegression(agent_storage), values)
    owner.complete_regression(execution, report)
    result = baselines.strict_json(prepared(owner.read(run.id), owner.steps(run.id)).messages[1].content)["steps"][0]["result"]
    assert result["status"] == "incomplete" and result["inputCaseCount"] == 6
    assert result["attemptedCaseCount"] == 6 and result["passedCaseCount"] == 5
    assert result["failedCases"] == [dict(caseId=report.caseResults[-1].caseId, suite="dev_regression", passed=False, code="needs_corpus")]
    assert result["reportDigest"] == baselines.digest(report.model_dump(mode="json"))
    assert "gold" not in result and "caseResults" not in result


def test_prompt_revalidates_copied_manifest_and_unsafe_tool_result(agent_storage):
    from app.agents.contracts import AgentError
    owner, _, run = running(agent_storage)
    with pytest.raises(AgentError): prepared(run.model_copy(update={"manifest": {"raw": "PRIVATE"}}))
    execution, action = step_inputs(run); owner.plan_step(execution, action)
    step = owner.steps(run.id)[0]
    with pytest.raises(AgentError): prepared(owner.read(run.id), (step.model_copy(update={
        "state": "completed", "resultJson": '{"rawTrace":"PRIVATE synthetic"}'}),))


def test_repeated_history_references_exact_earlier_action_result_without_losing_states(agent_storage):
    from app.agents.contracts import parse_tool_action
    from app.agents.tools import ToolExecutor
    owner, _, run = running(agent_storage)
    selected = dict(action="tool", tool="get_turn_trace", arguments=dict(turnId=run.manifest.context.turnId))
    for seq in (0, 2):
        decision = identity(run, seq); reserve(owner, decision)
        owner.complete_decision(decision, outcome(action=selected))
        ToolExecutor(owner).execute(identity(run, seq + 1), parse_tool_action(json.dumps(selected)))
    records = owner.steps(run.id)
    payload = baselines.strict_json(prepared(owner.read(run.id), records).messages[1].content)
    history = payload["steps"]
    assert [(s["seq"], s["operationKey"], s["state"]) for s in history] == [
        (s.seq, s.operationKey, s.state) for s in records]
    assert history[0]["result"]["action"] == selected
    assert history[1]["action"] == history[2]["result"]["action"] == history[3]["action"] == {"sameActionAsSeq": 0}
    assert history[1]["result"] == baselines.strict_json(records[1].resultJson)
    assert history[3]["result"] == dict(sameResultAsSeq=1, resultDigest=baselines.digest(history[1]["result"]))
    assert records[1].resultJson == records[3].resultJson
    assert all("inputDigest" not in s["action"] for s in history if s["action"].get("action") == "model_decision")
    assert baselines.strict_json(records[0].resultJson)["inputDigest"]  # Stored audit is not removed.


def test_new_prompt_code_is_in_fixed_loaded_execution_identity(agent_storage, monkeypatch):
    from pathlib import Path
    from app.agents.regression import FixedRegression
    from app.agents.contracts import AgentError
    prepared(running(agent_storage)[2])
    FixedRegression(agent_storage)
    original = Path.read_bytes
    def changed(path):
        value = original(path)
        return value + b"\n# synthetic prompt update\n" if path.name == "agent_prompt.py" else value
    monkeypatch.setattr(Path, "read_bytes", changed)
    with pytest.raises(AgentError) as caught: FixedRegression(agent_storage)
    assert caught.value.code == "agent_source_reload_required"
