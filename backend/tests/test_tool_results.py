"""Three read/proof tool successes have a closed output schema and stored scope."""
import json
from uuid import uuid4

import pytest

from app import baselines
from .test_agent_store import agent_storage, running, raw_rows, step_inputs
from .test_feedback_storage import snapshot, storage


def trace_body(run, **changes):
    context = run.manifest.context
    body = dict(schemaVersion=1, tool="get_turn_trace", turnId=context.turnId, soupId=context.soupId,
        puzzleVersion=context.observedPuzzleVersion, observedRuleVersion=context.observedRuleVersion,
        baseRuleVersion=context.baseRuleVersion, sanitizedInput=context.sanitizedInput.model_dump(mode="json"), claimsOnly=True,
        programDiagnostic=context.programDiagnostic.model_dump(mode="json"))
    return {**body, **changes}


def planned_trace(active):
    from app.agents.contracts import parse_tool_action
    owner, _, run = running(active); identity, _ = step_inputs(run)
    action = parse_tool_action(json.dumps(dict(action="tool", tool="get_turn_trace", arguments={"turnId": run.manifest.context.turnId})))
    owner.plan_step(identity, action)
    return owner, run, identity


def test_trace_success_is_typed_claim_not_original_trace_or_gold(agent_storage):
    from app.agents.tool_contracts import checked_tool_success
    owner, run, identity = planned_trace(agent_storage)
    value = checked_tool_success(trace_body(run))
    step = owner.complete_tool(identity, value)
    assert step.state == "completed" and json.loads(step.resultJson)["claimsOnly"] is True
    assert "PRIVATE synthetic claim" not in step.resultJson
    before = snapshot()
    assert owner.complete_tool(identity, value) == step and snapshot() == before


@pytest.mark.parametrize("changes", [{"schemaVersion": True}, {"claimsOnly": 1}, {"claimsOnly": False},
    {"rawTrace": "synthetic-private"}, {"reasoning": "synthetic-private"}, {"gold": "是"}])
def test_trace_output_cannot_hide_original_text_or_claim_human_truth(agent_storage, changes):
    from app.agents.contracts import AgentError
    from app.agents.tool_contracts import checked_tool_success
    _, _, run = running(agent_storage)
    with pytest.raises(AgentError): checked_tool_success(trace_body(run, **changes))


@pytest.mark.parametrize("changes", [{"turnId": str(uuid4())}, {"soupId": "foreign"},
    {"puzzleVersion": "p1:" + "e" * 64}, {"baseRuleVersion": "r1:" + "e" * 64}])
def test_stored_trace_output_cannot_cross_frozen_turn_or_source(agent_storage, changes):
    from app.agents.contracts import AgentError
    from app.agents.tool_contracts import checked_tool_success
    owner, run, identity = planned_trace(agent_storage); before = snapshot()
    value = checked_tool_success(trace_body(run, **changes))
    with pytest.raises(AgentError): owner.complete_tool(identity, value)
    assert snapshot() == before


def test_truth_success_is_bound_actual_ranked_excerpts_not_invented_fact_payload(agent_storage):
    from app.agents.contracts import AgentError, parse_tool_action
    from app.agents.tool_contracts import checked_tool_success
    owner, _, run = running(agent_storage); identity, action = step_inputs(run)
    body = action.model_dump(mode="json"); body["arguments"]["query"] = "Truth"
    owner.plan_step(identity, parse_tool_action(json.dumps(body)))
    fact = next(f for f in run.manifest.context.factScope if f.sourcePath == "bottom")
    checkpoint = next(f for f in run.manifest.context.factScope if f.sourcePath == "checkpoints[0]")
    # Literal independent ranking control: "Truth" matches bottom four
    # bigrams, then JSON true in the checkpoint matches tr/ru. A short query
    # must not be assumed to select only the first complete source record.
    assert len(checkpoint.payload) < 256
    body = dict(schemaVersion=1, tool="retrieve_truth", soupId=fact.soupId, puzzleVersion=fact.puzzleVersion,
        facts=[dict(id=fact.id, sourcePath="bottom", category="truth", excerpt='{"text":"Truth"}', truncated=False),
            dict(id=checkpoint.id, sourcePath="checkpoints[0]", category="checkpoint", excerpt=checkpoint.payload, truncated=False)])
    value = checked_tool_success(body)
    assert owner.complete_tool(identity, value).state == "completed"
    altered = {**body, "facts": [{**body["facts"][0], "excerpt": "Invented synthetic truth"}, body["facts"][1]]}
    before = snapshot()
    with pytest.raises(AgentError): owner.complete_tool(identity, checked_tool_success(altered))
    assert snapshot() == before


