"""Terminal-only writes never restore withdrawn model or execution authority."""
from uuid import uuid4

import pytest

from app import baselines
from .test_agent_store import agent_storage, running, create, store, raw_rows, step_inputs
from .test_agent_decisions import identity, reserve, outcome
from .test_feedback_storage import snapshot, storage


def revoke(item):
    from app.feedback_contract import PrivacyReview
    from app.feedback_store import set_model_permission
    set_model_permission(item.id, item.rowVersion, review=PrivacyReview(safeForModel=False, reviewNote="Synthetic revoke"))


def test_withdrawn_task_can_stop_and_show_minimal_status_but_cannot_restore_model_access(agent_storage):
    from app.agents.contracts import AgentError
    owner, item, run = running(agent_storage); execution = identity(run)
    reserve(owner, execution); revoke(item)
    with pytest.raises(AgentError): owner.read(run.id)
    status = owner.stop(run.id, lease_token=run.leaseToken, state="needs_human", reason="permission_revoked")
    assert status.state == "needs_human" and status.reason == "permission_revoked"
    assert status.modelAttemptsUsed == 1 and status.toolAttemptsUsed == 0
    shown = owner.read_status(run.id)
    assert shown == status and "PRIVATE" not in shown.model_dump_json()
    assert not hasattr(shown, "manifest") and not hasattr(shown, "leaseToken") and not hasattr(shown, "context")
    assert raw_rows("agent_runs")[0]["lease_token"] is None
    with pytest.raises(AgentError): owner.complete_decision(execution, outcome())
    assert raw_rows("agent_steps")[0]["state"] == "planned"


def test_expired_original_deadline_can_only_stop_not_restart_or_refresh_budget(agent_storage):
    from app.agents.contracts import AgentError
    clock = [1000.0]; owner = store(agent_storage, clock=lambda: clock[0])
    _, _, queued = create(agent_storage, owner=owner)
    run = owner.claim(queued.id, expected_row_version=queued.rowVersion)
    reserve(owner, identity(run)); clock[0] = 1181.0
    result = owner.stop(run.id, lease_token=run.leaseToken, state="needs_human", reason="deadline")
    assert result.deadlineAt == 1180.0 and result.modelAttemptsUsed == 1
    with pytest.raises(AgentError): owner.claim(run.id, expected_row_version=result.rowVersion)
    assert owner.read_status(run.id) == result


def test_old_owner_cannot_stop_a_task_after_actual_takeover(agent_storage):
    from app.agents.contracts import AgentError
    clock = [1000.0]; owner = store(agent_storage, clock=lambda: clock[0])
    _, _, queued = create(agent_storage, owner=owner)
    old = owner.claim(queued.id, expected_row_version=0); clock[0] += 31
    current = owner.claim(old.id, expected_row_version=old.rowVersion); before = snapshot()
    with pytest.raises(AgentError): owner.stop(old.id, lease_token=old.leaseToken, state="failed", reason="tool_failed")
    assert snapshot() == before and owner.read(old.id).leaseToken == current.leaseToken


def test_admin_cancel_requires_current_version_and_keeps_actual_budget(agent_storage):
    from app.agents.contracts import AgentError
    owner, _, run = running(agent_storage); reserve(owner, identity(run))
    current = owner.read(run.id); before = snapshot()
    with pytest.raises(AgentError): owner.cancel(run.id, expected_row_version=run.rowVersion)
    assert snapshot() == before
    stopped = owner.cancel(run.id, expected_row_version=current.rowVersion)
    assert stopped.state == "cancelled" and stopped.reason == "cancellation" and stopped.modelAttemptsUsed == 1
    assert raw_rows("agent_runs")[0]["lease_token"] is None
    before = snapshot()
    assert owner.cancel(run.id, expected_row_version=stopped.rowVersion) == stopped and snapshot() == before


def test_queued_cancel_does_not_start_deadline_or_consume_attempts(agent_storage):
    owner, _, run = create(agent_storage)
    stopped = owner.cancel(run.id, expected_row_version=0)
    assert stopped.state == "cancelled" and stopped.deadlineAt is None
    assert stopped.modelAttemptsUsed == 0 and stopped.toolAttemptsUsed == 0


