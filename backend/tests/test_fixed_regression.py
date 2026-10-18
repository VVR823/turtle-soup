"""Fixed program safety results are not human/real-model answer evidence."""
from uuid import uuid4

import pytest

from .test_agent_store import agent_storage, running, raw_rows
from .test_feedback_storage import storage, snapshot
from .test_candidate_reports import inputs


def regression_inputs(active):
    from app import baselines
    from app.rule_contract import read_rule_snapshot
    owner, _, run = running(active)
    identity, draft, _ = inputs(run)
    with owner._transaction(write=False) as conn:
        soup = baselines.session_soup(conn, draft.puzzleVersion)
        rules = read_rule_snapshot(conn, draft.puzzleVersion, draft.baseRuleVersion)
    return owner, run, identity, draft, soup, rules


def invoke(executor, values, **changes):
    _, run, identity, draft, soup, rules = values
    return executor.run(draft, **{**dict(run=run, identity=identity, soup=soup, rule_snapshot=rules), **changes})


def test_missing_corpus_preserves_actual_fixed_safety_and_never_returns_complete(agent_storage):
    from app.agents.regression import FixedRegression
    values = regression_inputs(agent_storage); before = snapshot()
    value = invoke(FixedRegression(agent_storage), values)
    assert value.status == "incomplete" and value.cleanupConfirmed
    assert value.inputCaseCount == value.attemptedCaseCount == 6
    assert value.passedCaseCount == 5
    assert [r.code for r in value.caseResults] == ["passed"] * 5 + ["needs_corpus"]
    assert value.evidenceKind == "deterministic_regression" and not value.truncated
    assert value.reportId == values[2].operationKey and value.runId == values[1].id
    assert value.contextDigest == values[1].manifest.contextDigest
    assert snapshot() == before and agent_storage.model.calls == []
    assert agent_storage.model_gateway is None and raw_rows("agent_steps") == []
    assert "PRIVATE" not in value.model_dump_json() and len(value.model_dump_json().encode()) < 32768


@pytest.mark.parametrize("field,value", [("runId", str(uuid4())), ("leaseToken", str(uuid4()))])
def test_regression_rejects_foreign_server_identity_before_computation(agent_storage, field, value):
    from app.agents.regression import FixedRegression
    from app.agents.contracts import AgentError
    values = regression_inputs(agent_storage); before = snapshot()
    with pytest.raises(AgentError): invoke(FixedRegression(agent_storage), values,
        identity=values[2].model_copy(update={field: value}))
    assert snapshot() == before and agent_storage.model_gateway is None


def test_expired_original_run_deadline_retains_plan_and_does_not_touch_live_gateway(agent_storage):
    from app.agents.regression import FixedRegression
    values = regression_inputs(agent_storage)
    value = invoke(FixedRegression(agent_storage, utc_clock=lambda: values[1].checkpoint.deadlineAt), values)
    assert value.status == "incomplete" and value.passedCaseCount == 0
    assert value.inputCaseCount == 6 and value.attemptedCaseCount < value.inputCaseCount
    assert value.caseResults[0].code == "deadline" and value.cleanupConfirmed
    assert agent_storage.model_gateway is None


def test_fixed_regression_revalidates_changed_source_even_without_corpus(agent_storage):
    from app.agents.regression import FixedRegression
    from app.agents.contracts import AgentError
    values = regression_inputs(agent_storage)
    with pytest.raises(AgentError): invoke(FixedRegression(agent_storage), values,
        soup=values[4].model_copy(update={"bottom": "Changed synthetic source"}))


def test_owned_fake_cleanup_unknown_prevents_completion_and_is_not_faked_true(agent_storage, monkeypatch):
    from app.agents.regression import FixedRegression
    from app.model_gateway import ModelGateway
    original = ModelGateway.close
    def unknown(self, **kwargs):
        result = original(self, **kwargs)
        return {**result, "active": 1}
    monkeypatch.setattr(ModelGateway, "close", unknown)
    value = invoke(FixedRegression(agent_storage), regression_inputs(agent_storage))
    assert value.status == "incomplete" and value.cleanupConfirmed is False
    assert agent_storage.model_gateway is None


def test_safety_counterexample_is_failed_not_hidden_by_missing_corpus(agent_storage, monkeypatch):
    from app.agents.regression import FixedRegression
    import app.agents.regression as module
    monkeypatch.setattr(module, "parse_tool_action", lambda raw: object())
    value = invoke(FixedRegression(agent_storage), regression_inputs(agent_storage))
    assert value.status == "failed" and value.caseResults[0].code == "probe_failed"
    assert any(r.code == "needs_corpus" for r in value.caseResults)


def test_fixed_suite_identity_does_not_depend_on_model_chosen_draft(agent_storage):
    from app.agents.regression import FixedRegression
    values = regression_inputs(agent_storage); executor = FixedRegression(agent_storage)
    first = invoke(executor, values)
    changed = (*values[:3], values[3].model_copy(update={"evidenceSummary": "Different synthetic explanation"}), *values[4:])
    second = invoke(executor, changed)
    assert first.suiteManifestDigest == second.suiteManifestDigest == executor.suite_manifest_digest
    assert first.draftDigest != second.draftDigest


def test_fixed_fake_probes_do_not_pollute_inherited_real_request_model_observations(agent_storage):
    from app.agents.regression import FixedRegression
    from app.audit_context import AttemptCollector, attempt_context
    collector = AttemptCollector(str(uuid4()), traffic_class="real")
    with attempt_context(collector):
        invoke(FixedRegression(agent_storage), regression_inputs(agent_storage))
    event = collector.finish(status_code=200, method="POST", route_template="unmatched",
        response_started=True, disconnected=False)
    assert event.details.modelCalls == () and not event.details.modelCallsTruncated


def test_five_second_budget_exhaustion_never_turns_into_complete_or_zero_denominator(agent_storage, monkeypatch):
    from app.agents.regression import FixedRegression
    import app.agents.regression as module
    state = [0.0]
    original = module.parse_tool_action
    def consume(raw):
        state[0] = 6.0
        return original(raw)
    values = regression_inputs(agent_storage)
    monkeypatch.setattr(module, "parse_tool_action", consume)
    value = invoke(FixedRegression(agent_storage, clock=lambda: state[0]), values)
    assert value.status == "incomplete" and value.inputCaseCount == 6
    assert value.attemptedCaseCount == 1 and value.caseResults[0].code == "deadline"
    assert value.elapsedSeconds == 6.0 and value.passedCaseCount == 0
    assert agent_storage.model_gateway is None


@pytest.mark.parametrize("asset", ["rag.py", "prompts.py", "audit_context.py", "task_context.py"])
def test_execution_dependency_change_invalidates_fixed_suite_identity(agent_storage, monkeypatch, asset):
    from pathlib import Path
    from app.agents.regression import FixedRegression
    original_digest = FixedRegression(agent_storage).suite_manifest_digest
    original_read = Path.read_bytes
    def changed(path):
        value = original_read(path)
        return value + b"\n# owned synthetic changed implementation\n" if path.name == asset else value
    monkeypatch.setattr(Path, "read_bytes", changed)
    from app.agents.contracts import AgentError
    with pytest.raises(AgentError) as caught: FixedRegression(agent_storage)
    assert caught.value.code == "agent_source_reload_required" and original_digest
