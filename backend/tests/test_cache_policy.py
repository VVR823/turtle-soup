# -*- coding: utf-8 -*-
"""主持人回答缓存策略的回归测试。

背景（2026-09）：曾发现 LLM 兜底结果（matched_checkpoint=None）被跨会话缓存，
而 LLM 是带着本局历史判定的，同一句话在不同上下文下结论可能不同，导致串答。
修复后 `_cacheable_host` 只缓存『结果与本局历史无关』的确定性分支。
本测试锁定该策略，防止后续被改回去。
"""
from app.main import _cacheable_host


def _host(reply: str, checkpoint):
    return {"reply": reply, "matched_checkpoint": checkpoint}


def test_llm_fallback_not_cached():
    """LLM 兜底（无 checkpoint 命中）依赖本局历史，绝不能进缓存。"""
    assert _cacheable_host(_host("是", None)) is False
    assert _cacheable_host(_host("不是", None)) is False
    assert _cacheable_host(_host("是也不是", None)) is False


def test_deterministic_branch_cached():
    """确定性分支（易错点/复合/类型/人数/RAG 等）结果与历史无关，应进缓存。"""
    assert _cacheable_host(_host("是", "易错点:xxx")) is True
    assert _cacheable_host(_host("不是", "复合陈述聚合(2个易错点)")) is True
    assert _cacheable_host(_host("是", "类型判定(genre=本格)")) is True
    assert _cacheable_host(_host("是", "人数判定(castCount=3)")) is True
    assert _cacheable_host(_host("不是", "checkpoint_key")) is True
    assert _cacheable_host(_host("是", "always_yes")) is True


def test_reminder_prefix_cached():
    """非是否类/流程提醒（🤔/🎯/⚠️ 前缀）无历史依赖，可缓存。"""
    assert _cacheable_host(_host("🤔 这个问题我没法回答", None)) is True
    assert _cacheable_host(_host("🎯 请换个方式提问", None)) is True
    assert _cacheable_host(_host("⚠️ 请拆成小问题", None)) is True


def test_progress_hint_not_cached():
    """进度提示答案依赖本局历史，不能缓存。"""
    assert _cacheable_host(_host("🎯 当前完成度 40%", "progress_hint")) is False


def test_llm_error_not_cached():
    """LLM 报错（🤖 前缀）是临时故障，缓存会固化错误，不能缓存。"""
    assert _cacheable_host(_host("🤖 主持人走神了，请重新发送", None)) is False


def test_empty_reply_not_cached():
    """无回复内容的判定不进缓存。"""
    assert _cacheable_host({}) is False
    assert _cacheable_host({"reply": "", "matched_checkpoint": None}) is False
    assert _cacheable_host(None) is False
