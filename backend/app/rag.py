"""海龟汤 RAG 检索引擎（平移自前端 src/lib/rag.ts）。

核心逻辑：用户提问 → 语义匹配汤底的 checkpoints
→ 返回匹配的判定结果；未匹配则交给 LLM 判断。
生产环境可替换为 embedding 相似度，这里用关键词 + 编辑距离 + bigram 启发式。
"""
from dataclasses import dataclass
from typing import List, Optional

import re

from .schemas import Checkpoint, Soup


@dataclass
class MatchResult:
    match: bool = False
    checkpoint: Optional[Checkpoint] = None
    confidence: float = 0.0


def match_user_query(question: str, soup: Soup) -> MatchResult:
    q = normalize_question(question)

    ctrl = check_control_command(q)
    if ctrl is not None:
        return ctrl

    q_core = extract_core(q)
    best: MatchResult = MatchResult(match=False, confidence=0.0)
    for cp in soup.checkpoints:
        terms = [cp.key] + (cp.aliases or [])
        best_score_for_cp = 0.0
        for term in terms:
            score = calculate_similarity(q, term)
            # 核心词重叠：去掉疑问/判断停用词后，若问题核心与 checkpoint 核心互相包含，
            # 覆盖「X是真的吗」↔「X是否是真的」等口语变体（通用增强，对所有汤生效，
            # 不必为每个汤手工加同义匹配）。
            tc = extract_core(term)
            if q_core and tc and (q_core in tc or tc in q_core) and (
                max(len(q_core), len(tc)) >= 2 or q_core == tc
            ):
                score = max(score, 0.7)
            if score > best_score_for_cp:
                best_score_for_cp = score
        if best_score_for_cp > best.confidence:
            best = MatchResult(
                match=best_score_for_cp >= 0.45,
                checkpoint=cp,
                confidence=best_score_for_cp,
            )
    return best


# 疑问/判断停用词：提取核心实体时去除，让口语变体（"X是真的吗"）能匹配标准 checkpoint
_QUERY_STOPWORDS = [
    "是不是", "是否", "真的", "吗", "呢", "是", "不是", "有没有", "有", "没有",
    "那个", "这个", "之", "它", "他", "她", "被", "让", "给", "对", "和", "与",
    "在", "了", "啊", "呀", "哦", "干嘛", "怎么", "为什么", "什么", "谁",
    "存在", "出现", "关于", "有关", "涉及到", "问题", "事情", "情况",
]


def extract_core(text: str) -> str:
    """去除疑问/判断停用词，保留核心中文实体，用于口语变体匹配。"""
    t = text
    for w in sorted(_QUERY_STOPWORDS, key=len, reverse=True):
        t = t.replace(w, "")
    t = re.sub(r"[^一-鿿]", "", t)  # 只保留中文字符
    return t.strip()


def normalize_question(q: str) -> str:
    result = (
        q.strip()
        .lower()
        .replace("？", " ")
        .replace("?", " ")
        .replace("！", " ")
        .replace("!", " ")
        .replace("。", " ")
        .replace(".", " ")
        .replace("，", " ")
        .replace(",", " ")
        .replace("；", " ")
        .replace(";", " ")
        .replace("：", " ")
        .replace(":", " ")
        .replace("/", " ")
        .replace("\\", " ")
        .replace("[", " ")
        .replace("]", " ")
        .replace("(", " ")
        .replace(")", " ")
        .replace("<", " ")
        .replace(">", " ")
        .replace("{", " ")
        .replace("}", " ")
        .replace("-", " ")
        .replace("_", " ")
        .replace("@", " ")
        .replace("#", " ")
        .replace("$", " ")
        .replace("%", " ")
        .replace("^", " ")
        .replace("&", " ")
        .replace("*", " ")
        .replace("+", " ")
        .replace("=", " ")
        .replace("~", " ")
        .replace("`", " ")
        .replace('"', " ")
        .replace("'", " ")
        .replace("（", " ")
        .replace("）", " ")
    )
    result = " ".join(result.split())

    result = result.strip()
    if not result:
        result = "无关"
    return result


def check_control_command(q: str) -> Optional[MatchResult]:
    if re_search(r"猜出|猜到了|知道了|我猜|答案|谜底|真相", q):
        return MatchResult(match=False, confidence=1.0)
    if re_search(r"放弃|跳过|提示|不知道|不会|看答案|告诉我|揭密|曝光", q):
        return MatchResult(match=False, confidence=1.0)
    return None


def calculate_similarity(a: str, b: str) -> float:
    if a == b:
        return 1.0
    if a in b or b in a:
        return 0.9
    edit_dist = levenshtein_distance(a, b)
    max_len = max(len(a), len(b))
    edit_score = 1 - edit_dist / max_len if max_len else 0
    a_bigrams = get_bigrams(a)
    b_bigrams = get_bigrams(b)
    overlap = sum(1 for bg in a_bigrams if bg in b_bigrams)
    bigram_score = overlap / len(a_bigrams) if a_bigrams else 0
    return max(edit_score * 0.6 + bigram_score * 0.4, 0.0)


def levenshtein_distance(a: str, b: str) -> int:
    if not a:
        return len(b)
    if not b:
        return len(a)
    matrix = [[0] * (len(a) + 1) for _ in range(len(b) + 1)]
    for i in range(len(b) + 1):
        matrix[i][0] = i
    for j in range(len(a) + 1):
        matrix[0][j] = j
    for i in range(1, len(b) + 1):
        for j in range(1, len(a) + 1):
            if b[i - 1] == a[j - 1]:
                matrix[i][j] = matrix[i - 1][j - 1]
            else:
                matrix[i][j] = min(
                    matrix[i - 1][j - 1] + 1,
                    matrix[i][j - 1] + 1,
                    matrix[i - 1][j] + 1,
                )
    return matrix[len(b)][len(a)]


def get_bigrams(s: str):
    chars = list(s)
    return set("".join(p) for p in zip(chars[:-1], chars[1:]))


def re_search(pattern: str, text: str):
    try:
        return __import__("re").search(pattern, text) is not None
    except Exception:
        return False
