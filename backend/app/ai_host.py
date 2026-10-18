"""AI 主持人核心逻辑（平移自前端 src/lib/ai-host.ts，并用 LangChain 重写 LLM 调用层）。

流程：独立游戏流程 → 完整范围、来源绑定的规则 → 是否类提醒 → 上下文模型。
候选检索、宽正则和相似度不再拥有在线答案权限。

复盘评估目前使用确定性规则；严格评分与完整结果快照由 TS-07 完成。
"""
import os
import re
import random
import time
from typing import List, Optional

from .prompts import HOST_SYSTEM_PROMPT
from .schemas import Soup, ConfusionPoint, Checkpoint, HostResult, HostVersions, HOST_ENGINE_VERSION
from . import rag  # legacy diagnostics only; not online answer authority


# ===================== LLM 客户端（LangChain ChatOpenAI） =====================
def _get_llm(max_tokens: int = 50):
    """Legacy injected-model access only; real calls must use the owned gateway."""
    from .runtime import get_runtime
    runtime = get_runtime()
    if runtime.model is not None:
        return runtime.model
    raise RuntimeError("Legacy real model access is disabled; use the owned model gateway")


# ===================== 是否类检测 =====================
def is_yes_no_question(question: str) -> bool:
    """
    判断玩家问题是否为可用"是/不是"回答的封闭式问题。

    核心原则：
    1. 先识别强是否标志（是不是/是否/有没有/对不对 等），可出现在句中任意位置。
    2. 再排除明确的开放式疑问词（什么/谁/为什么/怎么/多少 等）。
    3. 句末"吗/么"是兜底信号，但"什么/怎么/为什么/这么/多么"里的"么"不算。
    """
    q = question.strip()

    # 强是否标志：出现在句中任意位置都应视为是否类
    strong_anywhere = [
        r"是不是",
        r"是否",
        r"有木有",
        r"有没有",
        r"能不能",
        r"可不可以",
        r"能否",
        r"会不会",
        r"是不是",  # 重复 intentionally：确保优先级最高
    ]
    for pat in strong_anywhere:
        if re.search(pat, q):
            # 但如果是"为什么...是不是..."这种以"为什么"主导的，仍按开放式处理
            if re.search(r"为什么|为何|为啥", q):
                return False
            return True

    # 句首是否词：是不是/是否/有没有/是/不是/有/没有/能/不能/会/不会...
    if re.search(r"^(有|没有|是否|是不是|能不能|可不可以|会不会|能否|可以|会|是|不是|没|不|对|错)", q):
        return True

    # 明确的开放式疑问词 → 非是否类（优先于句末"吗/么"兜底）。
    # 例："我还有什么没答完的吗"含"什么"，本质是信息追问，不能回答"是/不是"。
    non_yes_no_keywords = [
        "什么", "谁", "哪个", "哪些", "哪里", "去哪", "为什么", "怎么",
        "如何", "为啥", "多少", "几个", "多久", "介绍", "告诉", "详细", "具体",
        "描述", "说说", "讲讲", "解释",
    ]
    for kw in non_yes_no_keywords:
        if kw in q:
            return False

    # 海龟汤玩家也会直接陈述时间存在关系来请求确认，不一定带“吗”。
    if re.search(r"(?:还|仍)?存在于", q) and len(q) <= 30:
        return True

    # 句末语气词：吗 / 么（排除"什么/怎么/为什么/这么/多么"——已由上方处理）
    if re.search(r"吗\s*[？?！!]?\s*$", q):
        return True
    if re.search(r"(么)\s*[？?！!]?\s*$", q) and not re.search(r"(什|怎|为|这|多)么", q):
        return True

    # 句末"对吧/对吗"
    if re.search(r"(对吗|对吧|对不)\s*[？?！!]?\s*$", q):
        return True

    # 确认式陈述：含"所以/因此/也就是说"等总结词，或长陈述（玩家在复述推理、请求主持人确认）
    if re.search(r"所以|因此|也就是说|也就是|换言之|对吗|是吧|对吧|没错吧|对不对", q):
        return True
    if len(q) >= 25 and re.search(r"[，。,.]", q):
        return True

    # 兜底：带问号的一般视为是否类；过长且无标点的不做硬性判否
    if re.search(r"[？?]", q):
        return True

    # 玩家断言式"A是B"（无"吗/么"等疑问词、无开放式疑问词、不以句号/语气词结尾）
    # 海龟汤中玩家常以此寻求主持人确认，按是否类处理（如"他们俩是同时在台上"）
    if ("是" in q) and ("吗" not in q) and ("么" not in q) and ("？" not in q) and ("?" not in q) \
            and not any(kw in q for kw in non_yes_no_keywords) \
            and not q.endswith(("。", "！", "呢", "啊", "吧", "的", "了")) \
            and len(q) <= 30:
        return True

    return False


