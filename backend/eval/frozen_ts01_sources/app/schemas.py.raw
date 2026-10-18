"""Pydantic 数据模型。

注意：响应模型的字段名故意使用 camelCase，以与现有 Next.js 前端的
约定（soupTitle / soupSurface / questionLimit / sessionId / isFreeReminder /
limitReached / keyPointsCovered / keyPointsMissing）保持一致，前端无需改动字段名。
"""
from typing import List, Literal, Optional, Union

from pydantic import BaseModel, ConfigDict, Field

# 主持人 5 种标准回答
AnswerType = Literal["是", "不是", "是也不是", "算是", "与此无关"]


class HostJudgment(BaseModel):
    """LLM 主持判定的结构化输出：先内部推理，再给最终 5 选 1 判定。

    用 JsonOutputParser 解析，避免模型自由文本里把推理和答案混在一起，
    也方便把 reasoning 与 answer 分离（answer 用于回复，reasoning 仅供调试）。
    """

    model_config = ConfigDict(populate_by_name=True)
    reasoning: str = Field(
        description="基于完整汤底事实的简短内部推理；只能引用汤底真相，不得向玩家透露汤底细节"
    )
    answer: AnswerType = Field(
        description="最终判定，只能从以下选一：是、不是、是也不是、算是、与此无关"
    )


class Checkpoint(BaseModel):
    model_config = ConfigDict(populate_by_name=True)
    key: str
    answer: Union[bool, Literal["unknown"]]  # true=是 / false=不是 / 'unknown'=与此无关
    hint: Optional[str] = None
    category: Optional[str] = None
    aliases: Optional[List[str]] = None


class ConfusionPoint(BaseModel):
    model_config = ConfigDict(populate_by_name=True)
    q: str  # 展示用坑点描述
    a: AnswerType  # 确定性标答
    match: Optional[List[str]] = None  # 触发正则（任一命中即锁定）
    note: Optional[str] = None


class SymbolMapping(BaseModel):
    """汤面意象 → 真实含义（帮助主持人理解隐喻/象征，避免只看字面关键词）。"""

    model_config = ConfigDict(populate_by_name=True)
    symbol: str  # 汤面意象（如"鱼缸/鱼"）
    meaning: str  # 真实含义（如"象征被囚禁的复制体/人类处境；不是双鱼玉佩"）
    note: Optional[str] = None  # 常见误读或判断示例


class TruthItem(BaseModel):
    """汤底中的原子事实（Truth Item）。

    把长文本汤底拆成可检索的结构化事实，帮助主持人在回答"X 是 Y 吗"这类
    身份/归属问题时，先定位到与 X 直接相关的事实，而不是凭关键词印象作答。
    """

    model_config = ConfigDict(populate_by_name=True)
    subject: str  # 事实主体，如"花园/院子下的尸体""04年的妻子"
    relation: str  # 关系，如"身份是""最终去向是""不是"
    object: str  # 事实对象/客体，如"主角（我）的复制体""失踪后穿越时空"
    evidence: Optional[str] = None  # 汤底中支撑该事实的原文片段或解释
    confidence: Optional[str] = "high"  # high/medium/low，表示事实确定性


class DifficultyLimits(BaseModel):
    model_config = ConfigDict(populate_by_name=True)
    xuermu: int
    baozi: int
    tianyi: int


class Soup(BaseModel):
    model_config = ConfigDict(populate_by_name=True)
    id: str
    title: str
    surface: str
    bottom: str
    bottomSummary: Optional[str] = None
    checkpoints: List[Checkpoint] = []
    tags: List[str] = []
    difficulty: int = 3
    source: str = ""
    genre: str = ""  # 汤类型：本格 / 变格（加汤必填；主持人据此确定性回答"这是本格吗/这是变格吗"）
    castCount: Optional[int] = None  # 故事中有作用/有指定称呼/有名有姓的真实人物实体数（同人异号算1；村民/人们/围观群众等泛指群体不算；演员扮演的非真实角色不算；未出生胎儿不计）。用于确定性回答"只有xx人吗"。加汤时按此口径标注；留 None 则该汤不触发人数规则。
    difficultyLimits: Optional[DifficultyLimits] = None
    confusionPoints: Optional[List[ConfusionPoint]] = None
    symbolMappings: Optional[List[SymbolMapping]] = None
    truthItems: Optional[List[TruthItem]] = None
    # 彩蛋/系列汤专属字段
    hidden: bool = False  # 不在首页列表显示，需解锁
    unlimited: bool = False  # 不限制提问次数
    always_yes: bool = False  # 是否类问题一律回答"是"
    special_scoring: bool = False  # 是否启用特殊复盘评分（映射后虚高以解锁彩蛋）
    unlocks: Optional[str] = None  # 通关后解锁的隐藏汤 id
    win_condition: Optional[dict] = None  # 隐藏彩蛋汤的"通关条件"：命中即判定通关，结构见 ai_host.check_win_condition


# ===================== 请求 / 响应 =====================
class ChatRequest(BaseModel):
    soupId: Optional[str] = None
    sessionId: Optional[str] = None
    question: Optional[str] = None
    level: Optional[str] = None


class ChatCreateResponse(BaseModel):
    soupTitle: str
    soupSurface: str
    sessionId: str
    questionLimit: Optional[int] = None
    unlocks: Optional[str] = None  # 本汤通关后解锁的隐藏彩蛋汤 id


class ChatReplyResponse(BaseModel):
    reply: str
    isReveal: bool = False
    isGiveup: bool = False
    isWin: bool = False  # 命中隐藏彩蛋汤的通关条件
    sessionId: Optional[str] = None
    remaining: Optional[int] = None
    limitReached: bool = False
    isFreeReminder: bool = False


class EvaluateRequest(BaseModel):
    sessionId: str


class EvaluationResult(BaseModel):
    completion: int
    evaluation: str
    keyPointsCovered: List[str] = []
    keyPointsMissing: List[str] = []
    bottom: str = ""
    unlockSoupId: Optional[str] = None  # 通关后解锁的隐藏彩蛋汤 id


class FeedbackSubmit(BaseModel):
    """玩家提交的「主持人回答与汤底出入」反馈。

    字段顺序即前端表单顺序：先选汤，再填问的问题、主持人回答、应得正确答案、理由(选填)。
    """
    soupId: str  # 选中的汤 id（对应 /api/soups 返回的 id）
    question: str  # 玩家问的问题是什么
    hostAnswer: str  # 主持人实际回答的是什么
    expectedAnswer: str  # 玩家认为正确答案应该是什么
    reason: Optional[str] = None  # 理由（选填）


class FeedbackRecord(BaseModel):
    """玩家反馈的完整记录（含审批与合并状态）。"""

    model_config = ConfigDict(populate_by_name=True)
    id: str
    ts: str
    soupId: str
    soupTitle: Optional[str] = None
    question: str
    hostAnswer: str
    expectedAnswer: str
    reason: Optional[str] = None
    status: Literal["pending", "approved", "rejected"] = "pending"
    reviewedAt: Optional[str] = None
    mergedAt: Optional[str] = None
    mergedAnswer: Optional[str] = None  # 标准化后的答案（是/不是/是也不是/算是/与此无关）


class VerifiedQAPair(BaseModel):
    """管理员审批通过、已合并到主持人知识库的 QA 对。

    每晚 0 点由 merge_verified_qa.py 从 approved 反馈中生成，
    db.py 启动时读取并按 soupId 注入为 ConfusionPoint。
    """

    model_config = ConfigDict(populate_by_name=True)
    feedbackId: str
    soupId: str
    confusionPoint: ConfusionPoint
    mergedAt: str
