"""Stored reports are bound program results, not model self-certified hashes."""
import json
from uuid import uuid4

import pytest

from app import baselines
from .test_agent_store import agent_storage, running, raw_rows, step_inputs
from .test_feedback_storage import snapshot, storage
from .test_repair_contracts import draft_body, report_body


def inputs(run, *, seq=0):
    from app.agents.contracts import checked_draft, parse_tool_action
    identity, _ = step_inputs(run, seq=seq)
    context = run.manifest.context
    draft = checked_draft(draft_body(soupId=context.soupId, puzzleVersion=context.observedPuzzleVersion,
        baseRuleVersion=context.baseRuleVersion, factIds=[context.factScope[0].id]))
    action = parse_tool_action(json.dumps(dict(action="tool", tool="run_regression", arguments=dict(draft=draft.model_dump(mode="json")))))
    return identity, draft, action


def report(run, identity, draft, **changes):
    from app.agents.contracts import RegressionReport, checked_model, draft_digest
    return checked_model(RegressionReport, report_body(reportId=identity.operationKey, runId=run.id,
        draftDigest=draft_digest(draft), contextDigest=run.manifest.contextDigest,
        puzzleVersion=draft.puzzleVersion, baseRuleVersion=draft.baseRuleVersion,
        suiteManifestDigest=run.manifest.suiteManifestDigest or "c" * 64, **changes))


def report_run(active, *, clock=None):
    from app.agents.store import AgentStore
    from .test_task_context import prepared, TOOLS
    owner = AgentStore(active, authorize_create=lambda context: True, **({} if clock is None else {"clock": clock}))
    item = prepared()
    run = owner.create(request_id=str(uuid4()), feedback_id=item.id, expected_feedback_version=item.rowVersion,
        allowed_tools=TOOLS, suite_manifest_digest="c" * 64)
    run = owner.claim(run.id, expected_row_version=0)
    return owner, item, run


def prepared_report(active, **changes):
    owner, item, run = report_run(active)
    identity, draft, action = inputs(run)
    owner.plan_step(identity, action)
    result = report(run, identity, draft, **changes)
    owner.complete_regression(identity, result)
    return owner, item, run, identity, draft, result


def save_inputs(run, draft, report_id, *, seq=1):
    from app.agents.contracts import parse_tool_action
    identity, _ = step_inputs(run, seq=seq)
    action = parse_tool_action(json.dumps(dict(action="tool", tool="save_candidate_rule",
        arguments=dict(draft=draft.model_dump(mode="json"), regressionReportId=report_id))))
    return identity, action


def test_completed_report_replays_exactly_but_changed_report_cannot_overwrite(agent_storage):
    from app.agents.contracts import AgentError
    owner, _, run, identity, draft, value = prepared_report(agent_storage)
    step = owner.complete_regression(identity, value)
    assert step.state == "completed" and json.loads(step.resultJson)["reportId"] == identity.operationKey
    assert len(raw_rows("agent_steps")) == 1
    before = snapshot()
    with pytest.raises(AgentError): owner.complete_regression(identity, value.model_copy(update={"elapsedSeconds": 0.2}))
    assert snapshot() == before


@pytest.mark.parametrize("field,value", [("runId", str(uuid4())), ("reportId", str(uuid4())),
    ("draftDigest", "e" * 64), ("contextDigest", "e" * 64), ("suiteManifestDigest", "e" * 64),
    ("puzzleVersion", "p1:" + "e" * 64), ("baseRuleVersion", "r1:" + "e" * 64)])
def test_report_commit_requires_exact_saved_action_and_run_proof(agent_storage, field, value):
    from app.agents.contracts import AgentError
    owner, _, run = report_run(agent_storage)
    identity, draft, action = inputs(run)
    owner.plan_step(identity, action)
    value = report(run, identity, draft).model_copy(update={field: value})
    before = snapshot()
    with pytest.raises(AgentError): owner.complete_regression(identity, value)
    assert snapshot() == before


def test_no_report_completion_without_actual_planned_regression_step(agent_storage):
    from app.agents.contracts import AgentError
    owner, _, run = report_run(agent_storage)
    identity, draft, _ = inputs(run)
    before = snapshot()
    with pytest.raises(AgentError): owner.complete_regression(identity, report(run, identity, draft))
    assert snapshot() == before


