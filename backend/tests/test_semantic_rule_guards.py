"""Shortcuts must cover the whole proposition, not a shared word/regex span."""
import importlib
import importlib.util

import pytest

from app import ai_host
from app.config import Settings
from app.runtime import Runtime, runtime_context
from app.schemas import Checkpoint, ConfusionPoint, HostVersions, Soup
from app.testing import FakeModel
from .test_host_evidence import pin


def authored_soup():
    return Soup(id="synthetic", title="Synthetic", surface="小明和小红在场。",
                bottom="Synthetic: 小明是凶手，小红不是凶手；其他数量/时间/条件并未确定。",
                checkpoints=[Checkpoint(key="小明是凶手", answer=True, aliases=["小明是凶手吗"])],
                confusionPoints=[ConfusionPoint(q="小明是凶手吗", a="是", match=["凶手"])])


def run_host(tmp_path, selected, question, *, answer="不是", history=None):
    model = FakeModel(answer=answer)
    active = Runtime(Settings.for_test(tmp_path), model=model)
    with runtime_context(active):
        try:
            result = ai_host.handle_host_response(selected, history or [], question)
        finally:
            if active.model_gateway is not None:
                active.model_gateway.close(wait_seconds=1)
    return result, model


@pytest.mark.parametrize("question,expected", [("小明是凶手吗？", "是"), ("小明不是凶手吗？", "不是")])
def test_same_named_subject_opposite_polarity_cannot_share_one_answer(tmp_path, question, expected):
    result, _ = run_host(tmp_path, authored_soup(), question)
    assert result.kind == "answer" and result.answer == expected


@pytest.mark.parametrize("question", [
    "小红是凶手吗？", "只有小明一个凶手吗？", "2006年小明是凶手吗？",
    "凶手有3个人吗？", "凶手有4个人吗？", "小明是凶手的儿子吗？",
    "小明是因为别人逼迫才成为凶手吗？", "小明是凶手意味着小红死亡吗？",
])
def test_changed_subject_quantity_time_condition_or_relation_is_not_a_partial_lock(tmp_path, question):
    result, model = run_host(tmp_path, authored_soup(), question)
    assert result.kind == "answer" and result.source == "llm"
    assert result.answer == "不是" and result.chargeable is True
    assert len(model.calls) == 1
    assert question in model.calls[0][1]["content"]


@pytest.mark.parametrize("question", [
    "小明是凶手，而且小红已经死了吗？",
    "如果今天没有下雨，小明是凶手吗？",
    "小明是凶手，但是故事一共有3个人吗？",
])
def test_one_supported_clause_never_proves_uncovered_compound_or_conditional(tmp_path, question):
    result, model = run_host(tmp_path, authored_soup(), question, answer="是也不是")
    assert result.kind == "answer" and result.source == "llm"
    assert result.answer == "是也不是" and len(model.calls) == 1


def test_weak_checkpoint_candidate_is_evidence_not_direct_answer(tmp_path):
    selected = authored_soup().model_copy(update={"confusionPoints": []})
    result, model = run_host(tmp_path, selected, "小明不是凶手吗？", answer="不是")
    assert result.answer == "不是"
    # Explicit signature/rule could legitimately decide this; a bare similarity
    # score cannot. Its evidence must be recorded if no model path was used.
    assert len(model.calls) == 1 or result.evidenceIds


@pytest.mark.parametrize("name,scripted", [("小明", "不是"), ("小红", "是")])
def test_same_exact_pronoun_question_in_opposite_histories_requires_context(tmp_path, name, scripted):
    selected = Soup(id="synthetic", title="Synthetic", surface="小明和小红。",
                    bottom="Synthetic: 小明活着，小红死了。",
                    checkpoints=[Checkpoint(key="小红死亡", answer=True, aliases=["他死了吗"])],
                    confusionPoints=[ConfusionPoint(q="他死了吗", a="是", match=["死"])])
    history = [{"role": "user", "content": f"下面我说的他指的是{name}，对吗？"},
               {"role": "host", "content": "是"}]
    result, model = run_host(tmp_path, selected, "他死了吗？", answer=scripted, history=history)
    assert result.kind == "answer" and result.source == "llm" and result.answer == scripted
    assert len(model.calls) == 1 and name in model.calls[0][1]["content"]


