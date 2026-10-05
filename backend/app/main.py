"""FastAPI 应用入口：海龟汤 AI 主持人后端。

路由：
  GET  /api/soups   —— 返回汤品列表（不含完整汤底）
  POST /api/chat    —— 创建会话 / 处理提问（含限次、非是否类不扣次、confusionPoints→RAG→LLM）
  POST /api/evaluate—— 根据本局问答自动评估完成度并公布汤底

前端（Next.js）通过 CORS 直连本服务（默认 :8000）。
"""
import json
import logging
import os
import re
import uuid
from datetime import datetime, timezone

from fastapi import Depends, FastAPI, HTTPException, Header
from fastapi.middleware.cors import CORSMiddleware

from . import ai_host, config, db, rag, trace_logger
from .feedback_utils import normalize_expected_answer
from .rate_limit import rate_limit
from .schemas import (
    ChatCreateResponse,
    ChatReplyResponse,
    ChatRequest,
    EvaluateRequest,
    EvaluationResult,
    FeedbackSubmit,
)

logger = logging.getLogger(__name__)

# 反馈落盘路径：backend/data/feedback.jsonl（每行一条 JSON 记录）
FEEDBACK_PATH = os.path.join(os.path.dirname(__file__), "..", "data", "feedback.jsonl")
VERIFIED_QA_PATH = os.path.join(os.path.dirname(__file__), "..", "data", "verified_qa_pairs.jsonl")


def _load_feedback_records() -> list[dict]:
    """读取全部反馈记录；解析失败的行会被跳过。"""
    records = []
    if not os.path.exists(FEEDBACK_PATH):
        return records
    with open(FEEDBACK_PATH, "r", encoding="utf-8") as f:
        for line in f:
            line = line.strip()
            if not line:
                continue
            try:
                records.append(json.loads(line))
            except json.JSONDecodeError:
                continue
    return records


def _save_feedback_records(records: list[dict]) -> None:
    """原子写回反馈文件（临时文件 + rename），避免并发覆盖丢数据。"""
    os.makedirs(os.path.dirname(FEEDBACK_PATH), exist_ok=True)
    tmp_path = FEEDBACK_PATH + ".tmp"
    with open(tmp_path, "w", encoding="utf-8") as f:
        for r in records:
            f.write(json.dumps(r, ensure_ascii=False) + "\n")
    os.replace(tmp_path, FEEDBACK_PATH)



app = FastAPI(title="海龟汤 AI 主持人后端", version="1.0.0")

