"""AI 主持人核心逻辑（平移自前端 src/lib/ai-host.ts，并用 LangChain 重写 LLM 调用层）。

流程（与前端行为一致）：
  0. 是否类检测（非是否类 → 只提醒、不扣次数）
  0.5 易错点确定性兜底（confusionPoints 正则命中即返回标答，先于 LLM，杜绝"该说不是却和稀泥"）
  1. RAG 关键词匹配 checkpoints（命中 → 直接返回预设判定）
  2. 以上都不命中 → LangChain 调大模型判定

复盘评估（evaluate_completion）用 LangChain + JsonOutputParser 输出结构化完成度。
"""
import os
import re
import random
import httpx
from typing import List, Optional

from langchain_openai import ChatOpenAI
from langchain_core.messages import SystemMessage, HumanMessage, AIMessage
from langchain_core.prompts import ChatPromptTemplate
from langchain_core.output_parsers import JsonOutputParser

from . import config
from .prompts import HOST_SYSTEM_PROMPT
from .schemas import Soup, ConfusionPoint, Checkpoint, EvaluationResult, SymbolMapping, HostJudgment
from . import rag


# ===================== LLM 客户端（LangChain ChatOpenAI） =====================
_llm_cache: dict = {}

# 共享 HTTP 连接池：避免每次 LLM 调用都重新 TLS 握手（省几十 ms/次）。
# 挂到模块级，进程生命周期内复用连接；线程安全由 httpx 内部保证。
_http_client = httpx.Client(
    timeout=httpx.Timeout(connect=10.0, read=120.0, write=30.0, pool=10.0),
)


def _get_llm(max_tokens: int = 50) -> ChatOpenAI:
    """懒加载并缓存 ChatOpenAI 实例（兼容 OpenAI 协议）：ollama / zhipu / siliconflow / cloud。"""
    if max_tokens not in _llm_cache:
        if config.LLM_PROVIDER == "ollama":
            # 本地 Ollama：0 成本，api_key 仅占位（Ollama 不校验）
            _llm_cache[max_tokens] = ChatOpenAI(
                model=config.OLLAMA_MODEL,
                api_key="ollama",
                base_url=config.OLLAMA_BASE_URL,
                temperature=0.1,
                max_tokens=max_tokens,
                http_client=_http_client,
            )
        elif config.LLM_PROVIDER == "siliconflow":
            # 硅基流动：选带「免费」标签的小模型即可 0 成本（不消耗赠送额度）
            _llm_cache[max_tokens] = ChatOpenAI(
                model=config.SILICONFLOW_MODEL,
                api_key=config.SILICONFLOW_API_KEY,
                base_url=config.SILICONFLOW_BASE_URL,
                temperature=0.1,
                max_tokens=max_tokens,
                http_client=_http_client,
            )
        elif config.LLM_PROVIDER == "zhipu":
            # 智谱 AI：GLM-4-Flash 永久免费，无需充值，能力优于 7B 级小模型
            _llm_cache[max_tokens] = ChatOpenAI(
                model=config.ZHIPU_MODEL,
                api_key=config.ZHIPU_API_KEY,
                base_url=config.ZHIPU_BASE_URL,
                temperature=0.1,
                max_tokens=max_tokens,
                http_client=_http_client,
            )
        else:
            # 云端 API（通义/智谱/DeepSeek 等，需自备 key 或额度）
            _llm_cache[max_tokens] = ChatOpenAI(
                model=config.QWEN_MODEL,
                api_key=config.QWEN_API_KEY,
                base_url=config.QWEN_BASE_URL,
                temperature=0.1,
                max_tokens=max_tokens,
                http_client=_http_client,
            )
    return _llm_cache[max_tokens]


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