# ===================== 关系型/象征型问题检测 =====================
_RELATIONSHIP_KEYWORDS = [
    "联想到", "想到", "联想", "象征", "代表", "意味着", "意味",
    "因为", "所以", "导致", "原因是", "来源于", "来自", "归因", "暗示", "隐喻", "寓意",
]


def is_relational_question(question: str) -> bool:
    """检测是否在问关系/因果/象征/联想。这类问题不适合走 RAG 关键词匹配，应交 LLM 语义判断。"""
    return any(kw in question for kw in _RELATIONSHIP_KEYWORDS)


# ===================== 身份归属/实体判断检测 =====================
_IDENTITY_PATTERNS = [
    # "X 是 Y 吗" / "X 是不是 Y" / "X 是 Y 还是 Z"
    r"^.+是.+吗",
    r"^.+是不是.+",
    r"^.+是.+还是.+",
    # "X 的身份是 Y 吗"
    r"身份是",
    r"(.+)是(.+)的人",
    # "尸体是 X 吗" / "那个人是 X 吗"
    r"尸体是",
    r"人是",
    r"那个人是",
    r"那个.+是",
]


def is_identity_question(question: str) -> bool:
    """检测是否在问'某个具体实体 X 的身份/归属是不是 Y'。

    这类问题不能靠 RAG 关键词匹配（容易因问题里出现'妻子''尸体'等词就误命中），
    必须交给 LLM 结合完整汤底和 truth items 做事实定位。
    """
    q = question.strip()
    # 强模式：X 是 Y 吗 / X 是不是 Y / X 是 Y 还是 Z
    if re.search(r"^.+是[^吗]*吗", q) and not re.search(r"^(有|没有|是否|能不能|可不可以|会不会|能否|可以|会|是|不是|没|不|对|错)", q):
        return True
    if re.search(r"^.+是不是[^吗]*", q):
        return True
    if re.search(r"^.+是[^还是]*还是", q):
        return True
    if re.search(r"身份是", q):
        return True
    # 明确归属：尸体/人/东西/那个 + 是
    if re.search(r"(尸体|人|东西|那个|这个).{0,5}是", q):
        return True
    return False


def format_yes_no_reminder(question: str) -> str:
    reminders = [
        '🤔 这个问题我没法用"是"或"不是"回答哦。试试改成："有XX吗？""是XX吗？"',
        '🎯 请用我能用"是"或"不是"回答的方式来提问~ 比如："存在XX吗？""和XX有关吗？"',
        '⚠️ 我只能回答"是/不是/是也不是/算是/与此无关"。把你的问题拆成小问题试试？',
    ]
    q = question.strip()
    if re.search(r"为什么|怎么|如何", q):
        return '🤔 "为什么/怎么样"的问题我没法直接回答。你可以试着拆成多个"是否"问题来推理，比如："是因为XX吗？""和XX有关吗？"'
    if re.search(r"什么|谁|哪里|去哪", q):
        return '🎯 直接问"是什么/是谁"就剧透啦！试试从侧面提问："有XX这个东西吗？""XX在汤里出现吗？""和XX有关吗？"'
    if re.search(r"多少|几个|介绍|告诉", q):
        return '⚠️ 这种问题等于让我直接给答案呢😅 换个方式问："存在XX吗？""和XX有关吗？"'
    return random.choice(reminders)


# ===================== 游戏流程/元问题兜底 =====================
_META_PROGRESS_PATTERNS = [
    r"还有.*没答完",
    r"还有.*没问",
    r"还缺.*什么",
    r"还差.*什么",
    r"遗漏.*什么",
    r"漏掉.*什么",
    r"有什么.*没答",
    r"我答.*多少",
    r"完成.*多少",
    r"进度.*多少",
]


def is_meta_progress_question(question: str) -> bool:
    """检测玩家是否在问本局进度/遗漏要点等元问题。这类问题不能回答"是/不是"。"""
    return any(re.search(p, question) for p in _META_PROGRESS_PATTERNS)


def format_progress_hint(soup: Soup, history: List[dict], *, versions: HostVersions | None = None) -> str:
    """只报同一严格计分器的汇总进度，不在游戏中泄露要点或证据。"""
    from .scoring import ConfirmedTurn
    if versions is None or versions.puzzleVersion == "unversioned":
        return '🎯 这份历史没有可核验的计分记录，完成度暂不能确认；还原程度尚未独立评估。可以继续提问或点「🏁 揭晓答案」。'
    turns = tuple(message["confirmedTurn"] for message in history
                  if isinstance(message.get("confirmedTurn"), ConfirmedTurn))
    result = evaluate_completion(soup, "", turns=turns, versions=versions)
    plot = (f' 剧情进度 {result["plotProgress"]}%（非还原评分）。' if result["plotProgress"] is not None else '')
    return (f'🎯 已确认事实覆盖（完成度）{result["verifiedCoverage"]}%。'
            f'还原程度尚未独立评估。{plot}可以继续提问，或点「🏁 揭晓答案」对照汤底。')