app.add_middleware(
    CORSMiddleware,
    allow_origins=config.CORS_ORIGINS,
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

LEVEL_KEYS = ["xuermu", "baozi", "tianyi"]

# 难度缺省/非法时的兜底档：取最严格档（xuermu 提问次数最少）。
# 题库里除 unlimited 彩蛋汤外，全部 65 道汤都定义了 difficultyLimits；
# 因此「没传 level」没有任何正当场景——旧实现会把 question_limit 留在 None（=不限次），
# 只要直接访问 /game/{id} 不带 level 参数就能绕过次数限制。这里改为 fail-closed。
DEFAULT_LEVEL = "xuermu"


# ===================== 主持人回答缓存 =====================
# 海龟汤真相固定：同一道汤、同一句问法，判定结果是恒定的（是/不是/是也不是/算是/与此无关）。
# 进程内缓存 (soupId, 归一化问句) -> host 判定结果：命中直接返回，完全跳过 LLM 调用，
# 大幅降低重复问句的响应延迟。判定逻辑本身一字未动（handle_host_response 原样执行后缓存）。
# 不缓存三类：
#   - 问进度类（matched_checkpoint=progress_hint）：答案依赖本局历史，不能跨会话复用；
#   - LLM 报错类（reply 以 🤖 开头）：临时故障，缓存会固化错误；
#   - LLM 兜底类（matched_checkpoint=None 且 reply 非提醒前缀）：LLM 是带着本局历史
#     （session messages）判定的，同一句话在不同上下文下结论可能不同，跨会话复用会串答；
#     只缓存确定性分支（易错点/复合/类型/人数/RAG/彩蛋等，结果与历史无关）。
# 注意：缓存随进程重启清空；若未来改了某道汤的易错点/汤底，需重启后端使缓存失效。
_HOST_CACHE_MAX = 10000  # 上限：超过后清空重建，避免长期运行内存无限增长
_host_cache: dict = {}


def _norm_q(question: str) -> str:
    """缓存键用的问题归一化：小写 + 标点/空白折叠，让「X死了吗」「X死了吗？」「x 死了 吗」命中同一键。"""
    return rag.normalize_question(question)


def _cacheable_host(host: dict) -> bool:
    """是否允许进入缓存。仅缓存『结果与本局历史无关』的确定性判定。"""
    if not host or not host.get("reply"):
        return False
    if host.get("matched_checkpoint") == "progress_hint":
        return False
    if str(host["reply"]).startswith("🤖"):
        return False
    # LLM 兜底（无确定性 checkpoint 命中）：判定依赖本局历史，不缓存，避免跨会话串答。
    if host.get("matched_checkpoint") is None and not str(host["reply"]).startswith(("🤔", "🎯", "⚠️")):
        return False
    return True


def _remaining(session: dict, asked: int):
    if session.get("questionLimit") is not None:
        return max(0, session["questionLimit"] - asked)
    return None


def _require_token(x_site_token: str | None = Header(None)):
    """访问口令闸门：设置了 SITE_PASSWORD 后，调用方必须在请求头带上一致的
    X-Site-Token，否则 401。主要用于保护 /api/chat 的付费 LLM 额度不被白嫖。
    未设置口令时（开发期）直接放行。
    """
    if config.SITE_PASSWORD and x_site_token != config.SITE_PASSWORD:
        raise HTTPException(status_code=401, detail="需要访问口令")


def _require_admin(x_admin_token: str | None = Header(None)):
    """反馈管理后台闸门：与站点口令独立。调用 GET /api/feedback/admin 必须带
    一致的 X-Admin-Token，否则 401。玩家即便拿到站点口令也看不到全部反馈。
    未配置 ADMIN_TOKEN 时（不应发生）一律 503，避免误开放。
    """
    if not config.ADMIN_TOKEN:
        raise HTTPException(status_code=503, detail="管理口令未配置")
    if x_admin_token != config.ADMIN_TOKEN:
        raise HTTPException(status_code=401, detail="管理口令错误")


@app.get("/api/config")
def app_config():
    """前端启动前先问：站点是否开启了访问口令（决定是否弹锁屏）。"""
    return {"siteLocked": bool(config.SITE_PASSWORD)}


@app.get("/api/soups")
def get_soups(
    q: str = None,
    unlocked: str = None,
    x_site_token: str | None = Header(None),
):
    """返回汤品列表（前端大厅与难度页使用；不暴露完整汤底）。

    可选参数 q：按 标题/汤面/标签/汤底摘要/完整汤底 做子串检索，
    新收录的汤进入 SOUPS 后自动可被搜到。

    可选参数 unlocked：逗号分隔的已解锁隐藏汤 id，用于在首页显示彩蛋汤。
    """
    _require_token(x_site_token)
    unlocked_ids = set()
    if unlocked:
        unlocked_ids = {u.strip() for u in unlocked.split(",") if u.strip()}
    soups = db.get_all_soups(q=q, unlocked_ids=unlocked_ids)
    return {
        "soups": [
            {
                "id": s.id,
                "title": s.title,
                "surface": s.surface,
                "tags": s.tags,
                "difficulty": s.difficulty,
                "source": s.source,
                "difficultyLimits": (s.difficultyLimits.model_dump() if s.difficultyLimits else None),
                "hidden": s.hidden,
                "unlimited": s.unlimited,
            }
            for s in soups
        ]
    }


@app.post("/api/chat", response_model=None)
def chat(
    req: ChatRequest,
    x_site_token: str | None = Header(None),
    # 限流：每 IP 每分钟 30 次 / 每小时 300 次（防刷 LLM 额度；正常玩家一局几十问足够）
    _rl_per_min: None = Depends(rate_limit(30, 60)),
    _rl_per_hour: None = Depends(rate_limit(300, 3600)),
):
    _require_token(x_site_token)
    # 场景1：创建新会话（没有 sessionId）
    if not req.sessionId and req.soupId:
        soup = db.get_soup_by_id(req.soupId)
        if not soup:
            raise HTTPException(status_code=404, detail=f"汤品 {req.soupId} 不存在")

        question_limit = None
        if not soup.unlimited and soup.difficultyLimits:
            # level 合法则用玩家所选难度；缺省或非法（如 ?level=abc）一律回退到最严格档，
            # 绝不放行成「不限次」——否则省略 level 即可无限提问。
            if req.level in LEVEL_KEYS:
                level = req.level
            else:
                level = DEFAULT_LEVEL
                if req.level:
                    logger.warning(
                        "非法 level 参数 %r（soup=%s），已回退到最严格档 %s",
                        req.level, req.soupId, DEFAULT_LEVEL,
                    )
            question_limit = getattr(soup.difficultyLimits, level)
        # unlimited 彩蛋汤强制不限次

        session = db.create_session(req.soupId, question_limit)
        return ChatCreateResponse(
            soupTitle=soup.title,
            soupSurface=soup.surface,
            sessionId=session["id"],
            questionLimit=session["questionLimit"],
            unlocks=soup.unlocks,
        )

    # 场景2：已有会话，发送问题
    if not req.sessionId or not req.question:
        raise HTTPException(status_code=400, detail="请提供 sessionId 和 question")

    session = db.get_session(req.sessionId)
    if not session:
        raise HTTPException(status_code=404, detail="会话不存在")
    if session["status"] != "playing":
        raise HTTPException(status_code=400, detail="游戏已结束，请重新开始")

    # 防止旧版手动输入/放弃指令消耗提问次数（统一走「揭晓答案」按钮）
    if re.match(
        r"^(我猜出答案了|我猜到了|我知道了|我放弃了|告诉我答案|看汤底|揭晓真相|跳过|不玩了)",
        req.question.strip(),
    ):
        cur = db.get_session(session["id"])
        asked = cur["questionsAsked"] if cur else session["questionsAsked"]
        return ChatReplyResponse(
            reply="请点击左侧「🏁 揭晓答案」按钮，AI 会根据本局问答自动评估完成度并公布汤底。",
            isReveal=False,
            isGiveup=False,
            sessionId=session["id"],
            isFreeReminder=True,
            remaining=_remaining(session, asked),
        )

    # 提问次数上限校验（难度档限制）
    if session.get("questionLimit") is not None and session["questionsAsked"] >= session["questionLimit"]:
        return ChatReplyResponse(
            reply="❌ 本局提问次数已用完，正在揭晓真相……",
            isReveal=False,
            isGiveup=False,
            limitReached=True,
            remaining=0,
        )

    soup = db.get_soup_by_id(session["soupId"])
    if not soup:
        # 汤可能后续从题库移除，旧会话仍在 → 明确提示而非 500
        raise HTTPException(status_code=404, detail="这道汤已下架，请返回大厅重新选择")

    # 回答缓存：同汤同问句直接复用上次判定（命中即跳过 LLM，判定逻辑不变）
    cache_key = (session["soupId"], _norm_q(req.question))
    cached = _host_cache.get(cache_key)
    if cached is not None:
        host = cached
    else:
        host = ai_host.handle_host_response(soup, session["messages"], req.question.strip())
        # 运行 trace：记录本次判定走的分支与最终答案（不侵入判定逻辑，失败静默）
        trace_logger.record(session["id"], session["soupId"], req.question.strip(), host)
        if _cacheable_host(host):
            # 容量上限：超过后清空重建（简单粗暴但有效，避免内存无限增长）
            if len(_host_cache) >= _HOST_CACHE_MAX:
                _host_cache.clear()
            _host_cache[cache_key] = host

    # 非是否类问题 / 游戏流程兜底 / LLM 服务异常 → 只提醒不扣次数，但保存记录供复盘/审查。
    # 🤖 前缀 = LLM 报错（走神/额度/未启动），玩家可直接重发同一问题，不能白扣次数。
    is_free = (
        host["reply"].startswith("🤔")
        or host["reply"].startswith("🎯")
        or host["reply"].startswith("⚠️")
        or host["reply"].startswith("🤖")
    )
    if is_free:
        db.save_message(session["id"], "user", req.question, is_free_reminder=True)
        db.save_message(session["id"], "host", host["reply"], is_free_reminder=True)
        cur = db.get_session(session["id"])
        asked = cur["questionsAsked"] if cur else session["questionsAsked"]
        return ChatReplyResponse(
            reply=host["reply"],
            isReveal=False,
            isGiveup=False,
            sessionId=session["id"],
            isFreeReminder=True,
            remaining=_remaining(session, asked),
        )

    # 保存对话（正常提问才保存+计数）
    db.save_message(session["id"], "user", req.question)
    db.save_message(session["id"], "host", host["reply"])

    updated = db.get_session(session["id"])
    asked = updated["questionsAsked"] if updated else session["questionsAsked"]

    return ChatReplyResponse(
        reply=host["reply"],
        isReveal=host["is_reveal"],
        isGiveup=host["is_giveup"],
        isWin=host.get("is_win", False),
        sessionId=session["id"],
        remaining=_remaining(session, asked),
    )


@app.post("/api/evaluate", response_model=EvaluationResult)
def evaluate(
    req: EvaluateRequest,
    x_site_token: str | None = Header(None),
    # 揭晓频率低：每 IP 每分钟 10 次足够（正常玩家不会一分钟揭晓十次）
    _rl_per_min: None = Depends(rate_limit(10, 60)),
):
    _require_token(x_site_token)
    if not req.sessionId:
        raise HTTPException(status_code=400, detail="请提供 sessionId")
    session = db.get_session(req.sessionId)
    if not session:
        raise HTTPException(status_code=404, detail="会话不存在")
    soup = db.get_soup_by_id(session["soupId"])
    if not soup:
        raise HTTPException(status_code=404, detail="汤品不存在")

    qa_text = "\n".join(
        f"{'玩家' if m['role'] == 'user' else '主持人'}：{m['content']}"
        for m in session["messages"]
        if m["role"] in ("user", "host")
    )

    eval_result = ai_host.evaluate_completion(soup, qa_text, messages=session.get("messages", []))
    db.update_session_status(req.sessionId, "given_up")

    unlock_soup_id = None
    if soup.unlocks and eval_result.get("unlockThresholdReached"):
        unlock_soup_id = soup.unlocks

    return EvaluationResult(
        completion=eval_result["completion"],
        evaluation=eval_result["evaluation"],
        keyPointsCovered=eval_result["keyPointsCovered"],
        keyPointsMissing=eval_result["keyPointsMissing"],
        bottom=soup.bottom,
        unlockSoupId=unlock_soup_id,
    )


@app.get("/api/session/{session_id}")
def get_session_api(
    session_id: str,
    x_site_token: str | None = Header(None),
    _rl: None = Depends(rate_limit(30, 60)),
):
    """按 sessionId 恢复一局进行中的游戏（刷新/重开页面后继续，不丢进度）。

    返回汤面、剩余次数与完整问答历史；已结束或已下架的会话返回 4xx，前端据此开新局。
    """
    _require_token(x_site_token)
    session = db.get_session(session_id)
    if not session:
        raise HTTPException(status_code=404, detail="会话不存在")
    if session["status"] != "playing":
        raise HTTPException(status_code=400, detail="游戏已结束")
    soup = db.get_soup_by_id(session["soupId"])
    if not soup:
        raise HTTPException(status_code=404, detail="汤品不存在")
    return {
        "sessionId": session["id"],
        "soupId": session["soupId"],
        "soupTitle": soup.title,
        "soupSurface": soup.surface,
        "unlocks": soup.unlocks,
        "questionLimit": session["questionLimit"],
        "questionsAsked": session["questionsAsked"],
        "remaining": _remaining(session, session["questionsAsked"]),
        "messages": session["messages"],
    }


@app.get("/health")
def health():
    return {"status": "ok", "soups": len(db.SOUPS)}


@app.post("/api/feedback")
def submit_feedback(
    req: FeedbackSubmit,
    x_site_token: str | None = Header(None),
    # 反馈低频：每 IP 每分钟 20 次足够（防刷文件写入）
    _rl: None = Depends(rate_limit(20, 60)),
):
    """玩家提交「主持人回答与汤底出入」的 bug 反馈。

    落盘到 backend/data/feedback.jsonl（追加写入，每行一条 JSON），
    管理员可 SSH 登录后直接 cat 该文件查看。不返回历史列表，避免玩家凭令牌拉取全部反馈。
    """
    _require_token(x_site_token)
    if not req.soupId or not req.question.strip() or not req.hostAnswer.strip() or not req.expectedAnswer.strip():
        raise HTTPException(status_code=400, detail="请完整填写：选汤、你问的问题、主持人回答、你认为正确答案")
    soup = db.get_soup_by_id(req.soupId)
    record = {
        "id": str(uuid.uuid4()),
        "ts": datetime.now(timezone.utc).isoformat(),
        "soupId": req.soupId,
        "soupTitle": soup.title if soup else None,
        "question": req.question.strip(),
        "hostAnswer": req.hostAnswer.strip(),
        "expectedAnswer": req.expectedAnswer.strip(),
        "reason": (req.reason or "").strip() or None,
        "status": "pending",
    }
    os.makedirs(os.path.dirname(FEEDBACK_PATH), exist_ok=True)
    with open(FEEDBACK_PATH, "a", encoding="utf-8") as f:
        f.write(json.dumps(record, ensure_ascii=False) + "\n")
    return {"ok": True, "id": record["id"]}


@app.get("/api/feedback/admin")
def list_feedback_admin(
    x_admin_token: str | None = Header(None),
):
    """管理员查看全部玩家反馈（需独立的 X-Admin-Token，与站点口令无关）。

    返回倒序（新提交在前）的反馈列表，供后台网页查看。玩家即便持有站点口令
    也无法调用此接口——必须同时知道 ADMIN_TOKEN。
    """
    _require_admin(x_admin_token)
    records = _load_feedback_records()
    # 按提交时间倒序（新在前）
    records.sort(key=lambda r: r.get("ts", ""), reverse=True)
    return {"total": len(records), "feedbacks": records}


@app.post("/api/feedback/admin/{feedback_id}/approve")
def approve_feedback(
    feedback_id: str,
    x_admin_token: str | None = Header(None),
):
    """管理员审批通过一条反馈。通过后会进入每晚 0 点的自动合并流程。"""
    _require_admin(x_admin_token)
    records = _load_feedback_records()
    found = False
    for r in records:
        if r.get("id") == feedback_id:
            if r.get("status") == "approved":
                raise HTTPException(status_code=400, detail="该反馈已经审批通过")
            r["status"] = "approved"
            r["reviewedAt"] = datetime.now(timezone.utc).isoformat()
            found = True
            break
    if not found:
        raise HTTPException(status_code=404, detail="反馈不存在")
    _save_feedback_records(records)
    return {"ok": True}


@app.post("/api/feedback/admin/{feedback_id}/reject")
def reject_feedback(
    feedback_id: str,
    x_admin_token: str | None = Header(None),
):
    """管理员拒绝一条反馈。拒绝后不会合并到主持人知识库。"""
    _require_admin(x_admin_token)
    records = _load_feedback_records()
    found = False
    for r in records:
        if r.get("id") == feedback_id:
            if r.get("status") == "rejected":
                raise HTTPException(status_code=400, detail="该反馈已经拒绝")
            r["status"] = "rejected"
            r["reviewedAt"] = datetime.now(timezone.utc).isoformat()
            found = True
            break
    if not found:
        raise HTTPException(status_code=404, detail="反馈不存在")
    _save_feedback_records(records)
    return {"ok": True}


@app.post("/api/feedback/admin/merge-verified")
def merge_verified_qa_endpoint(
    x_admin_token: str | None = Header(None),
):
    """手动触发已批准反馈的合并（生成 verified_qa_pairs.jsonl）。

    主要用于测试；生产环境由每晚 0 点的 crontab 自动调用。
    """
    _require_admin(x_admin_token)
    from .scripts import merge_verified_qa as merger

    count = merger.run_merge(FEEDBACK_PATH, VERIFIED_QA_PATH)
    return {"ok": True, "merged": count}
