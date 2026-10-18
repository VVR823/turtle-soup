"""Independently frozen synthetic labels test wiring, never real human quality."""
from uuid import uuid4

import pytest

from .test_rule_snapshots import rule_storage
from .test_candidate_validation import scope
from .test_task_context import prepared, TOOLS
from .test_agent_store import raw_rows
from .test_feedback_storage import snapshot


def frozen_corpus(source, *, labels=("是", "与此无关"), omit_candidate=False, extra_cases=0, context_chain=False):
    from app import baselines
    from eval.contracts import EvalCase, EvalPuzzle, ExpectedLabel, ReviewRecord, case_digest, review_context_digest
    from eval.grouping import audit_groups
    from eval.manifest import freeze_regression
    from backend.eval.tests.test_dataset_grouping import sources
    context, soup, rules, _ = source
    cases = []
    questions = ("小明是凶手吗？", "小红是凶手吗？") + tuple(f"合成角色{n}是凶手吗？" for n in range(extra_cases))
    labels = (*labels, *("与此无关" for _ in range(extra_cases)))
    if context_chain:
        questions = (*questions[:2], "小刚是凶手吗？")
        labels = (*labels[:2], "与此无关")
    for number, (question, answer) in enumerate(zip(questions, labels)):
        if number == 0 and omit_candidate: continue
        group = "owned-synthetic-chain" if context_chain else "owned-synthetic-" + str(number)
        case = EvalCase(caseId=str(uuid4()), soupId=soup.id, puzzleVersion=rules.puzzleVersion,
            question=question, caseType="context" if context_chain else "single", split="regression", sourceGroup=group, familyGroup=group,
            conversationId="owned-synthetic-chain" if context_chain else None,
            contextIndex=number + 1 if context_chain else None, categories=("synthetic-fixture",), visibility="public_authorized",
            origin="public_synthetic", evidenceSourceDigest=baselines.digest(group), authorRole="synthetic",
            reviewState="pending", proposedLabel=None, rawLegacyExpected=None, review=None)
        receipt = ReviewRecord(operatorId="synthetic-test-only", reviewedAt="2026-10-10T00:00:00Z",
            caseDigest=case_digest(case), expectedLabel=ExpectedLabel(kind="answer", answer=answer),
            factIds=(context.factScope[0].id,), humanConfirmed=True,
            reviewNote="Synthetic mechanical fixture, NOT an actual human label")
        cases.append(case.model_copy(update={"reviewState": "reviewed", "review": receipt}))
    cases = tuple(cases)
    if context_chain:
        cases = tuple(c.model_copy(update={"review": c.review.model_copy(update={
            "contextDigest": review_context_digest(c, cases)})}) for c in cases)
    catalog = (EvalPuzzle(soupId=soup.id, puzzleVersion=rules.puzzleVersion,
        soupJson=baselines.canonical_json(soup.model_dump(mode="json")), ruleSnapshot=rules),)
    proof = audit_groups((), repair_cases=cases, source_digests=sources(cases), source_complete=True)
    return freeze_regression(cases, catalog=catalog, audit=proof, source_digests=sources(cases), frozen_at="2026-10-10T00:00:00Z")


def setup_run(active, executor, source):
    from app import db
    from app.migrations import migrate
    from app.agents.contracts import checked_draft, parse_tool_action
    from app.agents.store import AgentStore
    from .test_agent_store import step_inputs
    conn = db._connect()
    try: migrate(conn, active.soups, target_version=3)
    finally: conn.close()
    owner = AgentStore(active, authorize_create=lambda context: True)
    item = prepared()
    run = owner.create(request_id=str(uuid4()), feedback_id=item.id, expected_feedback_version=item.rowVersion,
        allowed_tools=TOOLS, suite_manifest_digest=executor.suite_manifest_digest)
    run = owner.claim(run.id, expected_row_version=0)
    identity, _ = step_inputs(run)
    draft = checked_draft(source[3])
    action = parse_tool_action(dict(action="tool", tool="run_regression", arguments=dict(draft=draft.model_dump(mode="json"))))
    return owner, run, identity, draft, action


def test_fixed_synthetic_corpus_executes_actual_preview_then_saves_pending_without_publication(rule_storage):
    from app.agents.regression import FixedRegression
    from app.agents.tools import ToolExecutor
    from .test_candidate_reports import save_inputs
    source = scope(); corpus = frozen_corpus(source)
    executor = FixedRegression(rule_storage, corpus=corpus)
    owner, run, identity, draft, action = setup_run(rule_storage, executor, source)
    dispatcher = ToolExecutor(owner, regression=executor)
    value = dispatcher.execute(identity, action)
    assert value.status == "complete" and value.evidenceKind == "synthetic_fixture"
    assert value.inputCaseCount == value.attemptedCaseCount == value.passedCaseCount == 7
    assert len([r for r in value.caseResults if r.suite == "dev_regression"]) == 2
    saved_identity, saved_action = save_inputs(run, draft, identity.operationKey)
    saved = dispatcher.execute(saved_identity, saved_action)
    assert saved.status == "pending" and raw_rows("agent_steps")[0]["state"] == "completed"
    assert rule_storage.model.calls == [] and rule_storage.model_gateway is None
    assert "小明" not in value.model_dump_json() and "expectedLabel" not in value.model_dump_json()


@pytest.mark.parametrize("labels", [("不是", "与此无关"), ("是", "不是")])
def test_independent_counterexamples_cannot_be_rewritten_or_hidden(rule_storage, labels):
    from app.agents.regression import FixedRegression
    source = scope(); corpus = frozen_corpus(source, labels=labels)
    executor = FixedRegression(rule_storage, corpus=corpus)
    owner, run, identity, draft, _ = setup_run(rule_storage, executor, source)
    value = executor.run(draft, run=run, identity=identity, soup=source[1], rule_snapshot=source[2])
    assert value.status == "failed" and value.inputCaseCount == 7 and value.attemptedCaseCount == 7
    assert any(r.code == "counterexample" for r in value.caseResults)
    assert executor.corpus == corpus and rule_storage.model.calls == []