_REVEAL_KEYWORDS = [
    "汤底", "真相", "完整答案", "最终答案", "标准答案", "正确答案是",
    "我揭晓", "公布答案", "直接告诉我", "给我答案",
]


def looks_like_reveal_attempt(question: str) -> bool:
    """检测玩家是否把完整推理/汤底直接发在聊天框里（而非点击揭晓答案按钮）。

    判定标准：
    -  explicitly 提到"汤底/真相/答案"等关键词；
    -  或文本很长（>=60 字）且包含多个完整分句，更像是在复述故事而非提问。
    """
    q = question.strip()
    if any(kw in q for kw in _REVEAL_KEYWORDS):
        return True
    # 长文本 + 多个分句 => 大概率是完整推理/汤底
    if len(q) >= 60 and sum(1 for c in q if c in "，。,；;") >= 2:
        return True
    return False


def format_reveal_reminder() -> str:
    return '🤔 你这段看起来像是完整推理/汤底呢。请点击左侧「🏁 揭晓答案」按钮提交，我会评估完成度并公布汤底~'


# ===================== 易错点确定性兜底 =====================
# 以下文本/宽匹配工具仅保留给旧诊断与评分兼容，不参与在线确定性回答。
# 在线上下文由 host_context 保留完整汤底与有界完整候选证据；
# 玩家反馈发布/来源审核由 TS-10 完成，不把旧规则文本当独立人工质量证明。
AUTO_CP_PROMPT_LIMIT = 60


def build_confusion_text(soup: Soup) -> str:
    cps = soup.confusionPoints or []
    if not cps:
        return "（无）"
    # 区分手写易错点（作者精心设计，全保留）与自动合并规则（note 以「玩家反馈 #」开头）
    manual = [c for c in cps if not (c.note and c.note.startswith("玩家反馈 #"))]
    auto = [c for c in cps if c.note and c.note.startswith("玩家反馈 #")]
    # 自动规则按注入顺序（文件追加 = 时间序），保留最近 AUTO_CP_PROMPT_LIMIT 条
    auto = auto[-AUTO_CP_PROMPT_LIMIT:] if len(auto) > AUTO_CP_PROMPT_LIMIT else auto
    selected = manual + auto
    return "\n".join(
        f"问：「{c.q}」→ 答：「{c.a}」{('（' + c.note + '）') if c.note else ''}" for c in selected
    )


def build_symbol_text(soup: Soup) -> str:
    """把汤底的关键意象与真实含义格式化成文本，注入 LLM 上下文。"""
    mappings = soup.symbolMappings or []
    if not mappings:
        return "（无）"
    lines = []
    for m in mappings:
        line = f"- 「{m.symbol}」的真实含义：{m.meaning}"
        if m.note:
            line += f"（注意：{m.note}）"
        lines.append(line)
    return "\n".join(lines)


def build_truth_text(soup: Soup) -> str:
    """把汤底关键事实（Truth Items）格式化成 LLM 可检索的清单。"""
    items = soup.truthItems or []
    if not items:
        return "（无预抽取事实，请自行从完整汤底中提取）"
    lines = []
    for idx, item in enumerate(items, 1):
        line = f"{idx}. 「{item.subject}」{item.relation}「{item.object}」"
        if item.evidence:
            line += f"\n   依据：{item.evidence}"
        if item.confidence and item.confidence != "high":
            line += f"（确定性：{item.confidence}）"
        lines.append(line)
    return "\n".join(lines)


def _pattern_literal_len(pat: str) -> int:
    """统计正则中"字面字符"数量（忽略 .*+?|()[]{} 等元字符与转义序列）。

    用于衡量该正则的"具体程度"：字面关键词越多，越是针对某个具体问题的精确判定。
    例：'玉佩.*自己' 字面 4；'06年.*触碰.*玉佩' 字面 7 —— 后者更具体，应优先命中。
    """
    specials = set(".*+?|()^{}$")  # 注意：反斜杠单独处理
    count = 0
    i = 0
    n = len(pat)
    while i < n:
        ch = pat[i]
        if ch == '\\':  # 跳过转义序列（如 \d \s）
            i += 2
            continue
        if ch == '[':  # 跳过字符类 [...] 内部（非字面）
            j = pat.find(']', i)
            i = n if j == -1 else j + 1
            continue
        if ch == '{':  # 跳过量词 {...} 内部（如 {0,4} 的 0,4 非字面）
            j = pat.find('}', i)
            i = n if j == -1 else j + 1
            continue
        if ch == '(':  # 跳过分组/前后向断言 (...) 内部（非字面匹配文本）
            j = pat.find(')', i)
            i = n if j == -1 else j + 1
            continue
        if ch in specials:
            i += 1
            continue
        count += 1
        i += 1
    return count


