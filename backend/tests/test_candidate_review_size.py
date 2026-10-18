"""Actual large source facts and pre-task refusal, no fabricated passing report."""
import pytest

from app import baselines
from app.schemas import TruthItem
from .test_rule_snapshots import rule_storage
from .test_candidate_validation import scope


def large_soup(active, count):
    return active.soups[0].model_copy(update={"truthItems": [TruthItem(subject=f"附加条目{number}",
        relation="记载", object="合成背景事实", evidence="额外资料" * 500, confidence="low")
        for number in range(count)]})


def test_actual_large_source_detail_preserves_every_fact_qualifier_and_report_case(rule_storage, request):
    # This measures the human detail, NOT autonomous model prompt capacity.
    # Run native tools/save/finish directly with real owned lease/rows/report;
    # the unchanged 8000-character model prompt budget is not enlarged.
    from uuid import uuid4
    from app.agents.contracts import ExecutionIdentity, FinishAction, parse_tool_action
    from app.agents.regression import FixedRegression
    from app.agents.tools import ToolExecutor
    from app.candidate_review import CandidateReviewStore
    from .test_repair_corpus import frozen_corpus, setup_run
    source = scope(soup=large_soup(rule_storage, 40))
    rule_storage.repair_corpus = frozen_corpus(source)
    regression = FixedRegression(rule_storage, corpus=rule_storage.repair_corpus)
    owner, running, identity, draft, action = setup_run(rule_storage, regression, source)
    tools = ToolExecutor(owner, regression=regression)
    report = tools.execute(identity, action)
    save_identity = ExecutionIdentity(runId=running.id, leaseToken=running.leaseToken, seq=1, operationKey=str(uuid4()))
    saved = tools.execute(save_identity, parse_tool_action(dict(action="tool", tool="save_candidate_rule",
        arguments=dict(draft=draft.model_dump(mode="json"), regressionReportId=report.reportId))))
    cid = saved.id
    owner.finish(ExecutionIdentity(runId=running.id, leaseToken=running.leaseToken, seq=2, operationKey=str(uuid4())),
        FinishAction(action="finish", candidateId=cid))
    run = owner.read(running.id)
    assert run.checkpoint.modelAttemptsUsed == 0
    review = CandidateReviewStore(rule_storage)
    detail = review.detail(cid)
    assert detail.availability == "ready" and detail.material.factScope == run.manifest.context.factScope
    assert len(detail.material.factScope) == 42  # bottom + 40 facts + one old confusion
    facts = [fact for fact in detail.material.factScope if fact.category == "truth" and fact.sourcePath != "bottom"]
    assert len(facts) == 40
    for fact in facts:
        payload = baselines.strict_json(fact.payload)
        assert payload["confidence"] == "low" and payload["evidence"] == "额外资料" * 500
    assert detail.material.report.inputCaseCount == len(detail.material.report.caseResults) == 7
    detail_bytes = len(detail.model_dump_json().encode("utf-8"))
    assert 200000 < detail_bytes <= 524288
    # Native JUnit node properties work with this project's xunit2 serializer;
    # record_property warns that its fixture targets the legacy XML family.
    request.node.user_properties.extend([
        ("evidence_kind", "declared_synthetic_native_tool_fixture_not_autonomous_model"),
        ("detail_bytes", str(detail_bytes)), ("fact_count", str(len(detail.material.factScope))),
        ("model_attempts", str(run.checkpoint.modelAttemptsUsed)),
        ("report_case_count", str(detail.material.report.inputCaseCount)),
    ])


def test_source_over_response_cap_is_refused_before_task_not_silently_truncated(rule_storage):
    from app.task_context import freeze_task_context, NeedsHuman
    from .test_task_context import prepared, TOOLS
    # Full source facts already have a stricter 256KiB TaskContext bound, so a
    # 512KiB+ source cannot legally produce a complete review detail at all.
    soup = large_soup(rule_storage, 90)
    from app import db
    conn = db._connect()
    try:
        conn.execute("DELETE FROM runtime_meta WHERE key='active_baseline'")
        baselines.store_baseline(conn, [soup])
        conn.commit()
    finally:
        conn.close()
    assert len(baselines.canonical_json(soup.model_dump(mode="json")).encode("utf-8")) > 524288
    item = prepared()
    with pytest.raises(NeedsHuman) as caught:
        freeze_task_context(item.id, item.rowVersion, allowed_tools=TOOLS)
    assert caught.value.code == "feedback_context_invalid"
    # No 003 is silently created by this failed context-only entry point.
    conn = db._connect()
    try:
        assert conn.execute("SELECT 1 FROM sqlite_master WHERE name='agent_runs'").fetchone() is None
    finally:
        conn.close()
    assert rule_storage.model.calls == []
