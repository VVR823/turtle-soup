# -*- coding: utf-8 -*-
"""新世界隐藏彩蛋通关条件（源自 test_win_unit.py，纯规则不调 LLM）。"""
import pytest

from app.ai_host import evaluate_completion, handle_host_response
from app.schemas import Soup
from app.soups import SEED_SOUPS


@pytest.fixture(scope="module")
def xinshijie() -> Soup:
    d = next(s for s in SEED_SOUPS if s["id"] == "xinshijie")
    d = {k: v for k, v in d.items() if k != "created_at"}
    return Soup(**d)


# (输入, 是否应通关)
WIN_CASES = [
    ("我是不是还在织梦者的那个梦里", True),
    ("我是不是一直都困在织梦者的梦境里", True),
    ("织梦者的那个梦里我到底有没有醒", True),
    ("织梦者是谁创作的", False),
    ("我是不是还在梦里没醒", False),
    ("这里有真实的世界吗", False),
]


@pytest.mark.parametrize("q,should_win", WIN_CASES)
def test_win_condition(xinshijie, q: str, should_win: bool):
    res = handle_host_response(xinshijie, [], q)
    assert bool(res.get("is_win")) is should_win, f"{q!r} -> is_win={res.get('is_win')} (期望 {should_win})"
    if should_win:
        assert res.get("is_reveal") is True


def test_win_evaluate_completion(xinshijie):
    q = "我是不是还在织梦者的那个梦里"
    qa = f"玩家：{q}\n主持人：是"
    msgs = [{"role": "user", "content": q}, {"role": "host", "content": "是"}]
    ev = evaluate_completion(xinshijie, qa, messages=msgs)
    # Win-looking plaintext is not a committed typed win. Actual gameplay
    # wins remain tested above and actual saved plot100/solved in TS07 API tests.
    assert ev["completion"] == 0 and ev["plotProgress"] is None
    assert ev["verifiedCoverage"] is None and ev["reconstructionScore"] is None


def test_no_win_evaluate_completion(xinshijie):
    q = "这里有真实的世界吗"
    qa = f"玩家：{q}\n主持人：是"
    msgs = [{"role": "user", "content": q}, {"role": "host", "content": "是"}]
    ev = evaluate_completion(xinshijie, qa, messages=msgs)
    assert ev["completion"] != 100