def split_clauses(question: str) -> list[str]:
    """按中文/英文标点把长句拆成独立分句，避免正则跨分句误抓。"""
    clauses = [c.strip() for c in re.split(r"[，。,；;、]", question) if c.strip()]
    return clauses if clauses else [question]


def is_negative_statement(clause: str) -> bool:
    """判断玩家分句是否是否定陈述（如"X不是Y""X不存在"），而非疑问/反问/强调转折。

    用于把易错点的"问题答案"转换为"对玩家陈述的判断"：
    - 玩家说"幽灵不是真幽灵"，等价于问"幽灵是真的幽灵吗→不是"，但玩家陈述本身是对的，应回"是"。

    排除以下"强调性转折"，避免把"是A而不是B"误判为否定取反：
    - "是A而不是B" / "并不是A而是B" / "不是A而是B"：核心在肯定A，不在否定整个命题。
    """
    q = clause.strip()
    # 显式否定复合词（不含"不是"：避免把"是不是存在"里的"不是"误判为否定）
    strong_neg = re.search(r"不存在|没有|没|并非|未(?:曾|来)?[^，。,；;、]{0,2}(?:是|有)", q)
    # 疑问/反问结构：普通疑问（不含否定复合词）不按否定陈述取反；
    # 但"是不是不存在/是不是没有X"这类**否定疑问句**（疑问词+实体否定）仍需取反——
    # 例：CP"嫂子真实存在吗→不是"（嫂子不存在），玩家问"嫂子是不是不存在"应确认"是"。
    if re.search(r"[吗？?]$", q) or re.search(r"是不是|是否|有没有|有木有|能否|会不会|能不能|可不可以|对吗|对吧", q):
        if not strong_neg:
            return False
    # 强调转折结构：整体是肯定判断，不按否定取反
    if re.search(r"是[^，。,；;、]*而不是", q) or re.search(r"(?:并?非|不)[^，。,；;、]*而是", q):
        return False
    # 显式否定词
    if re.search(r"不是|没有|不存在|并非|未.{0,3}(?:是|有)|无.{0,3}(?:人|物|关)|非.{0,3}(?:常|常)?真|假的", q):
        return True
    return False


def effective_answer_for_clause(cp: ConfusionPoint, clause: str) -> str:
    """把易错点标答转换为对该分句陈述的判断。

    仅对二元答案"是"/"不是"做否定取反； nuanced 答案保持原样。
    """
    a = cp.a
    if a not in ("是", "不是"):
        return a
    if not is_negative_statement(clause):
        return a
    # 若易错点问题原文本身就用否定问法（如"10月4号没有日记是因为…吗"），
    # 标答已按否定语义写好；玩家复述同一否定表述时不翻答案，避免双重取反。
    cq = cp.q or ""
    if any(neg in cq for neg in ("没有", "不是", "不存在", "没")):
        return a
    return "不是" if a == "是" else "是"


def _cp_targets_whole_question(cp: ConfusionPoint, question: str) -> bool:
    """易错点的手写问题原文（cp.q）与玩家整句高度重合 → 该易错点就是针对整句的确定性判定。

    场景：旅馆等汤的易错点 q 字段就是完整问题原文（如"女孩的亲吻是在向我传递一种信号吗"），
    但 match 正则只匹配句子片段（如"传递.*信号"），导致复合陈述分支误判为
    "命中 1 个'不是'易错点 → 强制是也不是"，把确定性答案改坏。
    若 cp.q 与整句一致/互含/高度相似，说明作者已为该句锁定答案，直接采用。
    """
    q = question.strip()
    cq = (cp.q or "").strip()
    if not cq:
        return False
    if cq == q or cq in q or q in cq:
        return True
    return rag.calculate_similarity(q, cq) >= 0.85


def _cp_match_guard(cp: ConfusionPoint, clause: str, m) -> bool:
    """防「QA全覆盖」批量 CP 的宽 match 正则误命中。

    背景：批量灌入的 CP 常用 2-4 字短词做 match（如"人鱼""拐卖""本格"），
    会命中任何含该词的无关问题（实测"美人鱼是谁"误命中"这是变格吗"的 CP）。

    闸门规则（仅对短片段命中生效）：
    - 命中片段较长（>=4 字）→ 可信，放行；
    - CP.q 完整问法与玩家整句语义相似（>=0.3）或互相包含 → 放行；
    - 否则视为误命中，跳过该 CP（交给后续 RAG/LLM，避免系统性答错）。
    """
    cq = (cp.q or "").strip()
    q = clause.strip()
    span_len = (m.end() - m.start()) if m else 0
    if span_len >= 4:
        return True
    if len(cq) < 6 or len(q) < 4:
        return True
    if cq in q or q in cq:
        return True
    return rag.calculate_similarity(q, cq) >= 0.3


