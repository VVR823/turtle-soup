"""Native owned SQLite run creation/lease tests; all approvals are synthetic."""
import json
from concurrent.futures import ThreadPoolExecutor
from dataclasses import replace
from uuid import uuid4

import pytest

from app import db
from app.runtime import Runtime, runtime_context
from .test_feedback_storage import storage, snapshot
from .test_task_context import prepared, TOOLS


@pytest.fixture
def agent_storage(storage):
    from app.migrations import migrate
    conn = db._connect()
    try:
        migrate(conn, storage.soups, target_version=3)
    finally:
        conn.close()
    return storage


def store(active, **changes):
    from app.agents.store import AgentStore
    return AgentStore(active, authorize_create=lambda context: True, **changes)


def create(active, *, owner=None, item=None, request_id=None):
    owner = owner or store(active)
    item = item or prepared()
    run = owner.create(request_id=request_id or str(uuid4()), feedback_id=item.id,
        expected_feedback_version=item.rowVersion, allowed_tools=TOOLS, suite_manifest_digest=None)
    return owner, item, run


def raw_rows(table):
    assert table in {"agent_runs", "agent_steps", "rule_candidates", "audit_events"}
    conn = db._connect()
    try:
        return [dict(row) for row in conn.execute("SELECT * FROM " + table + " ORDER BY rowid")]
    finally:
        conn.close()


def test_constructor_requires_explicit_runtime_and_authorizer_without_db_io(agent_storage, monkeypatch):
    from app.agents.store import AgentStore
    before = snapshot()
    def unavailable(*args, **kwargs):
        raise AssertionError("Constructor touched runtime/configuration/database")
    with monkeypatch.context() as patch:
        patch.setattr(db, "_connect", unavailable)
        patch.setattr(db, "initialize", unavailable)
        owner = AgentStore(agent_storage, authorize_create=lambda context: True)
        with pytest.raises(TypeError): AgentStore(authorize_create=lambda context: True)
        with pytest.raises(TypeError): AgentStore(agent_storage)
    assert owner.runtime is agent_storage and snapshot() == before


def test_registered_phase_two_is_refused_without_hidden_migration(storage):
    from app.agents.contracts import AgentError
    item = prepared(); before = snapshot()
    with pytest.raises(AgentError): create(storage, item=item)
    assert snapshot() == before and "CREATE TABLE agent_runs" not in before


def test_create_is_persisted_idempotent_and_contains_only_checked_sanitized_context(agent_storage):
    owner, item, first = create(agent_storage)
    again = owner.create(request_id=first.requestId, feedback_id=item.id,
        expected_feedback_version=item.rowVersion, allowed_tools=TOOLS, suite_manifest_digest=None)
    assert first == again and first.state == "queued" and first.rowVersion == 0
    assert first.checkpoint.firstStartedAt is None and first.leaseToken is None
    assert first.manifest.context.feedbackId == item.id and first.manifest.trafficClass == "test"
    assert len(raw_rows("agent_runs")) == 1 and raw_rows("agent_steps") == []
    raw = raw_rows("agent_runs")[0]["manifest_json"]
    assert "PRIVATE synthetic claim" not in raw and agent_storage.model.calls == []
    events = [r for r in raw_rows("audit_events") if r["event_type"] == "agent_run"]
    assert len(events) == 1 and events[0]["run_id"] == first.id
    assert "是谁" not in events[0]["details_json"]


def test_request_id_cannot_be_reused_for_changed_source_or_tool_scope(agent_storage):
    from app.agents.contracts import AgentError
    owner, item, first = create(agent_storage); before = snapshot()
    with pytest.raises(AgentError): owner.create(request_id=first.requestId, feedback_id=item.id,
        expected_feedback_version=item.rowVersion, allowed_tools=("retrieve_truth",), suite_manifest_digest=None)
    assert snapshot() == before


@pytest.mark.parametrize("approval", [False, None, 1, "synthetic-private-not-a-boolean"])
def test_explicit_authorizer_requires_real_true_before_any_run_insert(agent_storage, approval):
    from app.agents.contracts import AgentError
    from app.agents.store import AgentStore
    item = prepared(); before = snapshot()
    owner = AgentStore(agent_storage, authorize_create=lambda context: approval)
    with pytest.raises(AgentError): create(agent_storage, owner=owner, item=item)
    assert snapshot() == before


def test_pending_queue_is_persistently_bounded_ten_across_store_instances(agent_storage):
    from app.agents.contracts import AgentError
    item = prepared()
    for _ in range(10): create(agent_storage, item=item)
    before = snapshot()
    with pytest.raises(AgentError): create(agent_storage, item=item)
    assert len(raw_rows("agent_runs")) == 10 and snapshot() == before


