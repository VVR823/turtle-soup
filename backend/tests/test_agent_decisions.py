"""Actual SQLite decision reservations conserve attempts and logical episodes."""
from uuid import uuid4

import pytest

from app import baselines
from .test_agent_store import agent_storage, running, raw_rows, store, create
from .test_feedback_storage import snapshot, storage


def identity(run, seq=0, *, token=None):
    from app.agents.contracts import ExecutionIdentity
    return ExecutionIdentity(runId=run.id, seq=seq, operationKey=str(uuid4()), leaseToken=token or run.leaseToken)


def reserve(owner, execution, *, correction=None, prompt="a", inputs="b"):
    return owner.reserve_decision(execution, prompt_digest=prompt * 64,
        input_digest=inputs * 64, correction_of=correction)


def outcome(*, status="valid", prompt="a", inputs="b", **changes):
    from app.agents.contracts import checked_model
    from app.agents.decision_contracts import DecisionResult
    body = dict(schemaVersion=1, status=status, promptDigest=prompt * 64, inputDigest=inputs * 64,
        action=dict(action="finish", needsHumanReason="Synthetic insufficient evidence") if status == "valid" else None,
        errorCode=None if status == "valid" else "model_output_invalid" if status == "invalid" else "model_unavailable")
    return checked_model(DecisionResult, {**body, **changes})


def test_tenth_actual_decision_reservation_leaves_zero_eleventh_has_no_row_or_refund(agent_storage):
    from app.agents.contracts import AgentError
    owner, _, run = running(agent_storage)
    for seq in range(10):
        value = reserve(owner, identity(run, seq))
        assert value.newly_created and value.step.action.action == "model_decision"
    saved = owner.read(run.id)
    assert saved.checkpoint.modelAttemptsUsed == 10 and saved.checkpoint.toolAttemptsUsed == 0
    assert len(raw_rows("agent_steps")) == 10
    before = snapshot()
    with pytest.raises(AgentError) as caught: reserve(owner, identity(run, 10))
    assert caught.value.code == "agent_model_budget_exhausted" and snapshot() == before


def test_decision_replay_is_not_another_attempt_and_changed_input_is_conflict(agent_storage):
    from app.agents.contracts import AgentError
    owner, _, run = running(agent_storage); execution = identity(run)
    first = reserve(owner, execution); before = snapshot()
    replay = reserve(owner, execution)
    assert first.newly_created and not replay.newly_created and replay.step == first.step
    assert snapshot() == before
    with pytest.raises(AgentError): reserve(owner, execution, inputs="c")
    assert snapshot() == before and owner.read(run.id).checkpoint.modelAttemptsUsed == 1


def test_decision_intent_counter_and_audit_rollback_together(agent_storage, monkeypatch):
    from app import audit_store
    from app.agents.contracts import AgentError
    owner, _, run = running(agent_storage); before = snapshot()
    def fail(*args, **kwargs): raise audit_store.AuditPersistenceError("PRIVATE synthetic failure")
    monkeypatch.setattr(audit_store, "insert_business_event", fail)
    with pytest.raises(AgentError): reserve(owner, identity(run))
    assert snapshot() == before and owner.read(run.id).checkpoint.modelAttemptsUsed == 0


def test_completed_actual_decision_survives_same_owner_heartbeat_and_immutable_replay(agent_storage):
    from app.agents.contracts import AgentError
    owner, _, run = running(agent_storage); execution = identity(run)
    reserve(owner, execution); owner.heartbeat(run.id, run.leaseToken)
    completed = owner.complete_decision(execution, outcome())
    assert completed.state == "completed" and baselines.strict_json(completed.resultJson)["status"] == "valid"
    before = snapshot()
    assert owner.complete_decision(execution, outcome()) == completed
    assert not reserve(owner, execution).newly_created and snapshot() == before
    with pytest.raises(AgentError): owner.complete_decision(execution, outcome(status="invalid"))
    assert snapshot() == before and owner.steps(run.id) == (completed,)


@pytest.mark.parametrize("field", ["promptDigest", "inputDigest"])
def test_decision_result_cannot_cross_stored_input_proof(agent_storage, field):
    from app.agents.contracts import AgentError
    owner, _, run = running(agent_storage); execution = identity(run)
    reserve(owner, execution); before = snapshot()
    with pytest.raises(AgentError): owner.complete_decision(execution, outcome(**{field: "c" * 64}))
    assert snapshot() == before and raw_rows("agent_steps")[0]["state"] == "planned"


def test_invalid_episode_has_one_durable_correction_different_body_cannot_reset_it(agent_storage):
    from app.agents.contracts import AgentError
    owner, _, run = running(agent_storage); first = identity(run)
    reserve(owner, first); owner.complete_decision(first, outcome(status="invalid"))
    correction = identity(run, 1)
    reserve(owner, correction, correction=first.operationKey, inputs="c")
    owner.complete_decision(correction, outcome(status="invalid", inputs="c"))
    before = snapshot()
    for parent in (first.operationKey, correction.operationKey):
        with pytest.raises(AgentError): reserve(owner, identity(run, 2), correction=parent, inputs="d")
        assert snapshot() == before
    unrelated = identity(run, 2)
    reserve(owner, unrelated); owner.complete_decision(unrelated, outcome(status="invalid"))
    reserve(owner, identity(run, 3), correction=unrelated.operationKey)
    checkpoint = owner.read(run.id).checkpoint
    assert checkpoint.modelAttemptsUsed == 4 and len(checkpoint.retryCounts) == 2
    assert all(item.kind == "model" and item.used == 1 for item in checkpoint.retryCounts)