def test_candidate_save_is_pending_idempotent_and_does_not_publish_or_certify(agent_storage):
    owner, _, run, regression, draft, value = prepared_report(agent_storage)
    identity, action = save_inputs(run, draft, regression.operationKey)
    owner.plan_step(identity, action)
    first = owner.save_candidate(identity, draft, regression.operationKey)
    again = owner.save_candidate(identity, draft, regression.operationKey)
    assert first == again and first.status == "pending" and first.runId == run.id
    assert not hasattr(first, "answerSupported") and not hasattr(first, "reviewReceipt")
    assert len(raw_rows("rule_candidates")) == 1
    assert owner.read(run.id).state == "running"
    assert agent_storage.model.calls == []


def test_unknown_or_model_self_hashed_report_id_cannot_save_candidate(agent_storage):
    from app.agents.contracts import AgentError
    owner, _, run = running(agent_storage); _, draft, _ = inputs(run)
    report_id = str(uuid4()); identity, action = save_inputs(run, draft, report_id, seq=0)
    owner.plan_step(identity, action); before = snapshot()
    with pytest.raises(AgentError): owner.save_candidate(identity, draft, report_id)
    assert snapshot() == before and raw_rows("rule_candidates") == []


def test_incomplete_report_is_retained_but_cannot_save_passing_candidate(agent_storage):
    from app.agents.contracts import AgentError
    owner, _, run, regression, draft, _ = prepared_report(agent_storage, status="incomplete", truncated=True)
    identity, action = save_inputs(run, draft, regression.operationKey)
    owner.plan_step(identity, action); before = snapshot()
    with pytest.raises(AgentError): owner.save_candidate(identity, draft, regression.operationKey)
    assert snapshot() == before and raw_rows("rule_candidates") == []
    assert json.loads(raw_rows("agent_steps")[0]["result_json"])["status"] == "incomplete"


def test_live_permission_revocation_between_compute_and_commit_blocks_report(agent_storage):
    from app.agents.contracts import AgentError
    from app.feedback_contract import PrivacyReview
    from app.feedback_store import set_model_permission
    owner, item, run = report_run(agent_storage); identity, draft, action = inputs(run)
    owner.plan_step(identity, action); value = report(run, identity, draft)
    set_model_permission(item.id, item.rowVersion, review=PrivacyReview(safeForModel=False, reviewNote="Synthetic revoke"))
    before = snapshot()
    with pytest.raises(AgentError): owner.complete_regression(identity, value)
    assert snapshot() == before


def test_report_business_audit_failure_rolls_back_result_but_not_reserved_attempt(agent_storage, monkeypatch):
    from app import audit_store
    from app.agents.contracts import AgentError
    owner, _, run = report_run(agent_storage); identity, draft, action = inputs(run)
    owner.plan_step(identity, action); value = report(run, identity, draft); before = snapshot()
    def fail(*args, **kwargs): raise audit_store.AuditPersistenceError("Synthetic failure")
    monkeypatch.setattr(audit_store, "insert_business_event", fail)
    with pytest.raises(AgentError): owner.complete_regression(identity, value)
    assert snapshot() == before and owner.read(run.id).checkpoint.toolAttemptsUsed == 1


def saved(active):
    owner, item, run, regression, draft, value = prepared_report(active)
    identity, action = save_inputs(run, draft, regression.operationKey)
    owner.plan_step(identity, action)
    candidate = owner.save_candidate(identity, draft, regression.operationKey)
    return owner, item, run, candidate


def finish_input(run, candidate_id=None, *, seq=2, reason=None):
    from app.agents.contracts import parse_agent_action
    identity, _ = step_inputs(run, seq=seq)
    action = {"action": "finish", "candidateId": candidate_id} if candidate_id is not None else {"action": "finish", "needsHumanReason": reason}
    return identity, parse_agent_action(json.dumps(action))


def test_finish_own_candidate_is_idempotent_awaiting_review_not_approval(agent_storage):
    owner, _, run, candidate = saved(agent_storage)
    identity, action = finish_input(run, candidate.id)
    finished = owner.finish(identity, action)
    before = snapshot()
    assert owner.finish(identity, action) == finished and snapshot() == before
    assert finished.state == "awaiting_review" and finished.leaseToken is None and finished.leaseExpiresAt is None
    assert raw_rows("rule_candidates")[0]["status"] == "pending"
    assert owner.read(run.id).checkpoint.toolAttemptsUsed == 2