def format_progress_hint(soup: Soup, history: List[dict]) -> str:
    """根据当前问答记录提示玩家当前完成度（不暴露未触及的 checkpoint 关键词）。"""
    # 复用 evaluate_completion 的纯计算逻辑（不修改会话状态）
    qa_text = "\n".join(
        f"{'玩家' if m.get('role') == 'user' else '主持人'}：{m.get('content', '')}"
        for m in history
        if m.get("role") in ("user", "host")
    )
    try:
        result = evaluate_completion(soup, qa_text, messages=history)
        completion = result.get("completion", 0)
        if completion >= 100:
            return f'🎯 当前完成度 {completion}% 已经满了！可以点左侧「🏁 揭晓答案」直接通关~'
        if completion == 0:
            return f'🎯 当前完成度约 {completion}%，继续从侧面提问来推进推理吧~'
        if completion < 40:
            return f'🎯 当前完成度约 {completion}%，刚开了个头，继续问~'
        if completion < 70:
            return f'🎯 当前完成度约 {completion}%，方向对了，但还有关键情节没触及。'
        return f'🎯 当前完成度约 {completion}%，已经很接近了，再深挖一下~'
    except Exception:
        return '🎯 可以点击左侧「🏁 揭晓答案」查看当前完成度和汤底；也可以继续从侧面提问推进~'


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
# 喂给 LLM 的自动合并规则上限（手写易错点全部保留；自动规则只取最近 N 条，
# 避免玩家反馈按天累积（如一天100条）导致 prompt 上下文爆炸、主持人变慢变笨。
# 注意：确定性匹配层 match_confusion_point 仍遍历【全部】规则，旧 bug 修复不会丢失，
# 只是不再全量塞进 LLM 提示词——规则命中了根本轮不到 LLM。
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
_CLAUSE_SEPARATORS = set("，。,；; ")
_CLAIM_MARKERS = ["是", "被", "有", "在"]


def is_compound_statement(question: str) -> bool:
    """检测玩家是否把多个独立判断揉在一句话里（复合陈述）。

    复合陈述的典型特征：
    - 句子较长（>=13 字）且包含分句/空格等分隔符；
    - 或包含多个断言词（是/被/有/在），难以用单个易错点判定整体对错。

    注意：
    - "是不是/是否/有没有/能不能/可不可以"等疑问结构只算一个整体；
    - 单个空格（如"我 爸妈 妻子"这种列表写法）不视为复合分句，只有 2 个及以上空格才计入。
    """
    q = question.strip()
    if len(q) < 12:
        return False
    # 中文/英文标点分隔符
    sep_count = sum(1 for c in q if c in "，。,；;")
    # 空格只有在出现 2 次及以上时才视为复合分隔（避免"我 爸妈 妻子"被误判）
    space_count = q.count(" ")
    if space_count >= 2:
        sep_count += space_count
    if sep_count >= 1 and len(q) >= 13:
        return True
    if sep_count >= 2:
        return True
    # 把疑问结构替换为占位符，避免"是不是"被拆成两个"是"
    q_for_markers = re.sub(r"是不是|是否|有没有|有木有|能不能|可不可以|能否|会不会", "¿", q)
    marker_count = sum(q_for_markers.count(m) for m in _CLAIM_MARKERS)
    if len(q) >= 16 and marker_count >= 2:
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


# ===================== 变格元素通用规则 =====================
# genre=变格 的汤，玩家问"有穿越/灵异/魔法等元素吗"时确定性答是（汤里几乎都含变格元素）；
# 否定形式（"没有X吗"）答不是。是 match_genre_answer 的语义补充：genre 规则只匹配"本格/变格"标志词，
# 这条覆盖变格元素的具体问法，避免全靠 LLM 免费模型瞎猜（曾误答"不是"）。
_SUPERNATURAL_KEYWORDS = [
    "穿越", "时空穿越", "时空逆行", "时间倒流", "时间倒着", "时间逆行",
    "平行世界", "平行宇宙", "平行时空", "多元宇宙",
    "超自然", "灵异", "灵异事件", "鬼怪", "闹鬼", "招魂",
    "魔法", "魔幻", "魔法少女", "修仙", "妖怪", "异能", "特异功能",
    "恶魔", "附身", "被附身", "召唤", "变身", "复活", "不死",
    "吸血鬼", "狼人", "僵尸", "幽灵",
    "幻觉", "幻象", "灵魂出窍", "催眠", "轮回", "因果循环",
]


def match_supernatural_answer(soup: Soup, question: str) -> Optional[str]:
    """ genre=变格时，玩家问"有/是/存在{变格元素}吗"确定性答是；否定形式答不是。不命中返回 None。"""
    if (soup.genre or "") != "变格":
        return None
    q = question.strip()
    hit_kw = next((kw for kw in _SUPERNATURAL_KEYWORDS if kw in q), None)
    if not hit_kw:
        return None
    rkw = re.escape(hit_kw)
    # 否定形式：问"没有/不是/不存在 X 吗"
    if re.search(r"(没有|不是|不存在|没)\s*.{0,6}" + rkw, q):
        return "不是"
    # 肯定形式：含"有/是/存在/发生了 + 关键词" 或"故事里 X"
    if re.search(r"(有|是|存在|发生了?|真的|算)\s*.{0,8}" + rkw, q) or \
       re.search(r"故事.{0,6}" + rkw, q) or \
       re.search(rkw + r".{0,6}(对吧|吧)", q):
        return "是"
    return None