def match_confusion_point(soup: Soup, question: str) -> Optional[ConfusionPoint]:
    """返回**最具体（字面关键词最多）正则命中**的易错点，而非第一个命中。

    根因修复：
    1. 旧实现遍历列表返回第一个命中的 confusionPoint，导致更宽泛的旧正则
       （如 '玉佩.*自己'）会截胡更精确的新正则（如 '06年.*触碰.*玉佩'），造成 43/46 题误答。
       改为对所有命中条目按正则"字面具体度"（字面字符数，其次匹配跨度）打分，取最高分者。
    2. 按分句拆分匹配，避免 '主角.*催眠师' 跨越顿号把"主角...妻子是催眠师"误抓成"主角是催眠师"。
    3. 短 match 命中但 CP 完整问法与问题语义无关时，跳过（防 QA 全覆盖宽正则误命中）。
    """
    cps = soup.confusionPoints or []
    best_cp: Optional[ConfusionPoint] = None
    best_score = (-1, -1)  # (字面长度, 匹配跨度)
    clauses = split_clauses(question)
    if not clauses:
        clauses = [question]
    for clause in clauses:
        for cp in cps:
            for pat in (cp.match or []):
                try:
                    m = re.search(pat, clause)
                except re.error:
                    continue
                if not m:
                    continue
                if not _cp_match_guard(cp, clause, m):
                    continue
                literal = _pattern_literal_len(pat)
                span = m.end() - m.start()
                score = (literal, span)
                if score > best_score:
                    best_score = score
                    best_cp = cp
    # 兜底：若没有任何正则命中，但某个易错点的问题原文与玩家整句高度相似（>=0.85），
    # 也视为命中。这对手写长问题原文（如旅馆"女孩的亲吻是在向我传递一种信号吗"）
    # 以及玩家反馈自动生成的 QA 对（q=玩家原问题）特别有效。
    if not best_cp:
        for cp in cps:
            if _cp_targets_whole_question(cp, question):
                best_cp = cp
                break
    return best_cp


# ===================== checkpoint 回复 =====================
def generate_reply_from_checkpoint(cp: Checkpoint) -> str:
    if cp.answer is True:
        return "是"
    if cp.answer is False:
        return "不是"
    return "与此无关"


# ===================== 复合陈述处理 =====================
def is_compound_statement(question: str) -> bool:
    """检测玩家是否把多个独立判断揉在一句话里（复合陈述）。

    复合陈述的典型特征：
    - 句子较长，且包含至少两个内部的分句分隔符；
    - 或使用两个及以上空格明确列出多个判断。

    注意：
    - 单个逗号常用于把主题和同一个判断隔开，不能据此判为复合陈述；
    - 单个空格（如"我 爸妈 妻子"这种列表写法）不视为复合分句，只有 2 个及以上空格才计入。
    """
    q = question.strip()
    if len(q) < 12:
        return False
    # 句末标点不是分句；只有多个内部分隔符才足以证明存在多个判断。
    body = q.rstrip("。；;，,、 ")
    sep_count = sum(1 for c in body if c in "，。,；;、")
    # 空格只有在出现 2 次及以上时才视为复合分隔（避免"我 爸妈 妻子"被误判）
    space_count = q.count(" ")
    if space_count >= 2:
        return True
    if sep_count >= 2:
        return True
    return False


def collect_confusion_matches(soup: Soup, question: str) -> list[tuple[ConfusionPoint, str]]:
    """收集所有命中的易错点及其对该分句陈述的有效答案（按分句拆分匹配，避免跨分句误抓）。"""
    out = []
    seen = set()
    clauses = split_clauses(question)
    if not clauses:
        clauses = [question]
    for clause in clauses:
        for cp in (soup.confusionPoints or []):
            if cp.q in seen:
                continue
            hit = False
            for pat in (cp.match or []):
                try:
                    m = re.search(pat, clause)
                    if m and _cp_match_guard(cp, clause, m):
                        hit = True
                        break
                except re.error:
                    continue
            # 兜底：CP 手写问题原文（cp.q）与整句一致/互含/高度相似 → 视为命中。
            # 修复：部分 CP 只有 q/a 没有 match 正则（如"送别"的脚步声问题），
            # 复合陈述分支此前只看 match 导致这类 CP 永远命中不了，走 LLM 兜底答错。
            if not hit and _cp_targets_whole_question(cp, clause):
                hit = True
            if hit:
                eff = effective_answer_for_clause(cp, clause)
                out.append((cp, eff))
                seen.add(cp.q)
    return out