def test_create_business_audit_failure_rolls_back_run(agent_storage, monkeypatch):
    from app import audit_store
    from app.agents.contracts import AgentError
    item = prepared(); before = snapshot()
    def fail(*args, **kwargs): raise audit_store.AuditPersistenceError("Synthetic failure")
    monkeypatch.setattr(audit_store, "insert_business_event", fail)
    with pytest.raises(AgentError): create(agent_storage, item=item)
    assert snapshot() == before


def test_read_in_foreign_thread_binds_only_explicit_runtime(agent_storage, tmp_path):
    owner, _, first = create(agent_storage)
    foreign = Runtime(replace(agent_storage.settings, DATA_DIR=tmp_path / "foreign"), model=agent_storage.model)
    def run():
        with runtime_context(foreign): return owner.read(first.id)
    with ThreadPoolExecutor(max_workers=1) as pool:
        assert pool.submit(run).result(timeout=5) == first
    assert not foreign.settings.DATA_DIR.exists()


def test_permission_revocation_blocks_read_and_duplicate_create(agent_storage):
    from app.agents.contracts import AgentError
    from app.feedback_contract import PrivacyReview
    from app.feedback_store import set_model_permission
    owner, item, first = create(agent_storage)
    set_model_permission(item.id, item.rowVersion, review=PrivacyReview(safeForModel=False, reviewNote="Synthetic revoke"))
    before = snapshot()
    with pytest.raises(AgentError): owner.read(first.id)
    with pytest.raises(AgentError): owner.create(request_id=first.requestId, feedback_id=item.id,
        expected_feedback_version=item.rowVersion, allowed_tools=TOOLS, suite_manifest_digest=None)
    assert snapshot() == before


def test_claim_and_reclaim_keep_original_deadline_and_fence_old_token(agent_storage):
    from app.agents.contracts import AgentError
    now = [100.0]
    owner, _, first = create(agent_storage, owner=store(agent_storage, clock=lambda: now[0]))
    started = owner.claim(first.id, expected_row_version=0)
    assert started.state == "running" and started.checkpoint.firstStartedAt == 100.0
    assert started.checkpoint.deadlineAt == 280.0 and started.leaseExpiresAt == 130.0
    before = snapshot()
    with pytest.raises(AgentError): owner.claim(first.id, expected_row_version=0)
    assert snapshot() == before
    now[0] = 131.0
    resumed = owner.claim(first.id, expected_row_version=started.rowVersion)
    assert resumed.leaseToken != started.leaseToken and resumed.checkpoint == started.checkpoint
    before = snapshot()
    with pytest.raises(AgentError): owner.heartbeat(first.id, started.leaseToken)
    assert snapshot() == before
    now[0] = 281.0
    with pytest.raises(AgentError): owner.claim(first.id, expected_row_version=resumed.rowVersion)
    assert snapshot() == before


def test_heartbeat_uses_current_row_version_and_same_owner_does_not_refresh_budget(agent_storage):
    now = [100.0]
    owner, _, first = create(agent_storage, owner=store(agent_storage, clock=lambda: now[0]))
    started = owner.claim(first.id, expected_row_version=0)
    now[0] = 110.0
    beat = owner.heartbeat(first.id, started.leaseToken)
    assert beat.rowVersion == started.rowVersion + 1 and beat.leaseExpiresAt == 140.0
    assert beat.checkpoint == started.checkpoint


def test_claim_cannot_rebase_after_actual_rule_pointer_changes(agent_storage):
    from app import baselines
    from app.agents.contracts import AgentError
    owner, _, first = create(agent_storage)
    conn = db._connect()
    try:
        old = baselines.active_manifest(conn)
        soup = baselines.session_soup(conn, old["puzzleVersions"]["synthetic"])
        conn.execute("DELETE FROM runtime_meta WHERE key='active_baseline'")
        baselines.store_baseline(conn, [soup.model_copy(update={"bottom": "Changed synthetic truth"})])
        conn.commit()
    finally:
        conn.close()
    before = snapshot()
    with pytest.raises(AgentError): owner.claim(first.id, expected_row_version=0)
    assert snapshot() == before


def test_claim_audit_failure_rolls_back_deadline_lease_and_version(agent_storage, monkeypatch):
    from app import audit_store
    from app.agents.contracts import AgentError
    owner, _, first = create(agent_storage); before = snapshot()
    def fail(*args, **kwargs): raise audit_store.AuditPersistenceError("Synthetic failure")
    monkeypatch.setattr(audit_store, "insert_business_event", fail)
    with pytest.raises(AgentError): owner.claim(first.id, expected_row_version=0)
    assert snapshot() == before