# ===================== 本格/变格 类型问题确定性兜底（通用规则） =====================
_GENRE_QUESTION_MARKERS = ["吗", "么", "是不是", "是否", "算不算", "算", "属于", "还是", "吧", "？", "?"]


def match_genre_answer(soup: Soup, question: str) -> Optional[str]:
    """玩家问"这是本格吗/这是变格吗/有变格元素吗"等类型问题时，按汤的 genre 字段确定性作答。

    - 汤必须有 genre（"本格"/"变格"），否则返回 None 走原流程；
    - 同时提及"本格"和"变格"（如"本格还是变格"）返回 None，交给 LLM；
    - 只有孤立关键词（如只发"本格"二字）不当作类型问题，避免误答。
    """
    genre = (getattr(soup, "genre", "") or "").strip()
    if genre not in ("本格", "变格"):
        return None
    q = question.strip()
    has_benge = "本格" in q
    has_biange = "变格" in q
    if not (has_benge or has_biange):
        return None
    if has_benge and has_biange:
        return None
    if not any(m in q for m in _GENRE_QUESTION_MARKERS):
        return None
    kw = "本格" if has_benge else "变格"
    return "是" if genre == kw else "不是"


# ===================== 人数问题确定性兜底（通用规则） =====================
# 口径（用户 2026-08-24 定义）：玩家问"故事里只有xx人"时，这个数量指「故事中有作用 /
# 有指定称呼 / 有名有姓的真实人物实体数」。
#   - 同一真人用不同称呼（如妈妈=妻子）只算 1 个实体；
#   - 村民 / 人们 / 围观群众 / 台下众人 等大规模泛指群体不算；
#   - 演员扮演的非真实角色（如《噩梦重现》里的"妻子/父母"）不算真实人物；
#   - 未出生的胎儿不计为独立"人"。
# soup.castCount 即按此口径标注的整数；为 None 则该汤不触发此规则。
_CAST_CN_NUM = {
    "零": 0, "一": 1, "二": 2, "两": 2, "三": 3, "四": 4, "五": 5,
    "六": 6, "七": 7, "八": 8, "九": 9,
}


def _cn_to_int(token: str) -> Optional[int]:
    """把阿拉伯数字或简单中文数字（0~99）转成 int。"""
    s = (token or "").strip()
    if not s:
        return None
    if s.isdigit():
        return int(s)
    if s in _CAST_CN_NUM:
        return _CAST_CN_NUM[s]
    # 含「十」的中文数字：十 / 十X / X十 / X十Y
    if "十" in s:
        left, _, right = s.partition("十")
        if left == "" and right == "":
            return 10
        if right == "":  # X十 -> X*10
            return _CAST_CN_NUM.get(left, 1) * 10
        if left == "":  # 十X -> 10+X
            return 10 + _CAST_CN_NUM.get(right, 0)
        return _CAST_CN_NUM.get(left, 1) * 10 + _CAST_CN_NUM.get(right, 0)
    return None


_CAST_SUBSET_KEYWORDS = [
    "死", "活", "参与", "出现", "认识", "知道", "看见", "在场", "幸存",
    "失踪", "被杀", "遇害", "身亡", "活着", "到场的", "在场的",
]

# 人数限定问法正则（预编译）：
#   (限定词|总括词) 必选 + (≤15字人名/修饰)? + 数字 + (个|口)? + 人 + (吗/么/吧/是…吗/？)?
#   limiter 必选（含"只有/仅/就/一共/总共/共/才/不过"等限定词，以及"故事/汤/旅馆/整个/里面"等总括词），
#   避免"旅馆里只有七个人吗"被前缀吞掉 limiter 而误判为 None。
# 例："只有四个人吗" / "只有我和爸爸两个人吗" / "一家七口人吗" / "两个人是新人吗" / "旅馆里只有七个人吗"
_CAST_RE = re.compile(
    r"(只有|仅有|就|一共|总共|共|仅|才|不过|故事|汤|整个|里面|全部|旅馆|现场|当时|全程)\s*"
    r".{0,15}?\s*"
    r"([0-9]+|[零一二两三四五六七八九十百]+)\s*"
    r"(?:个|口)?\s*人\s*"
    r"(?:吗|么|吧|对吗|对吧|？|\?|是[^吗么吧？?]{0,12}(?:吗|么|吧|？|\?))?\s*$"
)