def aggregate_confusion_replies(matches: list[tuple[ConfusionPoint, str]]) -> str:
    """对复合陈述，把多个易错点的标答聚合成一个整体回答。

    核心规则：玩家一句话里有对有错 → 必须回答「是也不是」。
    """
    if not matches:
        return ""
    answers = [a for _, a in matches]
    if len(set(answers)) == 1:
        return answers[0]
    pos = {"是", "算是"}
    neg = {"不是"}
    neu = {"是也不是"}
    has_pos = any(a in pos for a in answers)
    has_neg = any(a in neg for a in answers)
    has_neu = any(a in neu for a in answers)
    if has_neu or (has_pos and has_neg):
        return "是也不是"
    if has_pos:
        return "是"
    return "是也不是"


# ===================== 归一化主持人回复 =====================
def _normalize_reply(raw: str) -> str:
    reply = (raw or "").strip()
    # ① 是也不是（一真一假）——必须最前，因同时含"是"和"不是"
    if re.search(r"是也不是|既.*又.*|半对|对一半|一半对|有对有错|部分是|部分正确|部分对", reply):
        reply = "是也不是"
    # ② 算是（中心概念对、表述不严谨）——含"是"，需放在"是"之前
    elif re.search(r"算是|算吧|也算|大体|差不多|基本是|基本算|姑且算|勉强算|可以说|大体上|约等于|不太准确|表述不准|不严谨|说不太准|不太对但|大致", reply):
        reply = "算是"
    # ③ 是（不含"不是/否/不算"）
    elif "是" in reply and "不是" not in reply and "否" not in reply and "不算" not in reply:
        reply = "是"
    # ④ 不是 / 否 / 不对
    elif "不是" in reply or "否" in reply or "不对" in reply:
        reply = "不是"
    # ⑤ 与此无关（含无法判断 / 不知道 / 无关）
    elif "无关" in reply or "没关系" in reply or "不确定" in reply or "无法判断" in reply or "不知道" in reply:
        reply = "与此无关"
    else:
        reply = "与此无关"
    # 最终安全网
    STANDARD = ["是", "不是", "是也不是", "算是", "与此无关"]
    if reply not in STANDARD:
        reply = "与此无关"
    return reply


# ===================== 隐藏彩蛋通关条件 =====================
def check_win_condition(soup: Soup, text: str) -> Optional[str]:
    """检测玩家是否满足了 soup.win_condition 设定的通关条件。

    命中则返回通关祝贺语（str），未命中返回 None。
    win_condition 结构：
        {
            'must_include': ['织梦者'],                 # 必须出现的关键词（全部命中）
            'any_of': ['(还|仍).*梦', '梦.*织梦者'],     # 任一正则命中即满足第二条件
            'message': '🎉 通关！...'
        }
    """
    wc = getattr(soup, "win_condition", None)
    if not wc:
        return None
    t = (text or "").strip()
    if not t:
        return None
    for kw in (wc.get("must_include") or []):
        if kw not in t:
            return None
    any_of = wc.get("any_of") or []
    if any_of:
        hit = False
        for pat in any_of:
            try:
                if re.search(pat, t):
                    hit = True
                    break
            except re.error:
                continue
        if not hit:
            return None
    return wc.get("message")


# ===================== 精确元数据兼容入口 =====================
def match_supernatural_answer(soup: Soup, question: str) -> Optional[str]:
    """Specific presence/absence requires a specific structured source fact."""
    from .host_rules import presence_answer
    return presence_answer(soup, question)


def match_genre_answer(soup: Soup, question: str) -> Optional[str]:
    from .host_rules import genre_answer
    return genre_answer(soup, question)


def match_cast_count(soup: Soup, question: str) -> Optional[str]:
    """Total entity count only; subsets/conditions/other places defer."""
    from .host_rules import count_answer
    return count_answer(soup, question)


# ===================== 主入口：处理玩家消息 =====================
def _answer_result(answer: str, marker: str | None, *, display: str | None = None) -> HostResult:
    return HostResult(kind="answer", answer=answer, chargeable=True, source="deterministic",
                      reply=display or answer, matchedCheckpoint=marker)


def _reminder_result(reply: str, marker: str | None = None) -> HostResult:
    return HostResult(kind="reminder", chargeable=False, source="flow", reply=reply, matchedCheckpoint=marker)


def handle_host_response(
    soup: Soup,
    history: List[dict],
    user_question: str,
    *, versions: HostVersions | None = None, rule_snapshot=None,
) -> HostResult:
    from .host_evidence import validate_puzzle_snapshot
    from .question_normalization import NORMALIZATION_VERSION
    selected = versions or HostVersions()
    if (not isinstance(selected, HostVersions) or selected.engineVersion != HOST_ENGINE_VERSION
            or selected.normalizationVersion != NORMALIZATION_VERSION):
        raise ValueError("Unsupported host implementation version")
    if selected.puzzleVersion != "unversioned":
        # Validate actual source even on cache hits, before trusting its key.
        validate_puzzle_snapshot(soup, selected.puzzleVersion)
    options = {}
    if rule_snapshot is not None:
        from .rule_contract import verify_rule_snapshot
        options["rule_snapshot"] = verify_rule_snapshot(rule_snapshot, soup, selected)
    result = _handle_host_response(soup, history, user_question, versions=selected, **options)
    return HostResult.model_validate({**result.model_dump(), "versions": selected})


