# -*- coding: utf-8 -*-
"""主持人回答缓存策略的回归测试。

背景（2026-09）：曾发现 LLM 兜底结果（matched_checkpoint=None）被跨会话缓存，
而 LLM 是带着本局历史判定的，同一句话在不同上下文下结论可能不同，导致串答。
TS-06 只缓存完整版本绑定、来源证据和程序声明的纯规则结果。
本测试保留“LLM/上下文不能跨局缓存”的保护；展示标记本身不证明纯度。
"""
from app.main import _cacheable_host
from app.schemas import HostResult


def _host(reply: str, checkpoint, *, source=None, kind="answer"):
    return HostResult(kind=kind, answer=reply if kind == "answer" else None,
                      reply=reply, chargeable=kind == "answer",
                      source=source or ("deterministic" if checkpoint else "llm"),
                      matchedCheckpoint=checkpoint,
                      errorCode="model_unavailable" if kind == "system_error" else None)


def test_llm_fallback_not_cached():
    """LLM 兜底（无 checkpoint 命中）依赖本局历史，绝不能进缓存。"""
    assert _cacheable_host(_host("是", None)) is False
    assert _cacheable_host(_host("不是", None)) is False
    assert _cacheable_host(_host("是也不是", None)) is False


def test_deterministic_display_branch_alone_is_not_cache_authority():
    """旧展示字符串不能证明版本、证据或是否依赖历史；彩蛋永不缓存。"""
    for marker in ("易错点:xxx", "复合陈述聚合(2个易错点)", "类型判定(genre=本格)",
                   "人数判定(castCount=3)", "checkpoint_key", "always_yes"):
        assert _cacheable_host(_host("是", marker)) is False


def test_only_typed_versioned_pure_rule_is_cache_eligible():
    from .test_versioned_host_cache import pure
    assert _cacheable_host(pure()) is True
    assert _cacheable_host(pure(contextIndependent=False)) is False
    assert _cacheable_host(pure(matchedCheckpoint="always_yes")) is False


def test_reminders_not_cached_based_on_display_prefix():
    for reply in ("🤔 请换问法", "🎯 请换问法", "⚠️ 请换问法", "没有 emoji 的提醒"):
        assert _cacheable_host(_host(reply, None, source="flow", kind="reminder")) is False


def test_progress_hint_not_cached():
    """进度提示答案依赖本局历史，不能缓存。"""
    assert _cacheable_host(_host("🎯 当前完成度 40%", "progress_hint", source="flow", kind="reminder")) is False


def test_llm_error_not_cached():
    """LLM 报错（🤖 前缀）是临时故障，缓存会固化错误，不能缓存。"""
    for reply in ("🤖 请重试", "没有 emoji 的错误"):
        assert _cacheable_host(_host(reply, None, kind="system_error")) is False


def test_empty_reply_not_cached():
    """无回复内容的判定不进缓存。"""
    assert _cacheable_host({}) is False
    assert _cacheable_host({"reply": "", "matched_checkpoint": None}) is False
    assert _cacheable_host(None) is False