def match_cast_count(soup: Soup, question: str) -> Optional[str]:
    """玩家问'故事里只有N个人吗'时，按 soup.castCount 确定性作答。

    仅匹配"总人数"限定问法：含限定词（只有/仅有/就/一共/总共/共/仅/才/不过/是）
    或"故事/汤/整个/里面"等总括词 + 数字 + 人 + 吗/么/吧/？。

    排除问"死/活/参与/出现"等某子集人数的情形，避免误判。
    命中：N == castCount -> 是；否则 -> 不是。
    """
    cc = getattr(soup, "castCount", None)
    if cc is None:
        return None
    q = question.strip()
    # 子集限定词：问的是"死/活/参与/认识"的某部分人，不是总人数 -> 交原流程
    if any(kw in q for kw in _CAST_SUBSET_KEYWORDS):
        return None
    if not re.search(r"人", q):
        return None
    m = _CAST_RE.search(q)
    if not m:
        return None
    num = _cn_to_int(m.group(2))
    if num is None:
        return None
    return "是" if num == cc else "不是"


# ===================== 主入口：处理玩家消息 =====================
def handle_host_response(
    soup: Soup,
    history: List[dict],
    user_question: str,
) -> dict:
    # 0. 隐藏彩蛋通关条件（最高优先级）：玩家同时提及关键设定即判定通关，
    # 直接返回祝贺语并标记 is_win，不再走 always_yes 的普通"是"。
    win_msg = check_win_condition(soup, user_question)
    if win_msg:
        return {
            "reply": win_msg,
            "is_reveal": True,
            "is_giveup": False,
            "is_win": True,
            "matched_checkpoint": "win_condition",
        }

    # 特殊汤：always_yes（彩蛋汤《新世界》）。
    # 玩家问什么，主持人都回答"是"，因为世界是被编造的想象空间；
    # 非是否类问题仍引导改问法（保持统一交互）。
    if soup.always_yes:
        if not is_yes_no_question(user_question):
            return {
                "reply": format_yes_no_reminder(user_question),
                "is_reveal": False,
                "is_giveup": False,
                "matched_checkpoint": None,
            }
        hesitations = [
            "是",
            "是",
            "是",
            "……是",
            "嗯，是",
            "是。",
        ]
        return {
            "reply": random.choice(hesitations),
            "is_reveal": False,
            "is_giveup": False,
            "matched_checkpoint": "always_yes",
        }

    # 0. 游戏流程类消息兜底：先识别"完整推理/汤底直接发在聊天框"和"问进度/缺什么"元问题。
    # 这类消息不能也不应该用"是/不是"回答，且不应消耗提问次数。
    if looks_like_reveal_attempt(user_question):
        return {
            "reply": format_reveal_reminder(),
            "is_reveal": False,
            "is_giveup": False,
            "matched_checkpoint": "reveal_attempt_reminder",
        }
    if is_meta_progress_question(user_question):
        return {
            "reply": format_progress_hint(soup, history),
            "is_reveal": False,
            "is_giveup": False,
            "matched_checkpoint": "progress_hint",
        }

    # 0.5 易错点确定性兜底（命中即直接返回标答，先于是否类检测）
    # 放在最前面：可覆盖"陈述式确认"（如"我还存在于2027年之后""然后偷完孩子回到00年成为了爷爷被杀死"）
    # 这类玩家推理确认句没有"吗/么"等疑问标志，会被 is_yes_no_question 误判为非是否类而拦掉。
    #
    # 复合陈述特殊处理：玩家把多个判断揉在一句话里（有对有错），不能用一个最具体的易错点
    # 直接截胡整体答案。此时收集所有命中的易错点：
    # - 若多个易错点标答不一致，强制聚合为「是也不是」；
    # - 若只命中一个易错点且标答为「不是」：说明至少有一处错、其他部分可能对，按用户规则返回「是也不是」；
    # - 若只命中一个易错点且标答非「不是」（是/与此无关/算是）：整段围绕此确定事实，直接用易错点答案（确定性）；
    # - 若命中 0 个：走 LLM，由 prompt 规则 14 约束「有对有错→是也不是」。
    is_compound = is_compound_statement(user_question)
    if is_compound:
        cp_matches = collect_confusion_matches(soup, user_question)
        if len(cp_matches) >= 2:
            # 若任一命中易错点覆盖玩家整句（作者已为该句锁定确定性答案），
            # 直接采用该易错点答案，不再做「有对有错→是也不是」的聚合。
            # 否则多个局部易错点（含不同标答）会被强制和稀泥，把整句本应为「是」的
            # 复合确认句误判成「是也不是」（如「偷完孩子回到00年成为爷爷被杀死 是吗」）。
            for cp, ans in cp_matches:
                if _cp_targets_whole_question(cp, user_question):
                    return {
                        "reply": ans,
                        "is_reveal": False,
                        "is_giveup": False,
                        "matched_checkpoint": f"易错点整句锁定:{cp.q}",
                    }
            aggregated = aggregate_confusion_replies(cp_matches)
            return {
                "reply": aggregated,
                "is_reveal": False,
                "is_giveup": False,
                "matched_checkpoint": f"复合陈述聚合({len(cp_matches)}个易错点)",
            }
        # 命中 1 个易错点且其标答为「不是」：说明这句话里至少有一处明确错误，
        # 而复合陈述里通常还夹杂其他判断，按用户规则统一返回「是也不是」。
        # 例外：若该易错点的手写问题原文（cp.q）覆盖了玩家整句，说明作者已为整句
        # 锁定确定性答案（如旅馆"女孩的亲吻是在向我传递一种信号吗"），直接采用而非和稀泥。
        if len(cp_matches) == 1 and cp_matches[0][1] == "不是":
            if _cp_targets_whole_question(cp_matches[0][0], user_question):
                return {
                    "reply": cp_matches[0][1],
                    "is_reveal": False,
                    "is_giveup": False,
                    "matched_checkpoint": f"易错点整句锁定:{cp_matches[0][0].q}",
                }
            return {
                "reply": "是也不是",
                "is_reveal": False,
                "is_giveup": False,
                "matched_checkpoint": f"复合陈述单点兜底({cp_matches[0][0].q})",
            }
        # 命中 1 个非「不是」易错点：整段陈述围绕此确定事实，直接用易错点答案（确定性，避免 LLM 偶发飘）。
        if len(cp_matches) == 1:
            return {
                "reply": cp_matches[0][1],
                "is_reveal": False,
                "is_giveup": False,
                "matched_checkpoint": f"复合陈述单点易错点:{cp_matches[0][0].q}",
            }
        # 命中 0 个易错点：继续走 LLM
    else:
        # 非复合陈述：保持原有单点易错点兜底逻辑，但用 effective_answer 处理否定陈述
        cp_hit = match_confusion_point(soup, user_question)
        if cp_hit:
            eff_a = effective_answer_for_clause(cp_hit, user_question)
            return {
                "reply": eff_a,
                "is_reveal": False,
                "is_giveup": False,
                "matched_checkpoint": f"易错点:{cp_hit.q}",
            }

    # 0.4 本格/变格 类型问题确定性兜底（通用规则，2026-08-23 新增）
    # 放在易错点/复合判定之后：具体汤的易错点（如"除了巫术还有其他变格元素吗"）优先，
    # 未被易错点覆盖的通用类型问题（"这是本格吗/这是变格吗/有变格元素吗"）由 genre 字段确定性作答。
    genre_ans = match_genre_answer(soup, user_question)
    if genre_ans is not None:
        return {
            "reply": genre_ans,
            "is_reveal": False,
            "is_giveup": False,
            "matched_checkpoint": f"类型判定(genre={getattr(soup, 'genre', '')})",
        }

    # 0.4a 变格元素问法兜底（2026-09-01 新增）：genre=变格 时，玩家问"有穿越/灵异/魔法等元素吗"
    # 确定性答"是"，"没有X吗"答"不是"。补 match_genre_answer 只匹配"本格/变格"标志词之不足。
    # 放在 cast_count 之前、是否类检测之前：玩家必看得到确定性答案，避免 LLM 免费模型瞎猜。
    super_ans = match_supernatural_answer(soup, user_question)
    if super_ans is not None:
        return {
            "reply": super_ans,
            "is_reveal": False,
            "is_giveup": False,
            "matched_checkpoint": f"变格元素判定(genre=变格)",
        }

    # 0.4b 人数问题确定性兜底（通用规则，2026-08-24 新增）
    # 放在 genre 规则之后、是否类检测之前：玩家问"只有xx人吗"按 soup.castCount 确定性作答，
    # 不依赖 LLM，避免把村民/围观群众等泛指群体数进去。castCount 为 None 的汤不触发。
    cast_ans = match_cast_count(soup, user_question)
    if cast_ans is not None:
        return {
            "reply": cast_ans,
            "is_reveal": False,
            "is_giveup": False,
            "matched_checkpoint": f"人数判定(castCount={getattr(soup, 'castCount', None)})",
        }

    # 0. 是否类检测（覆盖所有路径）
    if not is_yes_no_question(user_question):
        return {
            "reply": format_yes_no_reminder(user_question),
            "is_reveal": False,
            "is_giveup": False,
            "matched_checkpoint": None,
        }

    # 1. RAG 语义匹配。复合陈述跳过 RAG（避免只命中一个 checkpoint 就给出片面答案）；
    # 关系型问题跳过（象征/因果需要语义理解）。
    # 身份归属类问题（"我是人吗""哥哥是自杀吗"）也允许先试 RAG：checkpoints.aliases
    # 是作者按玩家问法人工标注的，命中即用。此前 identity 问题被整体跳过 RAG 走 LLM，
    # 免费模型对这类简单身份问题反而答不准（实测"我是人吗"答成"不是"、哥哥的指令 4 题全错）。
    if not is_compound and not is_relational_question(user_question):
        match = rag.match_user_query(user_question, soup)
        if match.match and match.checkpoint:
            reply = generate_reply_from_checkpoint(match.checkpoint)
            return {
                "reply": reply,
                "is_reveal": False,
                "is_giveup": False,
                "matched_checkpoint": match.checkpoint.key,
            }

    # 2. 没有精确匹配 或 是关系型问题 / 复合陈述 → LangChain 调 LLM 判断
    # 系统 prompt 规则 14 已明确要求：复合陈述有对有错时回答「是也不是」。
    # （单点易错点的复合句已在上方确定性处理，此处仅服务 0 命中复合句 / 关系型 / 身份类问题）
    extra = None
    if is_compound:
        extra = (
            "【特别注意：玩家这句话包含多个独立判断（复合陈述）。"
            "如果其中有的判断正确、有的判断错误，或部分判断需要 nuanced 口径，"
            "你必须整体回答「是也不是」，禁止只抓住一个错误点就整体回答「不是」，"
            "也禁止因为'基本正确'就整体回答「是」。】"
        )
    llm_reply = call_llm(soup, history, user_question, extra_instruction=extra)
    return {**llm_reply, "matched_checkpoint": None}


