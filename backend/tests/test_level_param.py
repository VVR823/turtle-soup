# -*- coding: utf-8 -*-
"""难度参数（level）校验回归测试。

背景：旧实现 `if not soup.unlimited and req.level in LEVEL_KEYS and soup.difficultyLimits`
在 level 不在白名单时，会把 question_limit 留在 None（=不限次）。
于是只要直接访问 `/game/{id}`（不带 ?level=）或把参数改成 `?level=abc`，
就能绕开提问次数限制、无限提问。

修复后：缺省或非法一律回退到最严格档 xuermu，绝不放开成不限次（fail-closed）。
"""
import pytest

from app.soups import SEED_SOUPS


def _create_limit(client, soup_id: str, level=None):
    """创建一个会话并返回 questionLimit（不传 level 时 body 里完全不带该字段）。"""
    body = {"soupId": soup_id}
    if level is not None:
        body["level"] = level
    r = client.post("/api/chat", json=body)
    assert r.status_code == 200, r.text
    return r.json()["questionLimit"]


@pytest.mark.parametrize(
    "level,expected",
    [("xuermu", 35), ("baozi", 40), ("tianyi", 45)],
)
def test_level_valid_values(client, level, expected):
    """白名单内的三档难度应各自取到对应次数（xin 汤：35/40/45）。"""
    assert _create_limit(client, "xin", level) == expected


@pytest.mark.parametrize("bad", ["abc", "", "XUERMU", "tianyi ", "999", "xuermu,baozi"])
def test_invalid_level_falls_back_to_strictest(client, bad):
    """关键回归：非法 level 必须回退到最严格档(35)，而不是变成不限次(None)。"""
    limit = _create_limit(client, "xin", bad)
    assert limit == 35, f"level={bad!r} 应回退到 35，实际 {limit}"


def test_missing_level_falls_back_to_strictest(client):
    """完全不传 level（=直接访问 /game/{id}）同样必须回退到最严格档。"""
    assert _create_limit(client, "xin", None) == 35


def test_unlimited_egg_soup_unaffected(client):
    """彩蛋汤 unlimited=True，不受难度兜底影响，仍为不限次(None)。"""
    assert _create_limit(client, "xinshijie", "abc") is None
    assert _create_limit(client, "xinshijie", None) is None


def test_all_limited_soup_question_limits_are_multiples_of_five():
    invalid = {
        soup["id"]: soup["difficultyLimits"]
        for soup in SEED_SOUPS
        if not soup.get("unlimited")
        and any(limit % 5 for limit in soup["difficultyLimits"].values())
    }
    assert invalid == {}