@pytest.mark.parametrize("bad", [True, -1.0, float("nan"), float("inf")], ids=["bool", "negative", "nan", "infinity"])
def test_bad_clock_cannot_create_run_or_fake_started_deadline(agent_storage, bad):
    from app.agents.contracts import AgentError
    owner = store(agent_storage, clock=lambda: bad)
    item = prepared(); before = snapshot()
    with pytest.raises(AgentError): create(agent_storage, owner=owner, item=item)
    assert snapshot() == before


def test_current_permission_revocation_blocks_running_heartbeat(agent_storage):
    from app.agents.contracts import AgentError
    from app.feedback_contract import PrivacyReview
    from app.feedback_store import set_model_permission
    owner, item, first = create(agent_storage)
    started = owner.claim(first.id, expected_row_version=0)
    set_model_permission(item.id, item.rowVersion, review=PrivacyReview(safeForModel=False, reviewNote="Synthetic revoke"))
    before = snapshot()
    with pytest.raises(AgentError): owner.heartbeat(first.id, started.leaseToken)
    assert snapshot() == before


def test_expired_heartbeat_cannot_revive_old_lease(agent_storage):
    from app.agents.contracts import AgentError
    now = [100.0]
    owner, _, first = create(agent_storage, owner=store(agent_storage, clock=lambda: now[0]))
    started = owner.claim(first.id, expected_row_version=0)
    now[0] = 130.0; before = snapshot()
    with pytest.raises(AgentError): owner.heartbeat(first.id, started.leaseToken)
    assert snapshot() == before


def running(active):
    owner, item, first = create(active)
    return owner, item, owner.claim(first.id, expected_row_version=0)


def step_inputs(run, *, seq=0, operation_key=None):
    from app.agents.contracts import ExecutionIdentity, parse_tool_action
    identity = ExecutionIdentity(runId=run.id, operationKey=operation_key or str(uuid4()), leaseToken=run.leaseToken, seq=seq)
    action = parse_tool_action(json.dumps(dict(action="tool", tool="retrieve_truth", arguments=dict(
        soupId=run.manifest.context.soupId, puzzleVersion=run.manifest.context.observedPuzzleVersion, query="Synthetic fact"))))
    return identity, action


def test_planned_step_reserves_once_and_replay_is_not_a_completed_result(agent_storage):
    owner, _, run = running(agent_storage); identity, action = step_inputs(run)
    first = owner.plan_step(identity, action)
    replay = owner.plan_step(identity, action)
    assert first == replay and first.state == "planned" and first.resultJson is None
    assert owner.read(run.id).checkpoint.toolAttemptsUsed == 1
    assert len(raw_rows("agent_steps")) == 1 and agent_storage.model.calls == []
    events = [r for r in raw_rows("audit_events") if r["event_type"] == "agent_step"]
    assert len(events) == 1 and "Synthetic fact" not in events[0]["details_json"]


def test_step_replay_rechecks_permission_and_does_not_refund_attempt(agent_storage):
    from app.agents.contracts import AgentError
    from app.feedback_contract import PrivacyReview
    from app.feedback_store import set_model_permission
    owner, item, run = running(agent_storage); identity, action = step_inputs(run)
    owner.plan_step(identity, action)
    set_model_permission(item.id, item.rowVersion, review=PrivacyReview(safeForModel=False, reviewNote="Synthetic revoke"))
    before = snapshot()
    with pytest.raises(AgentError): owner.plan_step(identity, action)
    assert snapshot() == before


def test_same_step_key_cannot_change_action_or_borrow_another_run(agent_storage):
    from app.agents.contracts import AgentError, parse_tool_action
    owner, _, run = running(agent_storage); identity, action = step_inputs(run)
    owner.plan_step(identity, action)
    changed = action.model_dump(mode="json"); changed["arguments"]["query"] = "Changed synthetic input"
    before = snapshot()
    with pytest.raises(AgentError): owner.plan_step(identity, parse_tool_action(json.dumps(changed)))
    assert snapshot() == before
    _, _, other = create(agent_storage, owner=owner)
    other = owner.claim(other.id, expected_row_version=0)
    foreign_identity, foreign_action = step_inputs(other, operation_key=identity.operationKey)
    before = snapshot()
    with pytest.raises(AgentError): owner.plan_step(foreign_identity, foreign_action)
    assert snapshot() == before


def test_same_lease_heartbeat_can_advance_row_version_before_step_commit(agent_storage):
    owner, _, run = running(agent_storage); identity, action = step_inputs(run)
    beat = owner.heartbeat(run.id, run.leaseToken)
    step = owner.plan_step(identity, action)
    assert step.state == "planned" and owner.read(run.id).rowVersion == beat.rowVersion + 1


