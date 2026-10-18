"""Authoritative decisions, not display-text or provider-controlled permissions."""
import pytest
from pydantic import ValidationError

from app import schemas


def result(**changes):
    return schemas.HostResult(**{
        "kind": "answer", "answer": "是", "chargeable": True,
        "source": "deterministic", "reply": "是", **changes,
    })


@pytest.mark.parametrize("answer", ["是", "不是", "是也不是", "算是", "与此无关"])
def test_five_class_answers_are_explicit_and_immutable(answer):
    decision = result(answer=answer, reply="🤖 display is not authority")
    assert decision.answer == answer
    assert decision.chargeable is True
    assert decision.kind == "answer"
    with pytest.raises(ValidationError):
        decision.chargeable = False


@pytest.mark.parametrize("changes", [
    {"answer": "不知道"}, {"answer": None}, {"chargeable": False},
    {"chargeable": 1}, {"errorCode": "model_output_invalid"},
    {"kind": "reminder", "answer": "是", "chargeable": False},
    {"kind": "reminder", "answer": None},
    {"kind": "system_error", "answer": None, "chargeable": False},
    {"kind": "system_error", "answer": None, "errorCode": "model_timeout"},
    {"kind": "win", "answer": "是"}, {"extraPermission": True},
])
def test_invalid_business_combinations_fail_closed(changes):
    with pytest.raises(ValidationError):
        result(**changes)


def test_reminder_error_and_win_are_distinct():
    reminder = result(kind="reminder", answer=None, chargeable=False, source="flow", reply="提醒")
    error = result(kind="system_error", answer=None, chargeable=False, source="llm",
                   errorCode="model_output_invalid", reply="暂时不可用")
    win = result(kind="win", answer=None, reply="通关")
    assert not reminder.chargeable and reminder.errorCode is None
    assert error.answer is None and error.errorCode == "model_output_invalid"
    assert win.kind == "win" and win.answer is None
    assert reminder.evidenceIds == ()
    assert reminder.versions.engineVersion


@pytest.mark.parametrize("payload", [
    {"answer": "不知道", "reasoning": "uncertain"},
    {"answer": "是", "reasoning": "fixture", "chargeable": True},
    {"answer": "是", "reasoning": "fixture", "source": "deterministic"},
    {"answer": "是", "reasoning": 42},
])
def test_provider_cannot_supply_business_fields_or_unknown_answers(payload):
    with pytest.raises(ValidationError):
        schemas.HostJudgment.model_validate(payload)
