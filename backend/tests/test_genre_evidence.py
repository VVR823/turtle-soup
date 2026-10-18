"""Genre is not every supernatural fact; precise negative metadata stays normal."""
import pytest

from app import ai_host
from app.schemas import Soup, TruthItem
from .test_semantic_rule_guards import run_host


def time_only():
    return Soup(id="synthetic", title="Synthetic", surface="这是一个穿越故事。", genre="变格",
                bottom="Synthetic: 故事有穿越，但没有魔法。其他超自然元素未确定。",
                truthItems=[TruthItem(subject="故事", relation="存在", object="穿越"),
                            TruthItem(subject="故事", relation="不存在", object="魔法")])


@pytest.mark.parametrize("question,expected", [("有魔法吗？", "不是"), ("没有魔法吗？", "是"),
                                               ("有穿越吗？", "是"), ("没有穿越吗？", "不是")])
def test_specific_supernatural_element_requires_specific_actual_fact(question, expected):
    assert ai_host.match_supernatural_answer(time_only(), question) == expected


def test_genre_label_alone_cannot_manufacture_an_unknown_ghost_fact():
    assert ai_host.match_supernatural_answer(time_only(), "有灵异事件吗？") is None


@pytest.mark.parametrize("question,expected", [("这是变格吗？", "是"), ("这不是变格吗？", "不是"),
                                               ("这不是本格吗？", "是"), ("没有变格元素吗？", "不是")])
def test_precise_genre_forms_respect_negation(question, expected):
    assert ai_host.match_genre_answer(time_only(), question) == expected


@pytest.mark.parametrize("question", ["这是变格，而且小明死了吗？", "如果小明死了，这是变格吗？"])
def test_genre_metadata_cannot_short_circuit_uncovered_claims(tmp_path, question):
    result, model = run_host(tmp_path, time_only(), question, answer="是也不是")
    assert result.kind == "answer" and result.source == "llm" and result.answer == "是也不是"
    assert len(model.calls) == 1


@pytest.mark.parametrize("question", ["如果有人离开，故事里只有3个人吗？", "旅馆里只有3个人吗？"])
def test_total_cast_metadata_is_not_an_unsupported_conditional_or_other_place_count(tmp_path, question):
    selected = time_only().model_copy(update={"castCount": 3})
    result, model = run_host(tmp_path, selected, question)
    assert result.kind == "answer" and result.source == "llm" and len(model.calls) == 1


@pytest.mark.parametrize("question,expected", [("故事里只有3个人吗？", "是"), ("故事里只有4个人吗？", "不是")])
def test_plain_total_count_retains_exact_numeric_behavior(tmp_path, question, expected):
    selected = time_only().model_copy(update={"castCount": 3})
    result, model = run_host(tmp_path, selected, question)
    assert result.kind == "answer" and result.answer == expected
    assert result.source == "deterministic" and result.evidenceIds and not model.calls


@pytest.mark.parametrize("confidence", ["medium", "low", None])
def test_uncertain_structured_presence_fact_is_not_an_authoritative_answer(confidence):
    selected = time_only().model_copy(update={"truthItems": [
        TruthItem(subject="故事", relation="存在", object="幽灵", confidence=confidence)]})
    assert ai_host.match_supernatural_answer(selected, "有幽灵吗？") is None


def test_opposite_presence_facts_defer_instead_of_first_record_wins():
    selected = time_only().model_copy(update={"truthItems": [
        TruthItem(subject="故事", relation="存在", object="幽灵"),
        TruthItem(subject="故事", relation="不存在", object="幽灵")]})
    assert ai_host.match_supernatural_answer(selected, "有幽灵吗？") is None
