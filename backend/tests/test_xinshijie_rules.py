# -*- coding: utf-8 -*-
"""新世界彩蛋规则（源自 tests/online/test_xinshijie.py）：不限次 + 是否类全答"是" + 非是否类引导。"""
from .conftest import make_session


def test_xinshijie_unlimited(client):
    """彩蛋汤应不限提问次数。"""
    r = client.post("/api/chat", json={"soupId": "xinshijie", "level": "tianyi"})
    assert r.status_code == 200, r.text
    assert r.json().get("questionLimit") is None


def test_xinshijie_yes_questions(client):
    """是否类问题一律回"是"（世界是被编造的想象空间）。"""
    sid = make_session(client, "xinshijie")
    for q in ["这是真实的世界吗", "你是我的妻子吗", "我死了吗", "我在做梦吗", "你是主持人吗"]:
        d = client.post("/api/chat", json={"sessionId": sid, "question": q}).json()
        reply = d.get("reply", "")
        assert "是" in reply and "不是" not in reply, f"{q!r} -> {reply!r}"


def test_xinshijie_open_questions_guided(client):
    """非是否类问题应引导改问法（🤔/🎯/⚠️ 开头），而非直接回答。"""
    sid = make_session(client, "xinshijie")
    for q in ["为什么", "这是哪里", "今天星期几"]:
        d = client.post("/api/chat", json={"sessionId": sid, "question": q}).json()
        reply = d.get("reply", "")
        assert reply.startswith(("🤔", "🎯", "⚠️")), f"{q!r} -> {reply!r}"


def test_xinshijie_reveal_returns_bottom(client):
    """揭晓评估应返回汤底。"""
    sid = make_session(client, "xinshijie")
    d = client.post("/api/evaluate", json={"sessionId": sid}).json()
    assert d.get("bottom"), "应返回汤底"