# ===================== LangChain LLM 判定 =====================
def call_llm(soup: Soup, history: List[dict], user_question: str, extra_instruction: Optional[str] = None, fallback_answer: Optional[str] = None) -> dict:
    try:
        # 关键改造：发送【完整汤底】而非 bottomSummary。
        # 摘要会丢失"妈妈发疯是因为生下丈夫"这类关键因果链，导致 LLM 误判；
        # 完整汤底每局约几千 token，本地 Ollama 0 成本、云端也极便宜，却能根治"看不懂汤底"。
        truth_text = soup.bottom
        confusion_text = build_confusion_text(soup)
        symbol_text = build_symbol_text(soup)
        truth_items_text = build_truth_text(soup)
        recent_history = history[-10:] if history else []

        llm = _get_llm(max_tokens=600)
        parser = JsonOutputParser(pydantic_object=HostJudgment)
        prompt = ChatPromptTemplate.from_messages([
            ("system", HOST_SYSTEM_PROMPT),
            ("human", "{input_text}\n\n{format_instructions}"),
        ]).partial(format_instructions=parser.get_format_instructions())
        chain = prompt | llm | parser

        history_text = "\n".join(
            f"{'玩家' if (m.get('role', 'user') if isinstance(m, dict) else getattr(m, 'role', 'user')) == 'user' else '主持人'}："
            f"{m.get('content', '') if isinstance(m, dict) else getattr(m, 'content', '')}"
            for m in recent_history
        )

        user_content = (
            f"[当前汤的汤面]{soup.surface}\n\n"
            f"[完整汤底真相（绝对不能透露给玩家）]\n{truth_text}\n\n"
            f"[汤底关键意象与真实含义（必须区分字面物品与象征含义）]\n{symbol_text}\n\n"
            f'[汤底关键事实清单（回答身份归属/"X 是 Y 吗"类问题时，必须先在此定位 X 的真实身份）]\n{truth_items_text}\n\n'
            f"[已知易错点（遇到这些问题必须严格按给定答案回复）]\n{confusion_text}\n\n"
            f"[最近问答记录]\n{history_text if history_text else '（无）'}\n\n"
            f"{extra_instruction + chr(10) + chr(10) if extra_instruction else ''}"
            f"[玩家的提问]{user_question}\n\n"
            "请先依据[完整汤底真相]在心里列出与提问相关的事实（内部推理，不得透露给玩家），"
            "再严格只从 是/不是/是也不是/算是/与此无关 中选一个作为最终判定。"
        )

        try:
            result = chain.invoke({"input_text": user_content})
        except Exception as e:  # noqa: BLE001
            print("⚠️ HostJudgment 结构化解析失败，降级文本归一化:", e)
            messages = [SystemMessage(content=HOST_SYSTEM_PROMPT), HumanMessage(content=user_content)]
            raw = llm.invoke(messages)
            text = raw.content if hasattr(raw, "content") else str(raw)
            norm = _normalize_reply(text)
            if fallback_answer and norm not in ("是", "不是", "是也不是", "算是", "与此无关"):
                return {"reply": fallback_answer, "is_reveal": False, "is_giveup": False}
            return {"reply": norm, "is_reveal": False, "is_giveup": False}

        if hasattr(result, "model_dump"):
            result = result.model_dump()
        # 兜底：parser 偶尔返回非 dict（如 str），直接归一化文本或降级易错点答案
        if not isinstance(result, dict):
            norm = _normalize_reply(str(result))
            if fallback_answer and norm not in ("是", "不是", "是也不是", "算是", "与此无关"):
                return {"reply": fallback_answer, "is_reveal": False, "is_giveup": False}
            return {"reply": norm, "is_reveal": False, "is_giveup": False}
        answer = result.get("answer") or ""
        reply = _normalize_reply(answer)
        return {"reply": reply, "is_reveal": False, "is_giveup": False}
    except Exception as e:  # noqa: BLE001
        msg = str(e)
        if config.LLM_PROVIDER == "ollama":
            # 本地模式连不上，通常是 Ollama 未启动或没拉模型，给出可操作提示
            print("❌ 本地 Ollama 调用失败（请确认 Ollama 已启动且已拉取模型）:", e)
            return {
                "reply": "🤖 无法连接本地 Ollama，请先启动 Ollama 并拉取模型（ollama run qwen2.5:7b）。",
                "is_reveal": False,
                "is_giveup": False,
            }
        # 明确区分"额度耗尽/限流/服务异常"与"一般性失败"，便于自诊断（避免误以为是代码 bug）。
        # 注意：玩家看不到内部细节——免费模型（如 SiliconFlow Qwen2.5-7B-Instruct）虽 0 元，
        # 但有 RPM/QPS 限速，超限会 502/429，此时给玩家友好提示即可，具体原因只打日志。
        if "Free quota" in msg or "AllocationQuota" in msg or "403" in msg:
            print("❌ LLM 调用失败（API 额度/权限问题）:", e)
            return {
                "reply": "🤖 主持人暂时走神了，请重新发送你的问题（不会扣除提问次数）~",
                "is_reveal": False,
                "is_giveup": False,
            }
        if fallback_answer:
            print("❌ LLM 调用失败，降级使用易错点答案:", e)
            return {"reply": fallback_answer, "is_reveal": False, "is_giveup": False}
        print("❌ LLM 调用失败:", e)
        return {"reply": "🤖 主持人思考失败，请重新发送你的问题（不会扣除提问次数）~", "is_reveal": False, "is_giveup": False}


