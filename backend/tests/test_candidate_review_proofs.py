"""Review proof transformations over actual isolated regression/candidate rows."""
from importlib import import_module
from uuid import uuid4

import pytest

from app import baselines
from app.agents.contracts import CandidateRecord, RegressionReport, candidate_digest, checked_model, checked_draft
from .test_rule_snapshots import rule_storage
from .test_agent_store import raw_rows, store
from .test_candidate_review_contracts import body


def actual_material(active, monkeypatch):
    # Import inside the test, so missing interfaces are failures, not fixture
    # setup/collection errors. No passing regression report is manufactured.
    module = import_module("app.candidate_review")
    from backend.testing.agent_fixtures import run_agent_scenario
    scenario = run_agent_scenario(active, "candidate", monkeypatch=monkeypatch)
    assert scenario["state"] == "awaiting_review" and scenario["realProviderState"] == "not_called"
    candidate = checked_model(CandidateRecord, raw_rows("rule_candidates")[0]["candidate_json"])
    row = next(row for row in raw_rows("agent_steps") if row["operation_key"] == candidate.regressionReportId)
    report = checked_model(RegressionReport, row["result_json"])
    run = store(active).read(candidate.runId)
    assert report.status == "complete" and report.inputCaseCount == report.passedCaseCount == 7
    return module, candidate, report, run


def changed_candidate(candidate, changes, *, report_digest=None):
    draft = checked_draft({**candidate.draft.model_dump(mode="json"), **changes})
    digest = report_digest or candidate.reportDigest
    return checked_model(CandidateRecord, candidate.model_copy(update={"draft": draft,
        "reportDigest": digest, "candidateDigest": candidate_digest(draft, run_id=candidate.runId,
            report_id=candidate.regressionReportId, report_digest=digest)}))


def test_actual_candidate_report_and_publication_digests_are_distinct_and_bound(rule_storage, monkeypatch):
    module, candidate, report, run = actual_material(rule_storage, monkeypatch)
    from app.candidate_review_contracts import CandidateApprove
    approval = CandidateApprove.model_validate(body("CandidateApprove"))
    checked = module.validate_candidate_report(candidate, report, run)
    draft = module.publication_draft(candidate, approval)
    value = draft.model_dump(mode="json")
    assert checked == (candidate, report, run)
    assert value["op"] == "replace" and value["canonicalQuestionKey"] == "小明是凶手吗"
    assert value["question"] == "小明是凶手吗？" and value["answer"] == "是"
    assert value["confirmedContext"] is True and value["targetRuleDigest"] == candidate.draft.targetRuleDigest
    assert value["factIds"] == list(candidate.draft.factIds)
    assert set(value) == {"op", "canonicalQuestionKey", "question", "answer", "factIds",
        "targetRuleDigest", "puzzleVersion", "baseRuleVersion", "confirmedContext"}
    assert report.draftDigest == baselines.digest(candidate.draft.model_dump(mode="json"))
    assert baselines.digest(value) != report.draftDigest
    # Pure conversion and mechanical binding are NOT approval or publication.
    assert raw_rows("rule_candidates")[0]["status"] == "pending"
    assert store(rule_storage).read_status(run.id).state == "awaiting_review"


@pytest.mark.parametrize("change", [dict(answer="不是"), dict(evidenceSummary="Different synthetic claim"),
    dict(factIds=["f1:" + "e" * 64]), dict(operation="add", targetRuleDigest=None),
    dict(targetRuleDigest="e" * 64), dict(question="小王是凶手吗？")],
    ids=["answer", "evidence-summary", "facts", "operation", "target", "question"])
def test_changed_candidate_cannot_use_old_report_even_with_recomputed_candidate_digest(rule_storage, monkeypatch, change):
    module, candidate, report, run = actual_material(rule_storage, monkeypatch)
    from app.candidate_review_contracts import CandidateReviewError
    with pytest.raises(CandidateReviewError) as caught:
        module.validate_candidate_report(changed_candidate(candidate, change), report, run)
    assert caught.value.code == "candidate_proof_invalid"


@pytest.mark.parametrize("field", ["reportId", "runId", "contextDigest", "suiteManifestDigest", "elapsedSeconds"])
def test_changed_report_body_cannot_reuse_original_candidate_proof(rule_storage, monkeypatch, field):
    module, candidate, report, run = actual_material(rule_storage, monkeypatch)
    from app.candidate_review_contracts import CandidateReviewError
    value = str(uuid4()) if field in {"reportId", "runId"} else 0.2 if field == "elapsedSeconds" else "e" * 64
    altered = checked_model(RegressionReport, report.model_copy(update={field: value}))
    with pytest.raises(CandidateReviewError):
        module.validate_candidate_report(candidate, altered, run)


@pytest.mark.parametrize("field", ["contextDigest", "suiteManifestDigest"])
def test_self_consistent_candidate_and_report_still_need_independent_original_run_binding(rule_storage, monkeypatch, field):
    module, candidate, report, run = actual_material(rule_storage, monkeypatch)
    from app.candidate_review_contracts import CandidateReviewError
    altered = checked_model(RegressionReport, report.model_copy(update={field: "e" * 64}))
    altered_candidate = changed_candidate(candidate, {}, report_digest=baselines.digest(altered.model_dump(mode="json")))
    with pytest.raises(CandidateReviewError):
        module.validate_candidate_report(altered_candidate, altered, run)


def test_publication_conversion_revalidates_copied_human_confirmations(rule_storage, monkeypatch):
    module, candidate, _, _ = actual_material(rule_storage, monkeypatch)
    from app.candidate_review_contracts import CandidateApprove, CandidateReviewError
    approval = CandidateApprove.model_validate(body("CandidateApprove"))
    for field in ("answerSupported", "contextIndependent"):
        with pytest.raises(CandidateReviewError):
            module.publication_draft(candidate, approval.model_copy(update={field: 1}))


@pytest.mark.parametrize("filename", ["candidate_review.py", "candidate_review_contracts.py", "rule_publication.py", "admin_candidates.py"])
def test_review_execution_dependencies_invalidate_fixed_suite_when_bytes_change(rule_storage, monkeypatch, filename):
    """A report must not stay current after its review policy dependency changes."""
    from pathlib import Path
    from app.agents.regression import FixedRegression
    from app.agents.contracts import AgentError

    FixedRegression(rule_storage)
    original = Path.read_bytes

    def changed(path):
        value = original(path)
        return value + b"\n# synthetic changed review policy\n" if path.name == filename else value

    monkeypatch.setattr(Path, "read_bytes", changed)
    with pytest.raises(AgentError) as caught:
        FixedRegression(rule_storage)
    assert caught.value.code == "agent_source_reload_required"
