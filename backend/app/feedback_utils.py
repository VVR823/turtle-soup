"""反馈审批与自动合并相关的工具函数。

把标准化、match 正则生成等逻辑抽出来，供 main.py 与 scripts/merge_verified_qa.py 共用，
避免循环导入。
"""
from __future__ import annotations

import re
from typing import Optional


def normalize_expected_answer(ans: str) -> Optional[str]:
    """把玩家填写的自由文本正确答案，归一化为 5 种标准答案之一。

    归一化失败时返回 None，表示需要人工确认后再合并。
    """
    a = (ans or "").strip()
    if not a:
        return None
    # ① 是也不是
    if re.search(r"是也不是|半对|对一半|一半对|有对有错|部分是|部分正确|部分对", a):
        return "是也不是"
    # ② 算是
    if re.search(r"算是|算吧|也算|大体|差不多|基本是|基本算|姑且算|勉强算|可以说|大体上|约等于", a):
        return "算是"
    # ④ 不是 / 否
    if "不是" in a or a == "否" or a.startswith("否"):
        return "不是"
    # ③ 是（不含"不是/否"）
    if "是" in a:
        return "是"
    # ⑤ 与此无关 / 不确定
    if "无关" in a or "不确定" in a or "无法判断" in a or "不知道" in a:
        return "与此无关"
    return None


def _escape_regex_literal(text: str) -> str:
    """把普通文本转成正则字面量；保留中文、数字、字母，只转义元字符。"""
    return re.escape(text)


def build_match_patterns(question: str) -> list[str]:
    """从玩家问题自动生成用于 ConfusionPoint.match 的正则列表。

    策略：
    1. 提取核心中文实体（去除疑问/判断停用词）。
    2. 按字用窄通配连接，允许少量口语插入字。
    3. 若核心词 >= 4 字，额外生成前 3 个相邻 bigram 的灵活组合，增强问法变体覆盖。

    保守性（2026-09 修复）：
    - 字间通配从 `.{0,5}` 收紧为 `[^，。]{0,3}`（最多 3 字、且不跨分句），
      避免把「活/死/真/假/现在/亲」等**关键限定词**吞进通配而误匹配。
      例：注入规则「故事中还有其他人吗→是」若用 `.{0,5}` 会误吞掉
      「故事中除了我还有**其他活**人吗」里的“活”，把正确答案应为「不是」的问法
      错判成「是」。
    - 含强烈限定词（活/死/真/假/现在/曾经/第一 等）的问题，其核心词里该限定词
      必须原样保留（extract_core 不会删它们），靠窄通配保证不被跳过。

    注意：生成的正则仍偏“字面串匹配”，自动 QA 对只追加到 soup.confusionPoints
    末尾（手写 CP 的精确正则优先命中），避免自动规则截胡精心手写的规则。
    """
    from .rag import extract_core

    core = extract_core(question)
    if len(core) < 2:
        return []

    chars = list(core)
    # 窄通配：0~3 个非分句字符。可容忍口语插入（的/了/个/啊 等），
    # 但不足以吞掉「活/死/真」这类决定答案的限定词或跨分句。
    gap = r"[^，。！？!?；;、]{0,3}"
    char_pattern = gap.join(_escape_regex_literal(c) for c in chars)
    patterns = [char_pattern]

    # 相邻 bigram 组合（最多 3 个），覆盖词序变化（同样用窄通配）
    if len(chars) >= 4:
        bigrams = ["".join(chars[i : i + 2]) for i in range(len(chars) - 1)]
        selected = bigrams[:3]
        if selected:
            patterns.append(gap.join(_escape_regex_literal(bg) for bg in selected))

    return patterns
