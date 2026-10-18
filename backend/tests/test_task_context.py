"""Frozen owned evidence checks permission and scopes at every future entry."""
import json

import pytest
from pydantic import ValidationError

from app import db
from .test_feedback_privacy import approved_linked, permission
from .test_feedback_storage import body, rows, storage

TOOLS = ("get_turn_trace", "retrieve_truth", "find_rule_conflicts", "run_regression", "save_candidate_rule")


def prepared():
    from app.feedback_store import set_model_permission
    item = approved_linked()
    return set_model_permission(item.id, item.rowVersion, review=permission())


def frozen(item):
    from app.task_context import freeze_task_context
    return freeze_task_context(item.id, item.rowVersion, allowed_tools=TOOLS)


def test_permission_required_despite_approved(storage):
    from app.task_context import NeedsHuman
    item = approved_linked()
    with pytest.raises(NeedsHuman) as caught:
        frozen(item)
    assert caught.value.code == "feedback_permission_required" and storage.model.calls == []


def test_frozen_context_only_sanitized_input_and_actual_trace_scope(storage):
    from app.task_context import verify_task_context
    item = prepared(); context = frozen(item)
    source = json.loads(rows("feedback_items")[0]["source_json"])
    assert context.feedbackId == item.id and context.sourceFeedbackVersion == 2
    assert context.turnId == item.turnId and context.soupId == item.soupId
    assert context.observedPuzzleVersion == source["puzzleVersion"]
    assert context.observedRuleVersion == source["ruleVersion"] and context.allowedTools == TOOLS
    assert context.sanitizedInput.expectedClaim == "不知道"
    assert context.factScope and all(fact.soupId == item.soupId for fact in context.factScope)
    assert "PRIVATE synthetic claim" not in context.model_dump_json() and storage.model.calls == []
    verify_task_context(context, tool="retrieve_truth")
    with pytest.raises(ValidationError):
        context.soupId = "other"
    with pytest.raises(ValidationError):
        context.sanitizedInput.question = "other"


def test_revoke_after_freeze_blocks_next_entry(storage):
    from app.feedback_contract import PrivacyReview
    from app.feedback_store import set_model_permission
    from app.task_context import NeedsHuman, verify_task_context
    item = prepared(); context = frozen(item)
    set_model_permission(item.id, item.rowVersion, review=PrivacyReview(safeForModel=False, reviewNote="Revoke"))
    with pytest.raises(NeedsHuman):
        verify_task_context(context)
    assert storage.model.calls == []


def test_row_version_change_even_still_safe_blocks_frozen_source(storage):
    from app.feedback_store import set_model_permission
    from app.task_context import NeedsHuman, verify_task_context
    item = prepared(); context = frozen(item)
    set_model_permission(item.id, item.rowVersion, review=permission(sanitizedQuestion="经过新审核的问题？"))
    assert rows("feedback_items")[0]["safe_for_model"] == 1
    with pytest.raises(NeedsHuman) as caught:
        verify_task_context(context)
    assert caught.value.code == "feedback_context_stale"


@pytest.mark.parametrize("scope", [{"soup_id": "other"}, {"turn_id": "other"},
    {"puzzle_version": "p1:other"}, {"base_rule_version": "r1:other"}, {"tool": "shell_exec"}])
def test_foreign_scope_or_tool_cannot_borrow_another_context(storage, scope):
    from app.task_context import NeedsHuman, verify_task_context
    with pytest.raises(NeedsHuman):
        verify_task_context(frozen(prepared()), **scope)


@pytest.mark.parametrize("toolset", [(), ("shell_exec",), ("retrieve_truth", "retrieve_truth")])
def test_frozen_tool_scope_is_nonempty_registered_and_unique(storage, toolset):
    from app.task_context import NeedsHuman, freeze_task_context
    item = prepared()
    with pytest.raises(NeedsHuman):
        freeze_task_context(item.id, item.rowVersion, allowed_tools=toolset)


def test_unlinked_feedback_cannot_gain_trace_by_manual_permission(storage):
    from app.feedback_store import review_feedback, set_model_permission, submit_feedback
    from app.task_context import NeedsHuman
    item = submit_feedback(body()); item = review_feedback(item.id, 0, status="approved")
    item = set_model_permission(item.id, item.rowVersion, review=permission())
    with pytest.raises(NeedsHuman) as caught:
        frozen(item)
    assert caught.value.code == "feedback_trace_required"


