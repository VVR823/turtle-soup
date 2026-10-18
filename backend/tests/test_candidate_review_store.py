"""Private detail over real synthetic runs, not fabricated passing reports."""
from importlib import import_module
from uuid import uuid4

import pytest

from app import baselines, db
from app.runtime import Runtime
from app.config import Settings
from .test_rule_snapshots import rule_storage, schema2
from .test_feedback_storage import snapshot


def proposal(active, *, corpus=None):
    # Missing product interfaces fail inside tests, not during fixture setup.
    review = import_module("app.candidate_review").CandidateReviewStore(active)
    from app.agents.regression import FixedRegression
    from app.agents.repair_agent import RepairAgent
    from app.agents.tools import ToolExecutor
    from app.model_gateway import ModelGateway
    from backend.testing.agent_fixtures import _Conditional
    from .test_candidate_validation import scope
    from .test_repair_corpus import frozen_corpus, setup_run
    from .test_agent_store import raw_rows
    from threading import Event

    source = scope()
    active.repair_corpus = frozen_corpus(source) if corpus is None else corpus
    regression = FixedRegression(active, corpus=active.repair_corpus)
    owner, run, _, draft, _ = setup_run(active, regression, source)
    transport = _Conditional(draft)
    gateway = ModelGateway(adapter_factory=lambda: transport)
    active.model_gateway = gateway
    try:
        result = RepairAgent(owner, ToolExecutor(owner, regression=regression), gateway).drive(run.id, run.leaseToken, Event())
    finally:
        cleanup = gateway.close(wait_seconds=0.5)
    assert result.state == "awaiting_review" and cleanup["active"] == 0, (
        f"state={result.state}, reason={result.reason}, models={result.modelAttemptsUsed}, tools={result.toolAttemptsUsed}")
    candidate = next(row for row in raw_rows("rule_candidates") if row["run_id"] == run.id)
    return review, owner.read(run.id), candidate["id"]


def test_detail_contains_actual_claims_facts_old_new_and_all_cases_without_writing(rule_storage, monkeypatch):
    review, run, cid = proposal(rule_storage)
    before = snapshot()

    def forbidden(*args, **kwargs):
        raise AssertionError("Review read allocated a model or initialized storage")

    monkeypatch.setattr(Runtime, "get_model_gateway", forbidden)
    monkeypatch.setattr(db, "initialize", forbidden)
    result = review.detail(cid)
    assert result.candidateId == cid and result.runId == run.id
    assert result.candidateStatus == "pending" and result.reviewVersion == 0
    assert result.availability == "ready" and result.proofDigest is not None and result.blockers == ()
    assert result.agentStatus.state == "awaiting_review" and result.agentStatus.candidateId == cid
    material = result.material
    assert material.inputKind == "user_claim" and material.draftKind == "model_summary"
    assert material.sanitizedInput.question == "是谁？" and material.sanitizedInput.expectedClaim == "不知道"
    assert material.programDiagnostic.resultDigest == run.manifest.context.programDiagnostic.resultDigest
    assert material.draft.question == "小明是凶手吗？" and material.draft.answer == "是"
    assert material.oldTarget.question == "小明是凶手吗？" and material.oldTarget.answer == "不是"
    assert material.oldTarget.type == "confusion" and material.oldTarget.sourcePath == "confusionPoints[0]"
    assert material.oldTarget.targetRuleDigest == material.draft.targetRuleDigest
    assert material.factScope == run.manifest.context.factScope
    assert material.highlightedFactIds == material.draft.factIds
    assert material.report.status == "complete" and material.report.evidenceKind == "synthetic_fixture"
    assert material.report.inputCaseCount == material.report.passedCaseCount == len(material.report.caseResults) == 7
    assert material.report.cleanupConfirmed and not material.report.truncated
    assert result.review is None and result.publishedRuleVersion is None
    assert snapshot() == before and rule_storage.model.calls == []
    serialized = result.model_dump_json()
    assert "leaseToken" not in serialized and "manifest" not in serialized and "PRIVATE synthetic claim" not in serialized


def test_expired_original_execution_deadline_does_not_prevent_later_human_read(rule_storage, monkeypatch):
    review, run, cid = proposal(rule_storage)
    monkeypatch.setattr("time.time", lambda: run.checkpoint.deadlineAt + 1000)
    assert review.detail(cid).availability == "ready"


@pytest.mark.parametrize("change", ["withdraw", "new_input"])
def test_changed_privacy_or_input_only_exposes_minimal_stale_state(rule_storage, change):
    from app.feedback_store import set_model_permission
    from app.feedback_contract import PrivacyReview
    from .test_feedback_privacy import permission
    review, run, cid = proposal(rule_storage)
    decision = PrivacyReview(safeForModel=False, reviewNote="Synthetic withdrawal") if change == "withdraw" else permission(sanitizedQuestion="new claim")
    set_model_permission(run.feedbackId, run.manifest.context.sourceFeedbackVersion, review=decision)
    before = snapshot()
    result = review.detail(cid)
    assert result.availability == "stale" and result.material is None and result.proofDigest is None
    assert result.blockers == ("candidate_source_stale",)
    assert "是谁" not in result.model_dump_json() and "凶手" not in result.model_dump_json()
    assert snapshot() == before