def test_closing_allows_only_terminal_stop_not_decision_tool_or_completion(agent_storage):
    from app.agents.contracts import AgentError
    owner, _, run = running(agent_storage); execution = identity(run)
    reserve(owner, execution); agent_storage.closed = True
    before = snapshot()
    for operation in (lambda: reserve(owner, identity(run, 1)),
        lambda: owner.complete_decision(execution, outcome()),
        lambda: owner.plan_step(*step_inputs(run, seq=1))):
        with pytest.raises(AgentError): operation()
        assert snapshot() == before
    stopped = owner.stop(run.id, lease_token=run.leaseToken, state="needs_human", reason="shutting_down")
    assert stopped.state == "needs_human" and stopped.modelAttemptsUsed == 1


def test_terminal_stop_reason_is_immutable_and_atomic_with_audit(agent_storage, monkeypatch):
    from app import audit_store
    from app.agents.contracts import AgentError
    owner, _, run = running(agent_storage); before = snapshot()
    original = audit_store.insert_business_event
    def fail(*args, **kwargs): raise audit_store.AuditPersistenceError("PRIVATE synthetic")
    monkeypatch.setattr(audit_store, "insert_business_event", fail)
    with pytest.raises(AgentError): owner.stop(run.id, lease_token=run.leaseToken, state="failed", reason="tool_failed")
    assert snapshot() == before
    monkeypatch.setattr(audit_store, "insert_business_event", original)
    stopped = owner.stop(run.id, lease_token=run.leaseToken, state="failed", reason="tool_failed")
    rows = raw_rows("agent_steps")
    assert len(rows) == 1 and baselines.strict_json(rows[0]["action_json"])["action"] == "server_stop"
    assert rows[0]["state"] == "completed" and baselines.strict_json(rows[0]["result_json"])["reason"] == "tool_failed"
    before = snapshot()
    assert owner.stop(run.id, lease_token=run.leaseToken, state="failed", reason="tool_failed") == stopped
    with pytest.raises(AgentError): owner.stop(run.id, lease_token=run.leaseToken, state="needs_human", reason="deadline")
    assert snapshot() == before


@pytest.mark.parametrize("changes", [dict(state="running"), dict(state="awaiting_review"), dict(state="cancelled"),
    dict(reason="PRIVATE raw exception"), dict(reason="publish"), dict(lease_token=str(uuid4()))])
def test_worker_stop_cannot_assign_active_approval_or_arbitrary_reason(agent_storage, changes):
    from app.agents.contracts import AgentError
    owner, _, run = running(agent_storage); before = snapshot()
    args = dict(lease_token=run.leaseToken, state="needs_human", reason="tool_failed")
    with pytest.raises(AgentError): owner.stop(run.id, **{**args, **changes})
    assert snapshot() == before


def test_minimal_status_does_not_fabricate_valid_state_from_corrupt_run(agent_storage):
    from app import db
    from app.agents.contracts import AgentError
    owner, _, run = running(agent_storage)
    conn = db._connect()
    try:
        conn.execute("UPDATE agent_runs SET checkpoint_json=? WHERE id=?", ('{"PRIVATE":"synthetic corruption"}', run.id)); conn.commit()
    finally: conn.close()
    with pytest.raises(AgentError) as caught: owner.read_status(run.id)
    assert "PRIVATE" not in str(caught.value)


def test_cancelled_task_rejects_actual_late_tool_result_and_new_heartbeat(agent_storage):
    from app.agents.contracts import AgentError
    from app.agents.tool_contracts import trace_result
    from app.agents.contracts import parse_tool_action
    import json
    owner, _, run = running(agent_storage); execution = identity(run)
    owner.plan_step(execution, parse_tool_action(json.dumps(dict(action="tool", tool="get_turn_trace",
        arguments=dict(turnId=run.manifest.context.turnId)))))
    stopped = owner.cancel(run.id, expected_row_version=owner.read(run.id).rowVersion); before = snapshot()
    with pytest.raises(AgentError): owner.complete_tool(execution, trace_result(run.manifest.context))
    with pytest.raises(AgentError): owner.heartbeat(run.id, run.leaseToken)
    assert snapshot() == before and stopped.toolAttemptsUsed == 1


def test_minimal_status_cannot_include_model_feedback_fact_or_token_fields(agent_storage):
    from app.agents.contracts import AgentError, checked_model
    from app.agents.decision_contracts import AgentStatus
    owner, _, run = running(agent_storage); status = owner.read_status(run.id)
    for extra in ("manifest", "leaseToken", "rawOutput", "question", "reasoning", "facts"):
        with pytest.raises(AgentError): checked_model(AgentStatus, {**status.model_dump(mode="json"), extra: "PRIVATE"})
    assert status.state == "running" and status.modelAttemptsUsed == 0 and status.steps == ()