def test_uncertain_planned_decision_retry_consumes_new_attempt_no_free_reexecution(agent_storage):
    owner, _, run = running(agent_storage); first = identity(run)
    reserve(owner, first)
    reserve(owner, identity(run, 1), correction=first.operationKey)
    assert owner.read(run.id).checkpoint.modelAttemptsUsed == 2
    assert len(raw_rows("agent_steps")) == 2 and all(row["state"] == "planned" for row in raw_rows("agent_steps"))


def test_correction_parent_cannot_be_foreign_or_valid_decision(agent_storage):
    from app.agents.contracts import AgentError
    owner, _, run = running(agent_storage); first = identity(run)
    reserve(owner, first); owner.complete_decision(first, outcome())
    for parent in (first.operationKey, str(uuid4())):
        before = snapshot()
        with pytest.raises(AgentError): reserve(owner, identity(run, 1), correction=parent)
        assert snapshot() == before


@pytest.mark.parametrize("changes", [dict(status="valid", action=None), dict(status="invalid", errorCode=None),
    dict(status="invalid", action=dict(action="finish", needsHumanReason="Synthetic")),
    dict(schemaVersion=True), dict(rawOutput="PRIVATE synthetic"), dict(reasoning="PRIVATE synthetic"),
    dict(status="valid", errorCode="model_output_invalid")])
def test_closed_decision_result_refuses_forged_or_raw_payload_without_warnings(changes):
    from app.agents.contracts import AgentError
    with pytest.raises(AgentError): outcome(**changes)


def test_copied_decision_result_is_revalidated_at_completion(agent_storage):
    from app.agents.contracts import AgentError
    owner, _, run = running(agent_storage); execution = identity(run)
    reserve(owner, execution); before = snapshot()
    corrupt = outcome().model_copy(update={"action": {"action": "tool", "tool": "shell", "arguments": {}}})
    with pytest.raises(AgentError): owner.complete_decision(execution, corrupt)
    assert snapshot() == before


def test_internal_decision_is_not_an_owned_tool_result_or_failed_tool(agent_storage):
    from app.agents.contracts import AgentError
    from app.agents.tool_contracts import trace_result
    owner, _, run = running(agent_storage); execution = identity(run)
    reserve(owner, execution); before = snapshot()
    for operation in (lambda: owner.complete_tool(execution, trace_result(run.manifest.context)),
        lambda: owner.fail_step(execution, "agent_tool_failed")):
        with pytest.raises(AgentError) as caught: operation()
        assert caught.value.code == "agent_step_conflict" and snapshot() == before


def test_completed_decision_cannot_be_used_as_candidate_regression_report(agent_storage):
    import json
    from app.agents.contracts import AgentError, parse_tool_action
    from .test_candidate_reports import inputs
    owner, _, run = running(agent_storage); decision = identity(run)
    reserve(owner, decision); owner.complete_decision(decision, outcome())
    _, draft, _ = inputs(run)
    save = identity(run, 1)
    action = parse_tool_action(json.dumps(dict(action="tool", tool="save_candidate_rule", arguments=dict(
        draft=draft.model_dump(mode="json"), regressionReportId=decision.operationKey))))
    owner.plan_step(save, action); before = snapshot()
    with pytest.raises(AgentError) as caught: owner.save_candidate(save, draft, decision.operationKey)
    assert caught.value.code == "agent_report_unavailable" and snapshot() == before


def test_new_decision_implementation_is_in_fixed_loaded_source_identity(agent_storage, monkeypatch):
    from pathlib import Path
    from app.agents.regression import FixedRegression
    from app.agents.contracts import AgentError
    FixedRegression(agent_storage)
    original = Path.read_bytes
    def changed(path):
        payload = original(path)
        return payload + b"\n# synthetic new decision source\n" if path.name == "decision_contracts.py" else payload
    monkeypatch.setattr(Path, "read_bytes", changed)
    with pytest.raises(AgentError) as caught: FixedRegression(agent_storage)
    assert caught.value.code == "agent_source_reload_required"


def test_decision_completion_audit_failure_preserves_only_reserved_attempt(agent_storage, monkeypatch):
    from app import audit_store
    from app.agents.contracts import AgentError
    owner, _, run = running(agent_storage); execution = identity(run)
    reserve(owner, execution); before = snapshot()
    def fail(*args, **kwargs): raise audit_store.AuditPersistenceError("Synthetic completion failure")
    monkeypatch.setattr(audit_store, "insert_business_event", fail)
    with pytest.raises(AgentError): owner.complete_decision(execution, outcome())
    assert snapshot() == before and owner.read(run.id).checkpoint.modelAttemptsUsed == 1
    assert raw_rows("agent_steps")[0]["state"] == "planned"


def test_actual_takeover_denies_old_owner_decision_completion(agent_storage):
    from app.agents.contracts import AgentError
    clock = [1000.0]; owner = store(agent_storage, clock=lambda: clock[0])
    _, _, queued = create(agent_storage, owner=owner)
    old = owner.claim(queued.id, expected_row_version=0); execution = identity(old)
    reserve(owner, execution); clock[0] += 31
    current = owner.claim(old.id, expected_row_version=owner.read(old.id).rowVersion); before = snapshot()
    with pytest.raises(AgentError): owner.complete_decision(execution, outcome())
    assert snapshot() == before and owner.read(old.id).leaseToken == current.leaseToken
    assert owner.read(old.id).checkpoint.modelAttemptsUsed == 1


@pytest.mark.parametrize("action", ["model_decision", "server_stop"])
def test_internal_stored_actions_never_enter_the_public_model_parser(action):
    import json
    from app.agents.contracts import AgentError, parse_agent_action
    with pytest.raises(AgentError): parse_agent_action(json.dumps(dict(action=action, schemaVersion=1)))