def test_named_whole_question_rule_has_real_pinned_evidence_not_display_marker(tmp_path):
    selected, version = pin(tmp_path, authored_soup())
    assert importlib.util.find_spec("app.host_rules") is not None, "Missing guarded decision interface"
    rules = importlib.import_module("app.host_rules")
    from app.host_evidence import build_evidence_catalog
    versions = HostVersions(puzzleVersion=version, ruleVersion="synthetic-rule")
    result = rules.decide_deterministic(selected, "小明是凶手吗？", [], versions=versions)
    assert result is not None and result.answer == "是" and result.contextIndependent is True
    assert result.scope == "whole_question" and result.ruleId
    actual = {r.id for r in build_evidence_catalog(selected, version)}
    assert result.evidenceIds and set(result.evidenceIds) <= actual


def test_contradictory_authored_sources_defer_instead_of_first_match_wins(tmp_path):
    selected = authored_soup().model_copy(update={"confusionPoints": [
        ConfusionPoint(q="小明是凶手吗", a="不是")]})
    result, model = run_host(tmp_path, selected, "小明是凶手吗？", answer="是也不是")
    assert result.source == "llm" and result.answer == "是也不是" and len(model.calls) == 1


def test_every_supported_compound_clause_has_source_evidence(tmp_path):
    selected = authored_soup().model_copy(update={"checkpoints": [
        Checkpoint(key="小明是凶手", answer=True), Checkpoint(key="小红是凶手", answer=False)]})
    result, model = run_host(tmp_path, selected, "小明是凶手，小红是凶手吗？")
    assert result.source == "deterministic" and result.answer == "是也不是"
    assert len(result.evidenceIds) >= 2 and not model.calls


def test_false_conjunction_does_not_prove_each_component_false(tmp_path):
    selected = authored_soup().model_copy(update={"checkpoints": [
        Checkpoint(key="小明是凶手，小红是凶手", answer=False)], "confusionPoints": []})
    result, model = run_host(tmp_path, selected, "小明是凶手吗？", answer="是")
    assert result.source == "llm" and result.answer == "是" and len(model.calls) == 1


def test_bare_keyword_checkpoint_alias_is_not_a_whole_question(tmp_path):
    selected = authored_soup().model_copy(update={"checkpoints": [
        Checkpoint(key="小明是凶手", answer=True, aliases=["凶手"])], "confusionPoints": []})
    result, model = run_host(tmp_path, selected, "凶手吗？")
    assert result.source == "llm" and len(model.calls) == 1


@pytest.mark.parametrize("question", ["她死了吗？", "这个人是凶手吗？", "之前小明是凶手吗？"])
def test_authored_reference_dependent_whole_questions_still_require_context(tmp_path, question):
    selected = authored_soup().model_copy(update={"confusionPoints": [
        ConfusionPoint(q=question, a="是")], "checkpoints": []})
    history = [{"role": "user", "content": "当前谈的是小红，对吗？"}, {"role": "host", "content": "是"}]
    result, model = run_host(tmp_path, selected, question, history=history)
    assert result.source == "llm" and result.answer == "不是" and len(model.calls) == 1


def test_first_person_authored_narrator_qa_cannot_override_player_rebinding(tmp_path):
    selected = authored_soup().model_copy(update={"surface": "我看见两个人。", "confusionPoints": [
        ConfusionPoint(q="我是凶手吗", a="是")], "checkpoints": []})
    history = [{"role": "user", "content": "现在我扮演小红，对吗？"}, {"role": "host", "content": "是"}]
    result, model = run_host(tmp_path, selected, "我是凶手吗？", history=history)
    assert result.source == "llm" and result.answer == "不是" and len(model.calls) == 1