def test_suspension_blocks_context_without_erasing_history(storage):
    from app.task_context import NeedsHuman, verify_task_context
    item = prepared(); context = frozen(item)
    conn = db._connect()
    conn.execute("INSERT INTO runtime_meta(key,value_json) VALUES(?,?)",
        ("rule_suspension:" + context.baseRuleVersion.removeprefix("r1:"),
         json.dumps({"schemaVersion": 1, "ruleVersion": context.baseRuleVersion, "suspended": True, "reason": "Synthetic suspension"})))
    conn.commit(); conn.close()
    with pytest.raises(NeedsHuman) as caught:
        verify_task_context(context)
    assert caught.value.code == "rule_version_suspended" and rows("feedback_items")


@pytest.mark.parametrize("field,value", [("soupId", "foreign"), ("turnId", "foreign"),
    ("inputDigest", "a" * 64), ("baseRuleVersion", "r1:" + "a" * 64)])
def test_model_copy_bypass_cannot_change_frozen_authority(storage, field, value):
    from app.task_context import NeedsHuman, verify_task_context
    context = frozen(prepared())
    with pytest.raises(NeedsHuman):
        verify_task_context(context.model_copy(update={field: value}))


def test_frozen_context_refuses_current_puzzle_change_without_implicit_rebase(storage):
    from app import baselines
    from app.task_context import NeedsHuman, verify_task_context
    from .test_migrations import puzzle
    context = frozen(prepared()); conn = db._connect()
    try:
        changed = puzzle().model_copy(update={"bottom": "Different synthetic truth"})
        conn.execute("DELETE FROM runtime_meta WHERE key='active_baseline'")
        baselines.store_baseline(conn, [changed]); conn.commit()
    finally:
        conn.close()
    with pytest.raises(NeedsHuman):
        verify_task_context(context)


def test_legacy_import_has_no_turn_even_after_review_and_permission(storage, tmp_path):
    from app.feedback_store import review_feedback, set_model_permission
    from app.task_context import NeedsHuman
    from .test_feedback_import import imported, legacy, source_file
    source, digest, _ = source_file(tmp_path, [legacy()]); imported(source, digest)
    item = review_feedback(rows("feedback_items")[0]["id"], 0, status="approved")
    item = set_model_permission(item.id, item.rowVersion, review=permission())
    with pytest.raises(NeedsHuman) as caught:
        frozen(item)
    assert caught.value.code == "feedback_trace_required" and storage.model.calls == []


@pytest.mark.parametrize("mutation", ["missing-note", "bool-schema", "float-version", "bad-time"])
def test_corrupt_manual_privacy_record_is_not_usable_context(storage, mutation):
    from app.task_context import NeedsHuman
    item = prepared(); row = rows("feedback_items")[0]; source = json.loads(row["source_json"])
    if mutation == "missing-note":
        source["privacy"].pop("reviewNote")
    elif mutation == "bool-schema":
        source["privacy"]["schemaVersion"] = True
    elif mutation == "float-version":
        source["privacy"]["rowVersion"] = 2.0
    else:
        source["privacy"]["reviewedAt"] = "wrong-date"
    conn = db._connect()
    conn.execute("UPDATE feedback_items SET source_json=? WHERE id=?", (json.dumps(source), item.id)); conn.commit(); conn.close()
    with pytest.raises(NeedsHuman):
        frozen(item)


def test_boolean_context_schema_is_not_a_real_version(storage):
    from app.task_context import NeedsHuman, verify_task_context
    context = frozen(prepared())
    with pytest.raises(NeedsHuman):
        verify_task_context(context.model_copy(update={"schemaVersion": True}))


def test_oversized_catalog_needs_human_without_silent_fact_truncation(runtime):
    from app.task_context import NeedsHuman
    from .test_migrations import puzzle
    from app.schemas import TruthItem
    runtime.soups = [puzzle().model_copy(update={"truthItems": [TruthItem(subject=f"Synthetic subject {index}",
        relation="is", object="Synthetic fact") for index in range(260)]})]
    db.initialize()
    with pytest.raises(NeedsHuman):
        frozen(prepared())
    assert runtime.model.calls == []


def test_corrupt_root_source_schema_boolean_is_not_a_verified_trace(storage):
    from app.task_context import NeedsHuman
    item = prepared(); source = json.loads(rows("feedback_items")[0]["source_json"])
    source["schemaVersion"] = True
    conn = db._connect()
    conn.execute("UPDATE feedback_items SET source_json=? WHERE id=?", (json.dumps(source), item.id)); conn.commit(); conn.close()
    with pytest.raises(NeedsHuman):
        frozen(item)