def _handle_host_response(soup: Soup, history: List[dict], user_question: str, *,
                          versions: HostVersions, rule_snapshot=None) -> HostResult:
    from .question_normalization import normalize_exact_question
    try:
        question_key = normalize_exact_question(user_question)
    except ValueError:
        # Punctuation-only input is an ordinary incomplete question, not a
        # provider/transport failure. Exact-key's strict pure API stays strict.
        return _reminder_result("🤔 请补充一个具体的判断问题，例如「小明是凶手吗？」；这次不扣次数。")
    if question_key in {"吗", "么", "吧", "对吗", "对吧", "是吗"}:
        return _reminder_result("🤔 请补充你想确认的事情，再用是否问法提问；这次不扣次数。")
    # 0. 隐藏彩蛋通关条件（最高优先级）：玩家同时提及关键设定即判定通关，
    # 直接返回祝贺语并标记 is_win，不再走 always_yes 的普通"是"。
    win_msg = check_win_condition(soup, user_question)
    if win_msg:
        return HostResult(kind="win", chargeable=True, source="deterministic", reply=win_msg,
                          matchedCheckpoint="win_condition")

    # 特殊汤：always_yes（彩蛋汤《新世界》）。
    # 玩家问什么，主持人都回答"是"，因为世界是被编造的想象空间；
    # 非是否类问题仍引导改问法（保持统一交互）。
    if soup.always_yes:
        if not is_yes_no_question(user_question):
            return _reminder_result(format_yes_no_reminder(user_question))
        hesitations = [
            "是",
            "是",
            "是",
            "……是",
            "嗯，是",
            "是。",
        ]
        return _answer_result("是", "always_yes", display=random.choice(hesitations))

    # 0. 游戏流程类消息兜底：先识别"完整推理/汤底直接发在聊天框"和"问进度/缺什么"元问题。
    # 这类消息不能也不应该用"是/不是"回答，且不应消耗提问次数。
    if looks_like_reveal_attempt(user_question):
        return _reminder_result(format_reveal_reminder(), "reveal_attempt_reminder")
    if is_meta_progress_question(user_question):
        return _reminder_result(format_progress_hint(soup, history, versions=versions), "progress_hint")

    # Only complete source-bound rules can answer. Uncertain scope is normal
    # model fallback, not malformed output or an unchargeable system error.
    from .host_rules import decide_deterministic, question_has_static_scope
    from .host_cache import HostCacheKey
    from .runtime import get_runtime
    cache = get_runtime().deterministic_host_cache
    key = HostCacheKey(soup.id, versions.puzzleVersion, versions.ruleVersion, versions.engineVersion,
                       versions.normalizationVersion, question_key)
    exact_rule = next((rule for rule in rule_snapshot.exactRules if rule.canonicalQuestionKey == question_key), None) \
        if rule_snapshot is not None else None
    if exact_rule is not None:
        from .baselines import digest
        marker = "rule1:" + digest(exact_rule.model_dump(mode="json"))
        hit = cache.get(key)
        # Even an old internal caller using r1 without its overlay cannot seed
        # an original-rule answer that overrides the subsequently loaded patch.
        if (hit is not None and hit.matchedCheckpoint == marker and hit.answer == exact_rule.answer
            and hit.evidenceIds == exact_rule.factIds):
            return hit
        result = HostResult(kind="answer", answer=exact_rule.answer, reply=exact_rule.answer,
            chargeable=True, source="deterministic", versions=versions, evidenceIds=exact_rule.factIds,
            matchedCheckpoint=marker, contextIndependent=True)
        cache.put(key, result)
        return result
    hit = cache.get(key) if question_has_static_scope(soup, user_question) else None
    if hit is not None:
        return hit
    decision = decide_deterministic(soup, user_question, history, versions=versions)
    if decision is not None:
        result = HostResult(kind="answer", answer=decision.answer, chargeable=True,
                            source="deterministic", reply=decision.answer, versions=versions,
                            evidenceIds=decision.evidenceIds, matchedCheckpoint=decision.ruleId,
                            contextIndependent=decision.contextIndependent)
        cache.put(key, result)
        return result

    if not is_yes_no_question(user_question):
        return _reminder_result(format_yes_no_reminder(user_question))
    is_compound = is_compound_statement(user_question)
    extra = None
    if is_compound:
        extra = (
            "【特别注意：玩家这句话包含多个独立判断（复合陈述）。"
            "如果其中有的判断正确、有的判断错误，或部分判断需要 nuanced 口径，"
            "你必须整体回答「是也不是」，禁止只抓住一个错误点就整体回答「不是」，"
            "也禁止因为'基本正确'就整体回答「是」。】"
        )
    llm_reply = call_llm(soup, history, user_question, extra_instruction=extra, versions=versions)
    return llm_reply