# ===================== LangChain 复盘评估 =====================
def _clamp(n) -> int:
    try:
        n = int(n)
    except Exception:
        return 0
    return max(0, min(100, n))


def _parse_qa_pairs(qa_text: str):
    """把 '玩家：问题\\n主持人：回答' 文本解析成 [(question, answer), ...]。"""
    pairs = []
    cur_q = None
    for line in qa_text.split("\n"):
        line = line.strip()
        if line.startswith("玩家") and ("：" in line or ":" in line):
            sep = "：" if "：" in line else ":"
            cur_q = line.split(sep, 1)[1].strip()
        elif line.startswith("主持人") and ("：" in line or ":" in line) and cur_q:
            sep = "：" if "：" in line else ":"
            ans = line.split(sep, 1)[1].strip()
            pairs.append((cur_q, ans))
            cur_q = None
    return pairs


def _ans_matches(ans: str, expected: bool) -> bool:
    """判断主持人回答是否与 checkpoint 期望一致（True=应为'是'，False=应为'不是'）。"""
    a = (ans or "").strip()
    if not a:
        return False
    is_neg = a.startswith("不是") or a == "否" or a.startswith("否")
    is_pos = (a.startswith("是") and "不是也" not in a) or any(
        k in a for k in ("算是", "对", "没错", "正确", "是的")
    )
    if expected is True:
        return is_pos
    # expected is False / 'unknown'：只要给出了明确否定或任意答复即算触及
    return is_neg or is_pos or len(a) > 0