def test_changed_active_base_keeps_pinned_history_without_mutation_proof(rule_storage):
    review, run, cid = proposal(rule_storage)
    conn = db._connect()
    try:
        _, version, _ = schema2(conn)
        conn.execute("UPDATE runtime_meta SET value_json=?,row_version=row_version+1 WHERE key='active_baseline'",
            (baselines.canonical_json(dict(schemaVersion=1, ruleVersion=version)),))
        conn.commit()
    finally:
        conn.close()
    result = review.detail(cid)
    assert result.availability == "historical" and result.proofDigest is None
    assert result.activeRuleVersion == version and result.activePointerVersion == 1
    assert result.material.draft.baseRuleVersion == run.manifest.context.baseRuleVersion
    assert result.material.oldTarget.answer == "不是" and result.material.draft.answer == "是"
    assert result.blockers == ("candidate_base_changed",)


def test_changed_corpus_keeps_report_history_but_cannot_offer_approval_proof(rule_storage):
    from .test_repair_corpus import frozen_corpus
    from .test_candidate_validation import scope
    review, _, cid = proposal(rule_storage)
    rule_storage.repair_corpus = frozen_corpus(scope())  # fresh frozen IDs => different digest
    result = review.detail(cid)
    assert result.availability == "historical" and result.proofDigest is None
    assert result.material.report.inputCaseCount == 7
    assert result.blockers == ("candidate_suite_changed",)


def test_missing_corpus_never_becomes_ready_from_a_stored_complete_report(rule_storage):
    review, _, cid = proposal(rule_storage)
    rule_storage.repair_corpus = None
    result = review.detail(cid)
    assert result.availability == "unavailable" and result.material is None and result.proofDigest is None
    assert result.blockers == ("candidate_corpus_missing",)


def test_unbacked_approved_sql_status_is_not_fabricated_review_authority(rule_storage):
    from app.candidate_review_contracts import CandidateReviewError
    review, _, cid = proposal(rule_storage)
    conn = db._connect()
    try:
        conn.execute("UPDATE rule_candidates SET status='approved',reviewed_at=1 WHERE id=?", (cid,))
        conn.commit()
    finally:
        conn.close()
    with pytest.raises(CandidateReviewError) as caught:
        review.detail(cid)
    assert caught.value.code == "candidate_review_corrupt" and caught.value.status == 503


def test_read_missing_or_feature_disabled_database_does_not_initialize_it(tmp_path):
    from app.candidate_review_contracts import CandidateReviewError
    module = import_module("app.candidate_review")
    active = Runtime(Settings.for_test(tmp_path / "never-created"))
    with pytest.raises(CandidateReviewError) as caught:
        module.CandidateReviewStore(active).detail(str(uuid4()))
    assert caught.value.status == 503 and not active.settings.DATA_DIR.exists()


def test_missing_candidate_is_controlled_not_an_empty_success(rule_storage):
    from app.candidate_review_contracts import CandidateReviewError
    review, _, _ = proposal(rule_storage)
    with pytest.raises(CandidateReviewError) as caught:
        review.detail(str(uuid4()))
    assert caught.value.code == "candidate_not_found" and caught.value.status == 404


def test_code_bytes_changed_after_report_only_allow_pinned_history(rule_storage, monkeypatch):
    from pathlib import Path
    review, _, cid = proposal(rule_storage)
    read_bytes = Path.read_bytes

    def changed_bytes(path):
        data = read_bytes(path)
        return data + b"\n# Synthetic hot-code change, no file edit\n" if path.name == "candidate_review.py" else data

    monkeypatch.setattr(Path, "read_bytes", changed_bytes)
    result = review.detail(cid)
    assert result.availability == "historical" and result.proofDigest is None
    assert result.blockers == ("candidate_suite_changed",) and result.material.report.inputCaseCount == 7


def test_foreign_later_finish_cannot_borrow_existing_candidate_proof(rule_storage):
    from app.agents.contracts import FinishAction
    from app.agents.store import FinishRecord
    from app.candidate_review_contracts import CandidateReviewError
    review, run, cid = proposal(rule_storage)
    other = str(uuid4())
    action = FinishAction(action="finish", candidateId=other)
    outcome = FinishRecord(runId=run.id, state="awaiting_review", candidateId=other, executionDigest="e" * 64)
    conn = db._connect()
    try:
        seq = conn.execute("SELECT max(seq)+1 FROM agent_steps WHERE run_id=?", (run.id,)).fetchone()[0]
        conn.execute("INSERT INTO agent_steps(run_id,seq,operation_key,action_json,result_json,state,created_at) VALUES(?,?,?,?,?,'completed',?)",
            (run.id, seq, str(uuid4()), baselines.canonical_json(action.model_dump(mode="json")),
                baselines.canonical_json(outcome.model_dump(mode="json")), run.updatedAt))
        conn.commit()
    finally:
        conn.close()
    before = snapshot()
    with pytest.raises(CandidateReviewError) as caught:
        review.detail(cid)
    assert caught.value.code == "candidate_proof_invalid" and snapshot() == before


def test_suite_read_failure_is_not_misreported_as_invalid_corpus(rule_storage, monkeypatch):
    from app.agents.contracts import AgentError
    from app.agents.regression import FixedRegression
    review, _, cid = proposal(rule_storage)

    def unavailable(self):
        raise AgentError("agent_suite_unavailable", 503)

    monkeypatch.setattr(FixedRegression, "_suite_identity", unavailable)
    result = review.detail(cid)
    assert result.availability == "unavailable" and result.material is None and result.proofDigest is None
    assert result.blockers == ("candidate_suite_unavailable",)