# ===================== LangChain LLM 判定 =====================
def call_llm(soup: Soup, history: List[dict], user_question: str, extra_instruction: Optional[str] = None,
             fallback_answer: Optional[str] = None, *, versions: HostVersions | None = None) -> HostResult:
    """Validate output explicitly; never turn a failure into an irrelevant fact.

    fallback_answer is retained only for the old call signature and is not used
    to disguise an unavailable or malformed provider result.
    """
    from .host_context import ContextLimitError, build_puzzle_context
    from .model_gateway import ModelFailure
    from .runtime import get_runtime
    from .request_lifecycle import cancellation_signal
    deadline = time.monotonic() + 45
    try:
        format_rule = ('\n只输出 JSON 对象，answer 只能为是、不是、是也不是、算是、与此无关；'
                       'reasoning 为不超过100字的短依据，不要输出其他字段或Markdown。')
        context = build_puzzle_context(soup=soup, system_prompt=HOST_SYSTEM_PROMPT + format_rule,
                                      question=user_question, history=history or [], extra_instruction=extra_instruction or "",
                                      puzzle_version=(versions.puzzleVersion if versions is not None
                                                      and versions.puzzleVersion != "unversioned" else None))
        judgment = get_runtime().get_model_gateway().invoke([
            {"role": "system", "content": context.system}, {"role": "user", "content": context.user},
        ], deadline=deadline, cancelled=cancellation_signal())
        return HostResult(kind="answer", answer=judgment.answer, chargeable=True,
                          source="llm", reply=judgment.answer)
    except ContextLimitError:
        code = "context_too_large"
    except ModelFailure as error:
        code = error.code
    return HostResult(kind="system_error", chargeable=False, source="llm", errorCode=code,
                      reply="🤖 主持人暂时无法给出可靠回答，请稍后重试，本次不扣提问次数。")


# ===================== 无模型调用的类型化复盘评估 =====================
def evaluate_completion(soup: Soup, qa_text: str, messages: Optional[List[dict]] = None, *,
                        turns=None, versions: HostVersions | None = None, excluded_legacy_count: int = 0) -> dict:
    """Typed authoritative scorer, or explicitly unverified legacy adapter.

    Display/player plaintext never creates a factual answer, turn or win.
    Neither coverage nor narrative unlock progress is reconstruction quality.
    """
    from .scoring import score_confirmed_coverage
    if turns is None:
        return {"completion": 0, "verifiedCoverage": None, "reconstructionScore": None,
                "scoreVersion": None, "plotProgress": None, "unknownTopics": [],
                "unlockThresholdReached": False, "keyPointsCovered": [], "keyPointsMissing": [],
                "evaluation": "这份文字记录没有可核验的主持人判定，不能据此确认事实覆盖；还原程度尚未独立评估。"}
    if versions is None:
        raise ValueError("Typed evaluation requires its pinned versions")
    scored = score_confirmed_coverage(soup, turns, versions=versions, excluded_legacy_count=excluded_legacy_count)
    total = len(scored.keyPointsCovered) + len(scored.keyPointsMissing)
    evaluation = (f"已确认事实覆盖 {scored.verifiedCoverage}%（{len(scored.keyPointsCovered)}/{total} 个已知计分要点）。"
                  if total else "没有可确认的计分要点，事实覆盖记为 0%。")
    evaluation += "这不代表你已还原故事，还原程度尚未独立评估；完整汤底供你对照回顾。"
    if scored.excludedLegacyCount:
        evaluation += f" 有 {scored.excludedLegacyCount} 条旧问答没有可核验判定，历史已保留但未计分。"
    if scored.unknownTopics:
        evaluation += f" 另有 {len(scored.unknownTopics)} 个未知要点，不纳入已知事实分母。"
    if scored.plotProgress is not None:
        evaluation += f" 剧情进度 {scored.plotProgress}%（非还原评分）。"
    return {"completion": scored.verifiedCoverage, "verifiedCoverage": scored.verifiedCoverage,
            "reconstructionScore": None, "scoreVersion": scored.scoreVersion, "plotProgress": scored.plotProgress,
            "unknownTopics": list(scored.unknownTopics), "keyPointsCovered": list(scored.keyPointsCovered),
            "keyPointsMissing": list(scored.keyPointsMissing), "unlockThresholdReached": scored.unlockThresholdReached,
            "evaluation": evaluation}