def test_finish_cannot_borrow_foreign_candidate_or_invent_missing_candidate(agent_storage):
    from app.agents.contracts import AgentError
    _, _, _, candidate = saved(agent_storage)
    owner, _, other = report_run(agent_storage)
    for candidate_id in (candidate.id, str(uuid4())):
        identity, action = finish_input(other, candidate_id, seq=0)
        before = snapshot()
        with pytest.raises(AgentError): owner.finish(identity, action)
        assert snapshot() == before and owner.read(other.id).state == "running"


def test_finish_human_reason_is_terminal_and_late_tool_cannot_write(agent_storage):
    from app.agents.contracts import AgentError
    owner, _, run = report_run(agent_storage)
    tool_id, draft, action = inputs(run)
    owner.plan_step(tool_id, action)
    identity, finish = finish_input(run, seq=1, reason="Synthetic evidence insufficient")
    finished = owner.finish(identity, finish)
    assert finished.state == "needs_human" and finished.leaseToken is None
    before = snapshot()
    with pytest.raises(AgentError): owner.complete_regression(tool_id, report(run, tool_id, draft))
    assert snapshot() == before


def test_finish_audit_failure_rolls_back_step_and_run_state(agent_storage, monkeypatch):
    from app import audit_store
    from app.agents.contracts import AgentError
    owner, _, run, candidate = saved(agent_storage)
    identity, action = finish_input(run, candidate.id); before = snapshot()
    def fail(*args, **kwargs): raise audit_store.AuditPersistenceError("Synthetic failure")
    monkeypatch.setattr(audit_store, "insert_business_event", fail)
    with pytest.raises(AgentError): owner.finish(identity, action)
    assert snapshot() == before and owner.read(run.id).state == "running"


@pytest.mark.parametrize("state", ["failed", "cancelled", "needs_human"])
def test_saved_candidate_in_terminal_bad_run_cannot_finish_as_reviewable(agent_storage, state):
    from app import db
    from app.agents.contracts import AgentError
    owner, _, run, candidate = saved(agent_storage)
    conn = db._connect()
    try:
        # Explicit owned DB fixture represents future TS14 stop transition.
        conn.execute("UPDATE agent_runs SET state=?,lease_token=NULL,lease_expires_at=NULL,row_version=row_version+1 WHERE id=?", (state, run.id))
        conn.commit()
    finally: conn.close()
    identity, action = finish_input(run, candidate.id); before = snapshot()
    with pytest.raises(AgentError): owner.finish(identity, action)
    assert snapshot() == before and raw_rows("rule_candidates")[0]["status"] == "pending"


def test_finish_replay_must_keep_same_execution_identity_and_action(agent_storage):
    from app.agents.contracts import AgentError
    owner, _, run, candidate = saved(agent_storage)
    identity, action = finish_input(run, candidate.id)
    owner.finish(identity, action); before = snapshot()
    with pytest.raises(AgentError): owner.finish(identity.model_copy(update={"leaseToken": str(uuid4())}), action)
    _, changed = finish_input(run, reason="Different synthetic result")
    with pytest.raises(AgentError): owner.finish(identity, changed)
    assert snapshot() == before


def test_current_heartbeat_can_advance_row_before_report_completion(agent_storage):
    owner, _, run = report_run(agent_storage); identity, draft, action = inputs(run)
    owner.plan_step(identity, action); value = report(run, identity, draft)
    beat = owner.heartbeat(run.id, run.leaseToken)
    assert owner.complete_regression(identity, value).state == "completed"
    assert owner.read(run.id).rowVersion == beat.rowVersion + 1


def test_candidate_audit_failure_rolls_back_candidate_and_save_result_not_budget(agent_storage, monkeypatch):
    from app import audit_store
    from app.agents.contracts import AgentError
    owner, _, run, regression, draft, _ = prepared_report(agent_storage)
    identity, action = save_inputs(run, draft, regression.operationKey)
    owner.plan_step(identity, action); before = snapshot()
    def fail(*args, **kwargs): raise audit_store.AuditPersistenceError("Synthetic failure")
    monkeypatch.setattr(audit_store, "insert_business_event", fail)
    with pytest.raises(AgentError): owner.save_candidate(identity, draft, regression.operationKey)
    assert snapshot() == before and raw_rows("rule_candidates") == []
    assert owner.read(run.id).checkpoint.toolAttemptsUsed == 2


