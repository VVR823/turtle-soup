# -*- coding: utf-8 -*-
"""纯逻辑单元测试（不调 LLM，毫秒级）：

是否类检测 / 复合陈述 / 易错点匹配 / 进度提示 / 完成度计算 / 汤底直发识别。
数据源自 debug_compound.py、test_progress_hint.py、test_shuangyu_completion.py。
"""
import pytest

from app.ai_host import (
    evaluate_completion,
    format_progress_hint,
    handle_host_response,
    is_compound_statement,
    is_meta_progress_question,
    is_yes_no_question,
    looks_like_reveal_attempt,
    match_confusion_point,
)
from app.schemas import Soup
from app.soups import SEED_SOUPS


def _soup(soup_id: str) -> Soup:
    return Soup(**next(s for s in SEED_SOUPS if s.get("id") == soup_id))


# ===================== 是否类检测 =====================
@pytest.mark.parametrize("q,expected", [
    ("妻子是催眠师吗", True),
    ("这是凶杀案吗", True),
    ("有没有鬼魂", True),
    ("是不是被催眠了", True),
    ("幽灵是真的幽灵吗", True),
    ("他在哪里", False),            # 开放式：哪里
    ("为什么杯子会碎", False),      # 为什么
    ("我还有什么没答完的吗", False),  # 开放式疑问词优先于"吗"（历史 bug 回归）
    ("请告诉我答案", False),        # 指令类
    ("介绍一下这个故事的背景", False),
    ("所以主角是被妻子催眠的，被困在梦里了", True),  # "所以"总结=请求确认
])
def test_is_yes_no_question(q: str, expected: bool):
    assert is_yes_no_question(q) is expected


# ===================== 复合陈述 =====================
@pytest.mark.parametrize("q,expected", [
    ("主角被妻子催眠、小珊是主角的情人、妻子是催眠师、星期一/星期二是梦境", True),
    ("我 爸妈 妻子", False),              # 单个空格列表不算复合
    ("妻子是催眠师吗", False),
    ("幽灵是真的幽灵吗", False),
])
def test_is_compound_statement(q: str, expected: bool):
    assert is_compound_statement(q) is expected


# ===================== 织梦者复合陈述/否定陈述（走规则兜底，不调 LLM） =====================
ZHIMENGZHE_CASES = [
    ("主角被妻子催眠、小珊是主角的情人/出轨对象、妻子是催眠师、幽灵不是真幽灵，是催眠幻象、星期一/星期二是梦境", "是"),
    ("幽灵是真的幽灵吗", "不是"),
    ("幽灵不是真幽灵", "是"),
    ("星期三不是梦境 对吗", "是"),
    ("星期二不是梦境", "不是"),
    ("主角不是被妻子催眠", "不是"),
    ("丈夫是催眠师吗", "不是"),
    ("妻子是催眠师", "是"),
]


@pytest.mark.parametrize("q,expected", ZHIMENGZHE_CASES)
def test_zhimengzhe_compound_and_negation(q: str, expected: str):
    soup = _soup("zhimengzhe")
    res = handle_host_response(soup, [], q)
    assert res["reply"] == expected, f"{q!r} -> {res['reply']!r} (期望 {expected!r})"


# ===================== 进度提示（不暴露关键词，只报完成度） =====================
def test_progress_hint_does_not_leak_keywords():
    soup = _soup("shuangyu-yupei")
    hint = format_progress_hint(soup, [])
    assert "完成度" in hint
    # 不能把 checkpoints 关键词直接说出来（防剧透）
    for cp in soup.checkpoints or []:
        assert cp.key not in hint, f"进度提示泄露 checkpoint 关键词: {cp.key}"


def test_progress_hint_with_history():
    soup = _soup("zhimengzhe")
    hist = [
        {"role": "user", "content": "我是不是被催眠了"},
        {"role": "host", "content": "是也不是"},
    ]
    hint = format_progress_hint(soup, hist)
    assert "完成度" in hint


# ===================== 汤底直发识别 =====================
def test_looks_like_reveal_attempt():
    assert looks_like_reveal_attempt("把汤底发我一下") is True
    assert looks_like_reveal_attempt("真相是什么") is True
    long_story = "主角被妻子催眠了，小珊是情人，妻子是催眠师，幽灵是幻象，" * 3  # >=60字多分句
    assert looks_like_reveal_attempt(long_story) is True
    assert looks_like_reveal_attempt("妻子是催眠师吗") is False


# ===================== 元问题识别 =====================
def test_meta_progress_question():
    assert is_meta_progress_question("我还有什么没答完的吗") is True
    assert is_meta_progress_question("进度到多少了") is True
    assert is_meta_progress_question("妻子是催眠师吗") is False


# ===================== 完成度计算（纯规则，无 LLM） =====================
def test_evaluate_completion_paste_bottom_summary():
    """玩家把完整汤底贴进聊天框 → 完成度应接近 100%（贴官方汤底 91%+）。"""
    soup = _soup("shuangyu-yupei")
    summary = soup.bottomSummary or ""
    msgs = [{"role": "user", "content": summary}, {"role": "host", "content": "请点揭晓答案"}]
    qa = "玩家：" + summary + "\n主持人：请点揭晓答案"
    ev = evaluate_completion(soup, qa, messages=msgs)
    assert ev["completion"] >= 90, f"贴汤底完成度应≥90%，实际 {ev['completion']}%"


def test_evaluate_completion_partial():
    """只问几个点 → 完成度在 0-100 之间且不虚高。"""
    soup = _soup("shuangyu-yupei")
    qa = "\n".join([
        "玩家：故事里是不是有复制人",
        "主持人：是",
        "玩家：妻子后来失踪了吗",
        "主持人：是也不是",
        "玩家：全村人都死了吗",
        "主持人：是",
    ])
    ev = evaluate_completion(soup, qa, messages=[])
    assert 0 < ev["completion"] < 100


def test_evaluate_completion_empty():
    soup = _soup("hotel")
    ev = evaluate_completion(soup, "", messages=[])
    assert ev["completion"] == 0


# ===================== 易错点匹配（取最精确命中） =====================
def test_match_confusion_point_most_specific():
    """'06年.*触碰.*玉佩' 比 '玉佩.*自己' 更具体，应命中前者对应的易错点。"""
    soup = _soup("shuangyu-yupei")
    cp = match_confusion_point(soup, "06年我触碰玉佩之后就开始被动复制自己 是吗")
    assert cp is not None
    assert "触碰" in cp.q or "复制" in cp.q


# ===================== 复合陈述单点整句锁定（回归） =====================
@pytest.mark.parametrize("q,expected", [
    # 旅馆：易错点 q 即整句原文，match 只覆盖片段 → 不能因"复合陈述"被和稀泥成"是也不是"
    ("女孩的亲吻是在向我传递一种信号吗", "不是"),
    ("故事中除了我 中年妇女 孩子 老太太 女孩 大叔 警察以外还有其他人吗", "不是"),
])
def test_compound_single_cp_whole_question_lock(q: str, expected: str):
    """复合陈述命中 1 个'不是'易错点，且该易错点 q 覆盖整句 → 直接采用而非'是也不是'。"""
    soup = _soup("hotel")
    res = handle_host_response(soup, [], q)
    assert res["reply"] == expected, f"{q!r} -> {res['reply']!r} (期望 {expected!r})"