def _checkpoint_keywords(cp: Checkpoint) -> list[str]:
    """返回 checkpoint 用于匹配的关键字列表（key + aliases，去空）。"""
    key = cp.key or ""
    aliases = cp.aliases or []
    return [k for k in [key] + list(aliases) if k]


def _checkpoint_hit_by_text(cp: Checkpoint, text: str) -> bool:
    """判断一段文本（如玩家最终推理/汤底直发）是否覆盖某个 checkpoint 的关键信息。"""
    if not text:
        return False
    tl = text.lower()
    return any(kw.lower() in tl for kw in _checkpoint_keywords(cp))


def evaluate_completion(soup: Soup, qa_text: str, messages: Optional[List[dict]] = None) -> dict:
    """根据本局问答记录与预设 checkpoints 规则化计算还原完成度。

    不调用 LLM（本地小模型无法稳定输出结构化 JSON，且每次白等数秒）。
    直接判断每个 checkpoint 是否被玩家问及并得到与真相一致的答复，
    100% 确定、瞬间返回、与主持人判定逻辑同源。

    额外支持：如果玩家把完整推理/汤底直接发在聊天框（被识别为 reveal_attempt 并保存），
    也会用该文本匹配 checkpoints，避免"明明答对了却 0%"的情况。
    """
    checkpoints = [cp for cp in (soup.checkpoints or [])]

    # 隐藏彩蛋汤的通关：命中 win_condition 即 100% 通关（即使没有 checkpoints）。
    win_msg = check_win_condition(soup, qa_text)
    if win_msg:
        return {
            "completion": 100,
            "evaluation": "🎉 你已看穿隐藏彩蛋的终极真相，达成通关！完整汤底如下，请对照回顾。",
            "keyPointsCovered": ["通关条件已满足"],
            "keyPointsMissing": [],
        }

    if not checkpoints:
        return {
            "completion": 0,
            "evaluation": "本局暂无预设复盘要点，但完整汤底如下，请对照回顾。",
            "keyPointsCovered": [],
            "keyPointsMissing": [],
        }

    pairs = _parse_qa_pairs(qa_text)

    # 收集玩家发在聊天框里的"完整推理/汤底"类消息，用于最终覆盖度兜底
    reveal_texts: list[str] = []
    if messages:
        for m in messages:
            if m.get("role") == "user":
                content = m.get("content", "")
                if looks_like_reveal_attempt(content):
                    reveal_texts.append(content)

    covered, missing = [], []
    for cp in checkpoints:
        expected = cp.answer != "unknown" and cp.answer  # True/False 期望；unknown 视为任意
        hit = False
        # 1. 正常问答匹配
        for q, a in pairs:
            ql = q.lower()
            if any(kw.lower() in ql for kw in _checkpoint_keywords(cp)):
                # answer 为 'unknown' 时只要问及即算触及；否则需答复与期望一致
                if cp.answer == "unknown" or _ans_matches(a, bool(cp.answer)):
                    hit = True
                    break
        # 2. 完整推理/汤底直发兜底
        if not hit and reveal_texts:
            # 对于期望为 True 的 checkpoint，直接看关键词是否出现在玩家推理中；
            # 对于期望为 False 或 unknown 的， keyword 命中本身也说明玩家讨论到了该点，
            # 保守起见仍按"触及"处理（玩家能写出相关内容即视为知道）。
            if any(_checkpoint_hit_by_text(cp, t) for t in reveal_texts):
                hit = True
        if hit:
            covered.append(cp.key or "")
        else:
            missing.append(cp.key or "")

    total = len(checkpoints)
    cov = len(covered)
    completion = round(cov / total * 100) if total else 0

    if completion == 100:
        eval_text = f"完美！你还原了全部 {total} 个核心真相，完成度 100%。"
    elif completion >= 60:
        miss_preview = "、".join(missing[:3])
        tail = " 等" if len(missing) > 3 else ""
        eval_text = (
            f"不错！你还原了 {cov}/{total} 个核心真相（完成度 {completion}%）。"
            f"还有 {len(missing)} 个关键点没触及：{miss_preview}{tail}。"
        )
    else:
        miss_preview = "、".join(missing[:5])
        eval_text = (
            f"你还原了 {cov}/{total} 个核心真相（完成度 {completion}%）。"
            f"关键遗漏：{miss_preview}。"
        )

    # 特殊评分映射：用于解锁彩蛋汤（如《织梦者》→《新世界》）。
    # 规则：真实还原度 < 50% 时显示真实分；>= 50% 时直接显示 70%（解锁门槛），
    # 真实越高显示也越高（线性），封顶 100%。保证玩家"答得差不多"就能亮彩蛋。
    raw_completion = completion
    display_completion = completion
    if soup.special_scoring:
        if completion >= 50:
            display_completion = min(100, max(70, round(completion * 1.2)))
        # else 保持真实分

    return {
        "completion": display_completion,
        "rawCompletion": raw_completion,
        "unlockThresholdReached": display_completion >= 70,
        "evaluation": eval_text,
        "keyPointsCovered": covered,
        "keyPointsMissing": missing,
    }