def test_conflict_success_must_be_recomputed_from_actual_saved_draft(agent_storage):
    from app import db
    from app.agents.contracts import AgentError, parse_tool_action
    from app.agents.tool_contracts import checked_tool_success
    from app.agents.validation import validate_candidate
    from app.rule_contract import read_rule_snapshot
    from .test_candidate_reports import inputs
    owner, _, run = running(agent_storage); identity, draft, _ = inputs(run)
    action = parse_tool_action(json.dumps(dict(action="tool", tool="find_rule_conflicts", arguments=dict(
        baseRuleVersion=draft.baseRuleVersion, draft=draft.model_dump(mode="json")))))
    owner.plan_step(identity, action)
    conn = db._connect()
    try:
        soup = baselines.session_soup(conn, draft.puzzleVersion)
        snapshot_rule = read_rule_snapshot(conn, draft.puzzleVersion, draft.baseRuleVersion)
    finally: conn.close()
    result = validate_candidate(draft, context=run.manifest.context, soup=soup, rule_snapshot=snapshot_rule)
    body = dict(schemaVersion=1, tool="find_rule_conflicts", conflict=result.model_dump(mode="json"))
    assert owner.complete_tool(identity, checked_tool_success(body)).state == "completed"
    body["conflict"]["draftDigest"] = "e" * 64
    before = snapshot()
    with pytest.raises(AgentError): owner.complete_tool(identity, checked_tool_success(body))
    assert snapshot() == before


def test_read_tool_completion_audit_failure_rolls_back_result_not_reserved_attempt(agent_storage, monkeypatch):
    from app import audit_store
    from app.agents.contracts import AgentError
    from app.agents.tool_contracts import checked_tool_success
    owner, run, identity = planned_trace(agent_storage); before = snapshot()
    def fail(*args, **kwargs): raise audit_store.AuditPersistenceError("Synthetic failure")
    monkeypatch.setattr(audit_store, "insert_business_event", fail)
    with pytest.raises(AgentError): owner.complete_tool(identity, checked_tool_success(trace_body(run)))
    assert snapshot() == before and raw_rows("agent_steps")[0]["state"] == "planned"


def test_copied_output_is_revalidated_without_serializer_warning_or_private_text(agent_storage):
    import warnings
    from app.agents.contracts import AgentError
    from app.agents.tool_contracts import checked_tool_success
    _, _, run = running(agent_storage)
    value = checked_tool_success(trace_body(run)).model_copy(update={"sanitizedInput": {"synthetic-private": "secret"}})
    with warnings.catch_warnings(record=True) as caught:
        warnings.simplefilter("always")
        with pytest.raises(AgentError) as error: checked_tool_success(value)
    assert not caught and "synthetic-private" not in str(error.value)


def test_result_json_duplicate_keys_are_not_coerced_into_a_success(agent_storage):
    from app.agents.contracts import AgentError
    from app.agents.tool_contracts import checked_tool_success
    _, _, run = running(agent_storage)
    raw = json.dumps(trace_body(run))[:-1] + ',"claimsOnly":true}'
    with pytest.raises(AgentError): checked_tool_success(raw)


@pytest.mark.parametrize("problem", ["duplicate", "too_many", "long_excerpt", "raw_payload"])
def test_evidence_output_is_bounded_unique_and_has_no_full_payload_escape(agent_storage, problem):
    from app.agents.contracts import AgentError
    from app.agents.tool_contracts import checked_tool_success
    _, _, run = running(agent_storage)
    context = run.manifest.context; fact = context.factScope[0]
    entry = dict(id=fact.id, sourcePath=fact.sourcePath, category=fact.category, excerpt="Synthetic excerpt", truncated=True)
    entries = [entry]
    if problem == "duplicate": entries = [entry, entry]
    elif problem == "too_many": entries = [{**entry, "id": "f1:" + str(index) * 64} for index in range(9)]
    elif problem == "long_excerpt": entries = [{**entry, "excerpt": "x" * 257}]
    else: entries = [{**entry, "rawPayload": "synthetic-private-full"}]
    body = dict(schemaVersion=1, tool="retrieve_truth", soupId=context.soupId,
        puzzleVersion=context.observedPuzzleVersion, facts=entries)
    with pytest.raises(AgentError): checked_tool_success(body)