def test_replace_without_independent_candidate_question_never_passes(rule_storage):
    from app.agents.regression import FixedRegression
    source = scope(); executor = FixedRegression(rule_storage, corpus=frozen_corpus(source, omit_candidate=True))
    _, run, identity, draft, _ = setup_run(rule_storage, executor, source)
    value = executor.run(draft, run=run, identity=identity, soup=source[1], rule_snapshot=source[2])
    assert value.status == "incomplete" and any(r.code == "needs_corpus" for r in value.caseResults)


def test_corpus_forged_holdout_role_is_refused_without_reading_any_file(rule_storage):
    from app.agents.regression import FixedRegression
    from app.agents.contracts import AgentError
    corpus = frozen_corpus(scope()); before = snapshot()
    forged = corpus.model_copy(update={"manifest": corpus.manifest.model_copy(update={"splitRole": "holdout"})})
    with pytest.raises(AgentError): FixedRegression(rule_storage, corpus=forged)
    assert snapshot() == before and rule_storage.model.calls == []


def test_owned_fake_host_does_not_pollute_inherited_request_observations(rule_storage):
    from app.agents.regression import FixedRegression
    from app.audit_context import AttemptCollector, attempt_context
    source = scope(); executor = FixedRegression(rule_storage, corpus=frozen_corpus(source))
    _, run, identity, draft, _ = setup_run(rule_storage, executor, source)
    collector = AttemptCollector(str(uuid4()), traffic_class="real")
    with attempt_context(collector):
        value = executor.run(draft, run=run, identity=identity, soup=source[1], rule_snapshot=source[2])
    event = collector.finish(status_code=200, method="POST", route_template="unmatched",
        response_started=True, disconnected=False)
    assert value.status == "complete" and event.details.modelCalls == ()
    assert not event.details.modelCallsTruncated


def test_verified_corpus_over_100_cases_is_refused_not_silently_truncated(rule_storage):
    from app.agents.regression import FixedRegression
    from app.agents.contracts import AgentError
    corpus = frozen_corpus(scope(), extra_cases=99); before = snapshot()
    assert corpus.manifest.inputCount == 101
    with pytest.raises(AgentError) as caught: FixedRegression(rule_storage, corpus=corpus)
    assert caught.value.code == "agent_corpus_invalid" and snapshot() == before
    assert rule_storage.model_gateway is None


def test_source_compatible_labels_cannot_borrow_another_base_rule_version(rule_storage):
    from app.agents.regression import FixedRegression
    from app.agents.contracts import AgentError
    source = scope(); executor = FixedRegression(rule_storage, corpus=frozen_corpus(source))
    _, run, identity, draft, _ = setup_run(rule_storage, executor, source)
    with pytest.raises(AgentError): executor.run(draft, run=run, identity=identity,
        soup=source[1], rule_snapshot=source[2].model_copy(update={"ruleVersion": "r1:" + "e" * 64}))


def test_context_receives_actual_typed_prior_result_not_gold_or_display_only(rule_storage, monkeypatch):
    from app.agents.regression import FixedRegression
    import app.ai_host as host
    source = scope(); executor = FixedRegression(rule_storage,
        corpus=frozen_corpus(source, labels=("不是", "与此无关"), context_chain=True))
    _, run, identity, draft, _ = setup_run(rule_storage, executor, source)
    original = host.handle_host_response
    seen = []
    def observe(soup, history, question, **kwargs):
        seen.append([dict(row) for row in history])
        return original(soup, history, question, **kwargs)
    monkeypatch.setattr(host, "handle_host_response", observe)
    value = executor.run(draft, run=run, identity=identity, soup=source[1], rule_snapshot=source[2])
    assert value.status == "failed" and value.inputCaseCount == value.attemptedCaseCount == 8
    assert seen[0] == []
    assert seen[1] == [dict(role="user", content="小明是凶手吗？"),
        dict(role="host", content="是", answer="是", kind="answer", is_free_reminder=False)]
    assert len(seen[2]) == 4 and seen[2][-1]["answer"] == "与此无关"


def test_reused_executor_cannot_swap_another_valid_sealed_corpus_under_old_suite_identity(rule_storage):
    from app.agents.regression import FixedRegression
    from app.agents.contracts import AgentError
    source = scope(); executor = FixedRegression(rule_storage, corpus=frozen_corpus(source))
    _, run, identity, draft, _ = setup_run(rule_storage, executor, source)
    executor.corpus = frozen_corpus(source, labels=("不是", "与此无关"))
    with pytest.raises(AgentError): executor.run(draft, run=run, identity=identity,
        soup=source[1], rule_snapshot=source[2])


def test_reused_executor_refuses_changed_registered_code_instead_of_old_fingerprint_report(rule_storage, monkeypatch):
    from pathlib import Path
    from app.agents.regression import FixedRegression
    from app.agents.contracts import AgentError
    source = scope(); executor = FixedRegression(rule_storage, corpus=frozen_corpus(source))
    _, run, identity, draft, _ = setup_run(rule_storage, executor, source)
    original = Path.read_bytes
    def changed(path):
        value = original(path)
        return value + b"\n# owned synthetic changed code\n" if path.name == "rag.py" else value
    monkeypatch.setattr(Path, "read_bytes", changed)
    with pytest.raises(AgentError): executor.run(draft, run=run, identity=identity,
        soup=source[1], rule_snapshot=source[2])