def test_another_run_completed_report_cannot_certify_this_candidate(agent_storage):
    from app.agents.contracts import AgentError
    _, _, _, foreign, _, _ = prepared_report(agent_storage)
    owner, _, run = report_run(agent_storage); _, draft, _ = inputs(run)
    identity, action = save_inputs(run, draft, foreign.operationKey, seq=0)
    owner.plan_step(identity, action); before = snapshot()
    with pytest.raises(AgentError): owner.save_candidate(identity, draft, foreign.operationKey)
    assert snapshot() == before and raw_rows("rule_candidates") == []


def test_same_run_second_report_cannot_replace_immutable_candidate_report(agent_storage):
    from app.agents.contracts import AgentError
    owner, _, run, candidate = saved(agent_storage)
    regression, draft, action = inputs(run, seq=2)
    owner.plan_step(regression, action)
    owner.complete_regression(regression, report(run, regression, draft))
    identity, action = save_inputs(run, draft, regression.operationKey, seq=3)
    owner.plan_step(identity, action); before = snapshot()
    with pytest.raises(AgentError): owner.save_candidate(identity, draft, regression.operationKey)
    assert snapshot() == before and len(raw_rows("rule_candidates")) == 1
    assert raw_rows("rule_candidates")[0]["id"] == candidate.id


def test_known_failed_report_keeps_failure_and_is_not_candidate_evidence(agent_storage):
    from app.agents.contracts import AgentError
    owner, _, run = report_run(agent_storage); regression, draft, action = inputs(run)
    owner.plan_step(regression, action)
    value = report(run, regression, draft, status="failed", passedCaseCount=0,
        caseResults=[dict(caseId=str(uuid4()), suite="fixed_safety", passed=False, code="counterexample")])
    owner.complete_regression(regression, value)
    identity, action = save_inputs(run, draft, regression.operationKey)
    owner.plan_step(identity, action); before = snapshot()
    with pytest.raises(AgentError): owner.save_candidate(identity, draft, regression.operationKey)
    assert snapshot() == before and json.loads(raw_rows("agent_steps")[0]["result_json"])["passedCaseCount"] == 0


def test_new_lease_owner_blocks_old_computed_report_and_finish(agent_storage):
    from app.agents.contracts import AgentError
    now = [100.0]
    owner, _, run = report_run(agent_storage, clock=lambda: now[0])
    identity, draft, action = inputs(run)
    owner.plan_step(identity, action); value = report(run, identity, draft)
    current = owner.read(run.id)
    now[0] = 131.0
    replacement = owner.claim(run.id, expected_row_version=current.rowVersion)
    assert replacement.leaseToken != run.leaseToken
    before = snapshot()
    with pytest.raises(AgentError): owner.complete_regression(identity, value)
    finish_identity, finish = finish_input(run, seq=1, reason="Synthetic old owner")
    with pytest.raises(AgentError): owner.finish(finish_identity, finish)
    assert snapshot() == before


def test_total_deadline_blocks_report_commit_without_erasing_reserved_intent(agent_storage):
    from app.agents.contracts import AgentError
    now = [100.0]
    owner, _, run = report_run(agent_storage, clock=lambda: now[0])
    identity, draft, action = inputs(run)
    owner.plan_step(identity, action); value = report(run, identity, draft)
    now[0] = 280.0; before = snapshot()
    with pytest.raises(AgentError): owner.complete_regression(identity, value)
    assert snapshot() == before and raw_rows("agent_steps")[0]["state"] == "planned"


def test_candidate_save_after_permission_withdrawal_cannot_replay_green_report(agent_storage):
    from app.agents.contracts import AgentError
    from app.feedback_contract import PrivacyReview
    from app.feedback_store import set_model_permission
    owner, item, run, regression, draft, _ = prepared_report(agent_storage)
    identity, action = save_inputs(run, draft, regression.operationKey)
    owner.plan_step(identity, action)
    set_model_permission(item.id, item.rowVersion, review=PrivacyReview(safeForModel=False, reviewNote="Synthetic revoke"))
    before = snapshot()
    with pytest.raises(AgentError): owner.save_candidate(identity, draft, regression.operationKey)
    assert snapshot() == before and raw_rows("rule_candidates") == []


def test_candidate_and_finish_do_not_change_active_pointer_or_release_bytes(agent_storage):
    from app import db
    def baseline():
        conn = db._connect()
        try:
            return tuple(tuple(row) for row in conn.execute("SELECT * FROM rule_releases ORDER BY id")), baselines.active_manifest(conn)
        finally: conn.close()
    before = baseline()
    owner, _, run, candidate = saved(agent_storage)
    identity, action = finish_input(run, candidate.id)
    owner.finish(identity, action)
    assert baseline() == before
