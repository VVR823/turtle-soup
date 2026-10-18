"""Unapproved exact preview preserves actual base and never mints a receipt."""
import pytest

from .test_candidate_validation import scope
from .test_rule_snapshots import rule_storage
from .test_feedback_storage import snapshot


def preview_inputs():
    from app.agents.contracts import checked_draft
    context, soup, rules, body = scope()
    return checked_draft(body), context, soup, rules


def baseline(soup, rules, question):
    from app.ai_host import handle_host_response
    from app.schemas import HostVersions
    return handle_host_response(soup, [], question, versions=HostVersions(
        puzzleVersion=rules.puzzleVersion, ruleVersion=rules.ruleVersion), rule_snapshot=rules)


def build(values):
    from app.agents.preview import CandidatePreview
    draft, context, soup, rules = values
    return CandidatePreview(draft, context=context, soup=soup, rule_snapshot=rules)


def test_local_exact_replacement_does_not_edit_base_or_become_human_proof(rule_storage):
    values = preview_inputs(); draft, _, soup, rules = values
    original = baseline(soup, rules, draft.question); before = snapshot()
    preview = build(values); value = preview.apply(draft.question, original)
    assert original.answer == "不是" and value.answer == "是"
    assert value.contextIndependent is False and value.cacheHit is False
    assert value.matchedCheckpoint == "candidate_preview" and value.versions == original.versions
    assert baseline(soup, rules, draft.question).answer == "不是" and snapshot() == before
    assert not hasattr(preview, "reviewReceipt") and rule_storage.model.calls == []


@pytest.mark.parametrize("question", ["小明不是凶手吗？", "这是恐怖故事吗？", "我还差什么？"])
def test_unrelated_or_negated_question_keeps_actual_original_host_result(rule_storage, question):
    values = preview_inputs(); original = baseline(values[2], values[3], question)
    assert build(values).apply(question, original) == original


@pytest.mark.parametrize("kind", ["reminder", "system_error", "win"])
def test_preview_cannot_hide_an_earlier_flow_or_failure_even_on_exact_key(rule_storage, kind):
    from app.schemas import HostResult, HostVersions
    values = preview_inputs()
    original = HostResult(kind=kind, chargeable=kind == "win", source="deterministic" if kind == "win" else "flow",
        errorCode="model_timeout" if kind == "system_error" else None, reply="Synthetic earlier flow",
        versions=HostVersions(puzzleVersion=values[3].puzzleVersion, ruleVersion=values[3].ruleVersion))
    assert build(values).apply(values[0].question, original) == original


def test_preview_refuses_foreign_version_outcome_instead_of_relabeling_it(rule_storage):
    from app.agents.contracts import AgentError
    values = preview_inputs(); original = baseline(values[2], values[3], values[0].question)
    with pytest.raises(AgentError): build(values).apply(values[0].question,
        original.model_copy(update={"versions": original.versions.model_copy(update={"ruleVersion": "r1:" + "e" * 64})}))


@pytest.mark.parametrize("question", ["", "x" * 501, None, True])
def test_preview_refuses_unbounded_or_untyped_question_before_override(rule_storage, question):
    from app.agents.contracts import AgentError
    values = preview_inputs(); original = baseline(values[2], values[3], values[0].question)
    with pytest.raises(AgentError) as caught:
        build(values).apply(question, original)
    assert caught.value.code == "agent_input_invalid"


def test_preview_refuses_changed_actual_truth_source_before_any_override(rule_storage):
    from app.agents.contracts import AgentError
    values = preview_inputs()
    with pytest.raises(AgentError): build((*values[:2], values[2].model_copy(update={"bottom": "Changed truth"}), values[3]))


def test_preview_constructor_rejects_a_known_conflicting_addition(rule_storage):
    from app.agents.contracts import AgentError, checked_draft
    from app.agents.preview import CandidatePreview
    context, soup, rules, body = scope()
    draft = checked_draft({**body, "operation": "add", "targetRuleDigest": None, "answer": "是"})
    with pytest.raises(AgentError) as caught:
        CandidatePreview(draft, context=context, soup=soup, rule_snapshot=rules)
    assert caught.value.code == "agent_candidate_conflict"
