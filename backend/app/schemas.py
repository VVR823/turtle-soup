"""Pydantic 数据模型。

注意：响应模型的字段名故意使用 camelCase，以与现有 Next.js 前端的
约定（soupTitle / soupSurface / questionLimit / sessionId / isFreeReminder /
limitReached / keyPointsCovered / keyPointsMissing）保持一致，前端无需改动字段名。
"""
from typing import List, Literal, Optional, Union
from uuid import UUID, uuid4

from pydantic import BaseModel, ConfigDict, Field, StrictInt, StrictStr, field_validator, model_validator

# 主持人 5 种标准回答
AnswerType = Literal["是", "不是", "是也不是", "算是", "与此无关"]


class HostJudgment(BaseModel):
    """LLM 主持判定的结构化输出：先内部推理，再给最终 5 选 1 判定。

    用 JsonOutputParser 解析，避免模型自由文本里把推理和答案混在一起，
    也方便把 reasoning 与 answer 分离（answer 用于回复，reasoning 仅供调试）。
    """

    model_config = ConfigDict(extra="forbid", strict=True, frozen=True)
    reasoning: str = Field(
        max_length=1000,
        description="基于完整汤底事实的简短内部推理；只能引用汤底真相，不得向玩家透露汤底细节"
    )
    answer: AnswerType = Field(
        description="最终判定，只能从以下选一：是、不是、是也不是、算是、与此无关"
    )


HostKind = Literal["answer", "reminder", "system_error", "win"]
HostSource = Literal["deterministic", "llm", "flow", "legacy"]
ModelErrorCode = Literal[
    "model_timeout", "model_busy", "model_unavailable", "model_output_invalid",
    "model_policy_unknown", "model_auth", "model_quota", "model_transport_error",
    "model_cancelled", "model_cleanup_failed", "context_too_large",
]


HOST_ENGINE_VERSION = "host-v3"


class HostVersions(BaseModel):
    """Program-owned versions; the provider cannot select these."""
    model_config = ConfigDict(extra="forbid", strict=True, frozen=True)
    puzzleVersion: str = Field(default="unversioned", min_length=1)
    ruleVersion: str = Field(default="unversioned", min_length=1)
    engineVersion: str = Field(default=HOST_ENGINE_VERSION, min_length=1)
    normalizationVersion: str = Field(default="exact-v1", min_length=1)


class HostResult(BaseModel):
    """Authoritative business decision; display text grants no permissions."""
    model_config = ConfigDict(extra="forbid", strict=True, frozen=True)
    kind: HostKind
    answer: Optional[AnswerType] = None
    chargeable: bool
    source: HostSource
    evidenceIds: tuple[str, ...] = ()
    cacheHit: bool = False
    contextIndependent: bool = False
    versions: HostVersions = Field(default_factory=HostVersions)
    errorCode: Optional[ModelErrorCode] = None
    reply: str = Field(min_length=1, max_length=2000)
    matchedCheckpoint: Optional[str] = None

    @model_validator(mode="after")
    def consistent_decision(self):
        if self.kind == "answer":
            valid = self.answer is not None and self.chargeable and self.errorCode is None
            valid = valid and self.source in {"deterministic", "llm", "legacy"}
        elif self.kind == "system_error":
            valid = self.answer is None and not self.chargeable and self.errorCode is not None
            valid = valid and self.source in {"llm", "flow"}
        elif self.kind == "reminder":
            valid = self.answer is None and not self.chargeable and self.errorCode is None
            valid = valid and self.source in {"deterministic", "flow"}
        else:
            valid = self.answer is None and self.errorCode is None and self.source == "deterministic"
        if not valid:
            raise ValueError("Inconsistent host decision")
        return self

    def __getitem__(self, name):
        # Temporary compatibility for existing internal host tests/scripts.
        # No permissive provider dict conversion is provided.
        aliases = {
            "is_reveal": self.kind == "win", "is_giveup": False,
            "is_win": self.kind == "win", "matched_checkpoint": self.matchedCheckpoint,
        }
        if name in aliases:
            return aliases[name]
        if name in type(self).model_fields:
            return getattr(self, name)
        raise KeyError(name)

    def get(self, name, default=None):
        try:
            return self[name]
        except KeyError:
            return default


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
    match: Optional[List[str]] = None  # 旧诊断/检索提示；正则不授予在线答案权限
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
class RequestSceneError(ValueError):
    """A well-typed body does not describe either supported chat scene."""


class ChatRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")
    soupId: Optional[StrictStr] = Field(default=None, min_length=1, max_length=200)
    sessionId: Optional[StrictStr] = Field(default=None, min_length=1, max_length=200)
    question: Optional[StrictStr] = Field(default=None, min_length=1, max_length=500)
    level: Optional[StrictStr] = Field(default=None, max_length=50)
    requestId: UUID = Field(default_factory=uuid4)

    @field_validator("question", mode="before")
    @classmethod
    def trim_question(cls, value):
        return value.strip() if isinstance(value, str) else value

    def scene(self) -> Literal["create", "ask"]:
        if self.sessionId is None:
            if self.soupId is None or self.question is not None:
                raise RequestSceneError("Invalid create scene")
            return "create"
        if self.question is None or "level" in self.model_fields_set:
            raise RequestSceneError("Invalid ask scene")
        return "ask"


class ChatCreateResponse(BaseModel):
    soupTitle: str
    soupSurface: str
    sessionId: str
    questionLimit: Optional[int] = None
    unlocks: Optional[str] = None  # 本汤通关后解锁的隐藏彩蛋汤 id
    requestId: Optional[str] = None


class ChatReplyResponse(BaseModel):
    reply: str
    isReveal: bool = False
    isGiveup: bool = False
    isWin: bool = False  # 命中隐藏彩蛋汤的通关条件
    sessionId: Optional[str] = None
    remaining: Optional[int] = None
    limitReached: bool = False
    isFreeReminder: bool = False
    requestId: Optional[str] = None
    turnId: Optional[str] = None
    kind: Optional[HostKind] = None
    state: Optional[Literal["reserved", "completed", "failed", "expired"]] = None


class EvaluateRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")
    sessionId: StrictStr = Field(min_length=1, max_length=200)


class EvaluationResult(BaseModel):
    completion: int
    evaluation: str
    keyPointsCovered: List[str] = []
    keyPointsMissing: List[str] = []
    bottom: str = ""
    unlockSoupId: Optional[str] = None  # 通关后解锁的隐藏彩蛋汤 id
    verifiedCoverage: StrictInt | None = Field(default=None, ge=0, le=100)
    reconstructionScore: None = None
    scoreVersion: Literal["coverage-v1"] | None = None
    plotProgress: StrictInt | None = Field(default=None, ge=0, le=100)
    unknownTopics: List[str] = Field(default_factory=list)

    @model_validator(mode="after")
    def consistent_score(self):
        if self.scoreVersion == "coverage-v1":
            if self.verifiedCoverage is None or self.completion != self.verifiedCoverage:
                raise ValueError("New completion must equal verified coverage")
        elif self.verifiedCoverage is not None or self.plotProgress is not None or self.unknownTopics:
            raise ValueError("Unversioned legacy scores cannot claim new measurements")
        return self


class FeedbackSubmit(BaseModel):
    """玩家提交的「主持人回答与汤底出入」反馈。

    字段顺序即前端表单顺序：先选汤，再填问的问题、主持人回答、应得正确答案、理由(选填)。
    """
    model_config = ConfigDict(extra="forbid")
    soupId: StrictStr = Field(min_length=1, max_length=200)
    question: StrictStr = Field(min_length=1, max_length=500)
    hostAnswer: StrictStr = Field(min_length=1, max_length=100)
    expectedAnswer: StrictStr = Field(min_length=1, max_length=100)
    reason: Optional[StrictStr] = Field(default=None, max_length=2000)
    turnId: Optional[StrictStr] = Field(default=None, min_length=36, max_length=36,
        pattern=r"^[0-9a-f]{8}(?:-[0-9a-f]{4}){3}-[0-9a-f]{12}$")

    @field_validator("question", mode="before")
    @classmethod
    def trim_question(cls, value):
        return value.strip() if isinstance(value, str) else value


    @field_validator("soupId", "hostAnswer", "expectedAnswer")
    @classmethod
    def nonblank_feedback_required_fields(cls, value):
        if not value.strip():
            raise ValueError("Required feedback fields must contain meaningful text")
        # Preserve original meaningful claims, including surrounding whitespace.
        return value


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