def test_eight_tool_intents_exhaust_persisted_budget_without_reset_or_ninth_insert(agent_storage):
    from app.agents.contracts import AgentError
    owner, _, run = running(agent_storage)
    for index in range(8):
        identity, action = step_inputs(run, seq=index)
        owner.plan_step(identity, action)
    assert owner.read(run.id).checkpoint.toolAttemptsUsed == 8
    identity, action = step_inputs(run, seq=8); before = snapshot()
    with pytest.raises(AgentError): owner.plan_step(identity, action)
    assert snapshot() == before and len(raw_rows("agent_steps")) == 8


def test_step_audit_failure_rolls_back_intent_counter_and_row_version(agent_storage, monkeypatch):
    from app import audit_store
    from app.agents.contracts import AgentError
    owner, _, run = running(agent_storage); identity, action = step_inputs(run); before = snapshot()
    def fail(*args, **kwargs): raise audit_store.AuditPersistenceError("Synthetic failure")
    monkeypatch.setattr(audit_store, "insert_business_event", fail)
    with pytest.raises(AgentError): owner.plan_step(identity, action)
    assert snapshot() == before


@pytest.mark.parametrize("changes", [{"soupId": "foreign"}, {"puzzleVersion": "p1:" + "e" * 64}])
def test_foreign_fact_scope_cannot_reserve_or_consume_step_budget(agent_storage, changes):
    from app.agents.contracts import AgentError, parse_tool_action
    owner, _, run = running(agent_storage); identity, action = step_inputs(run)
    body = action.model_dump(mode="json"); body["arguments"].update(changes)
    before = snapshot()
    with pytest.raises(AgentError): owner.plan_step(identity, parse_tool_action(json.dumps(body)))
    assert snapshot() == before


def test_concurrent_same_intent_reserves_one_attempt_and_one_audit(agent_storage):
    owner, _, run = running(agent_storage); identity, action = step_inputs(run)
    with ThreadPoolExecutor(max_workers=4) as pool:
        values = list(pool.map(lambda _: owner.plan_step(identity, action), range(4)))
    assert all(value == values[0] for value in values)
    assert owner.read(run.id).checkpoint.toolAttemptsUsed == 1 and len(raw_rows("agent_steps")) == 1
    assert len([r for r in raw_rows("audit_events") if r["event_type"] == "agent_step"]) == 1


def test_failed_tool_result_is_immutable_replay_and_does_not_refund_attempt(agent_storage):
    from app.agents.contracts import AgentError
    owner, _, run = running(agent_storage); identity, action = step_inputs(run)
    owner.plan_step(identity, action)
    first = owner.fail_step(identity, "agent_tool_failed")
    assert first.state == "failed" and json.loads(first.resultJson) == {"schemaVersion": 1, "code": "agent_tool_failed"}
    before = snapshot()
    assert owner.fail_step(identity, "agent_tool_failed") == first and snapshot() == before
    with pytest.raises(AgentError): owner.fail_step(identity, "agent_deadline_exhausted")
    assert snapshot() == before and owner.read(run.id).checkpoint.toolAttemptsUsed == 1


def test_tool_failure_never_stores_arbitrary_exception_text(agent_storage):
    from app.agents.contracts import AgentError
    owner, _, run = running(agent_storage); identity, action = step_inputs(run)
    owner.plan_step(identity, action); before = snapshot()
    with pytest.raises(AgentError): owner.fail_step(identity, "synthetic-private-path-or-exception")
    assert snapshot() == before


def test_failure_audit_error_rolls_back_result_but_retains_intent(agent_storage, monkeypatch):
    from app import audit_store
    from app.agents.contracts import AgentError
    owner, _, run = running(agent_storage); identity, action = step_inputs(run)
    owner.plan_step(identity, action); before = snapshot()
    def fail(*args, **kwargs): raise audit_store.AuditPersistenceError("Synthetic failure")
    monkeypatch.setattr(audit_store, "insert_business_event", fail)
    with pytest.raises(AgentError): owner.fail_step(identity, "agent_tool_failed")
    assert snapshot() == before


def test_revocation_is_controlled_context_refusal_not_transient_server_failure(agent_storage):
    from app.agents.contracts import AgentError
    from app.feedback_contract import PrivacyReview
    from app.feedback_store import set_model_permission
    owner, item, run = create(agent_storage)
    set_model_permission(item.id, item.rowVersion, review=PrivacyReview(safeForModel=False, reviewNote="Synthetic revoke"))
    before = snapshot()
    with pytest.raises(AgentError) as caught: owner.read(run.id)
    assert caught.value.code == "agent_context_stale" and caught.value.status == 409
    assert snapshot() == before


def test_internal_failure_record_refuses_boolean_schema_like_other_versioned_contracts():
    from app.agents.contracts import AgentError, checked_model
    from app.agents.store import ToolFailure
    with pytest.raises(AgentError): checked_model(ToolFailure, {"schemaVersion": True, "code": "agent_tool_failed"})
