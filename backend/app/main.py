"""FastAPI 应用入口：海龟汤 AI 主持人后端。

路由：
  GET  /api/soups   —— 返回汤品列表（不含完整汤底）
  POST /api/chat    —— 创建会话 / 完整范围规则或上下文模型（限次、提醒/失败不扣次）
  POST /api/evaluate—— 根据本局问答自动评估完成度并公布汤底

前端（Next.js）通过 CORS 直连本服务（默认 :8000）。
"""
import logging
import re
import uuid
import asyncio
from contextlib import asynccontextmanager

from fastapi import APIRouter, Depends, FastAPI, HTTPException, Header, Request
from fastapi.responses import JSONResponse, Response
from fastapi.exceptions import RequestValidationError
from fastapi.middleware.cors import CORSMiddleware

from . import ai_host, config, db, trace_logger, game_service
from .feedback_contract import FeedbackError
from .agents.contracts import AgentError
from .metrics_contracts import MetricsError
from .post_publication_contracts import PostPublicationError
from .rate_limit import RatePolicy, rate_limit, rate_limits
from .request_guards import BodyLimitMiddleware, GuardFailure, require_admin_token, require_site_token
from .request_contract import StrictJSONRoute
from .request_lifecycle import run_request
from .runtime import Runtime, get_runtime, runtime_context
from .audit_store import AuditPersistenceError, AuditStore
from .audit_context import current_attempt
from .audit_events import BusinessDetails
from .audit_middleware import AuditMiddleware
from .schemas import (
    ChatCreateResponse,
    ChatReplyResponse,
    ChatRequest,
    EvaluateRequest,
    EvaluationResult,
    HostVersions,
    HostResult,
    RequestSceneError,
)

logger = logging.getLogger(__name__)


router = APIRouter(route_class=StrictJSONRoute)

LEVEL_KEYS = ["xuermu", "baozi", "tianyi"]

# 难度缺省/非法时的兜底档：取最严格档（xuermu 提问次数最少）。
# 题库里除 unlimited 彩蛋汤外，全部 65 道汤都定义了 difficultyLimits；
# 因此「没传 level」没有任何正当场景——旧实现会把 question_limit 留在 None（=不限次），
# 只要直接访问 /game/{id} 不带 level 参数就能绕过次数限制。这里改为 fail-closed。
DEFAULT_LEVEL = "xuermu"


# Legacy dictionaries stay inert. The Runtime-owned versioned LRU stores only
# pure source-bound rule decisions; never model/history/player responses.


def _cacheable_host(host) -> bool:
    """Compatibility diagnostic delegates to the real cache eligibility policy."""
    from .host_cache import is_cacheable
    return is_cacheable(host)


def _remaining(session: dict, asked: int):
    if session.get("questionLimit") is not None:
        return max(0, session["questionLimit"] - asked)
    return None


def _require_token(x_site_token: str | None = Header(None)):
    """访问口令闸门：设置了 SITE_PASSWORD 后，调用方必须在请求头带上一致的
    X-Site-Token，否则 401。主要用于保护 /api/chat 的付费 LLM 额度不被白嫖。
    未设置口令时（开发期）直接放行。
    """
    return require_site_token(x_site_token, get_runtime().settings)


def _require_admin(x_admin_token: str | None = Header(None)):
    """反馈管理后台闸门：与站点口令独立。调用 GET /api/feedback/admin 必须带
    一致的 X-Admin-Token，否则 401。玩家即便拿到站点口令也看不到全部反馈。
    未配置 ADMIN_TOKEN 时（不应发生）一律 503，避免误开放。
    """
    return require_admin_token(x_admin_token, get_runtime().settings)


@router.get("/api/config")
def app_config():
    """前端启动前先问：站点是否开启了访问口令（决定是否弹锁屏）。"""
    return {"siteLocked": bool(config.SITE_PASSWORD)}


@router.get("/api/soups")
def get_soups(
    q: str = None,
    unlocked: str = None,
    x_site_token: str | None = Header(None),
):
    """返回汤品列表（前端大厅与难度页使用；不暴露完整汤底）。

    可选参数 q：只按公开的标题/汤面/标签做子串检索。
    汤底和私密证据不能影响搜索结果，合法揭晓仍由 evaluate 提供。

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


@router.post("/api/chat", response_model=None)
def chat(
    req: ChatRequest,
    request: Request,
    x_site_token: str | None = Header(None),
    _rl: None = Depends(rate_limits((RatePolicy("minute", 30, 60), RatePolicy("hour", 300, 3600)))),
):
    request.scope["request_id"] = str(req.requestId)
    _require_token(x_site_token)
    try:
        scene = req.scene()
    except RequestSceneError:
        return JSONResponse(status_code=400, content={
            "detail": "请按开局或提问格式提交请求。", "code": "request_scene_invalid",
            "requestId": str(req.requestId),
        })
    if scene == "create":
        body = db.create_game_once(req.soupId, req.level, str(req.requestId))
        return Response(content=db.baselines.canonical_json(body), media_type="application/json")
    replay = game_service.ask(req)
    return Response(content=db.baselines.canonical_json(replay.safeResponse),
                    status_code=replay.httpStatus, media_type="application/json")


@router.get("/api/session/{session_id}/turns/{request_id}")
def turn_response_api(
    session_id: str, request_id: uuid.UUID,
    request: Request,
    x_site_token: str | None = Header(None),
    _rl: None = Depends(rate_limit(30, 60)),
):
    request.scope["request_id"] = str(request_id)
    _require_token(x_site_token)
    replay = db.get_turn_response(session_id, str(request_id))
    if replay is None:
        raise db.GameNotFound("turn_not_found")
    return Response(content=db.baselines.canonical_json(replay.safeResponse),
                    status_code=replay.httpStatus, media_type="application/json")


@router.post("/api/evaluate", response_model=EvaluationResult)
def evaluate(
    req: EvaluateRequest,
    x_site_token: str | None = Header(None),
    _rl_per_min: None = Depends(rate_limit(10, 60)),
):
    _require_token(x_site_token)
    return db.evaluate_once(req.sessionId, game_service.evaluate_snapshot)


@router.get("/api/session/{session_id}")
def get_session_api(
    session_id: str,
    x_site_token: str | None = Header(None),
    _rl: None = Depends(rate_limit(30, 60)),
):
    """按 sessionId 恢复一局进行中的游戏（刷新/重开页面后继续，不丢进度）。

    返回冻结汤面、剩余次数与问答历史；已揭晓局可恢复其保存的评估。
    进行中的局不返回汤底，损坏或不兼容的旧局安全拒绝。
    """
    _require_token(x_site_token)
    session = db.get_session(session_id)
    if not session:
        raise HTTPException(status_code=404, detail="会话不存在")
    db.require_compatible(session)
    soup = db.get_session_soup(session)
    if not soup:
        raise HTTPException(status_code=404, detail="汤品不存在")
    collector = current_attempt()
    if collector is not None:
        collector.bind_ids(session_id=session["id"])
        collector.observe_metadata(BusinessDetails(reasonCode="session_restored", versions=HostVersions(
            puzzleVersion=session["puzzleVersion"], ruleVersion=session["ruleVersion"],
            engineVersion="unversioned", normalizationVersion="unversioned"),
            trafficClass="test" if get_runtime().settings.TESTING else "real"))
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
        "status": session["status"],
        "puzzleVersion": session["puzzleVersion"],
        "ruleVersion": session["ruleVersion"],
        "ruleSuspended": session["ruleSuspended"],
        "evaluation": session["evaluation"],
    }


@router.get("/health")
def health():
    result = {"status": "ok", "soups": len(db.SOUPS)}
    runtime = get_runtime()
    if runtime.settings.TESTING:
        result.update(testing=True, provider=runtime.settings.LLM_PROVIDER,
                      instanceId=runtime.settings.TEST_INSTANCE_ID or runtime.instance_id)
    return result




@router.post("/api/feedback/admin/merge-verified")
def merge_verified_qa_endpoint(
    x_admin_token: str | None = Header(None),
):
    """Retired: no direct JSONL rule writes or service restarts."""
    _require_admin(x_admin_token)
    return JSONResponse(status_code=410, content={
        "detail": "旧规则合并入口已停用，后续使用版本化审批发布。",
        "code": "legacy_writer_disabled",
    })

class RuntimeMiddleware:
    """Pure ASGI context propagation includes FastAPI's sync worker threads."""

    def __init__(self, app, owner):
        self.app = app
        self.owner = owner
        self.cors = None
        self.runtime = None

    async def __call__(self, scope, receive, send):
        if scope["type"] not in ("http", "websocket"):
            await self.app(scope, receive, send)
            return
        runtime = self.owner.state.runtime
        if runtime is None or not runtime.initialized or runtime.closed:
            if scope["type"] == "websocket":
                await send({"type": "websocket.close", "code": 1013})
            else:
                await JSONResponse(
                    {"detail": "应用尚未启动", "code": "app_not_started"}, status_code=503,
                )(scope, receive, send)
            return
        if self.runtime is not runtime:
            self.cors = CORSMiddleware(
                BodyLimitMiddleware(self.app), allow_origins=runtime.settings.CORS_ORIGINS,
                allow_credentials=True, allow_methods=["*"], allow_headers=["*"],
                expose_headers=["Retry-After"],
            )
            self.runtime = runtime
        with runtime_context(runtime):
            async def guarded(request_scope, request_receive, request_send):
                await run_request(self.cors, request_scope, request_receive, request_send)
            await AuditMiddleware(guarded, runtime.audit_store, testing=runtime.settings.TESTING)(scope, receive, send)


def create_app(
    settings: config.Settings | None = None, *, model=None, soups=None, repair_corpus=None,
) -> FastAPI:
    """Pure factory. Files/config/resources are initialized only during lifespan."""

    @asynccontextmanager
    async def lifespan(application):
        selected = settings if settings is not None else config.load_settings()
        selected_model = model
        if selected.LLM_PROVIDER == "fake" and selected_model is None:
            from .testing import FakeModel
            selected_model = FakeModel()
        runtime = Runtime(selected, model=selected_model, soups=soups, repair_corpus=repair_corpus)
        application.state.runtime = runtime
        try:
            with runtime_context(runtime):
                db.initialize()
                def audit_connect():
                    with runtime_context(runtime):
                        return db._connect(timeout=0.25)
                runtime.audit_store = await asyncio.to_thread(AuditStore, runtime.settings.DATA_DIR, connect=audit_connect)
                runtime.audit_startup_recovery = await runtime.audit_store.recover(wait_ms=500)
                runtime.start_agent_worker()
            yield
        finally:
            await runtime.aclose()

    application = FastAPI(
        title="海龟汤 AI 主持人后端", version="1.0.0", lifespan=lifespan,
    )
    application.state.runtime = None

    @application.exception_handler(MetricsError)
    async def metrics_failure(_request, error):
        details = {
            "metrics_query_invalid": "统计查询格式或范围不符合要求，请修改后重试。",
            "metrics_busy": "统计暂时繁忙，请稍后重试。",
            "metrics_unavailable": "统计暂时不可用；旧数据库需要管理员显式完成004迁移，请勿在查询时自动升级。",
            "metrics_export_too_large": "完整导出超过上限，请缩小时间、题目或版本范围。",
        }
        return JSONResponse(status_code=error.status, headers={"Cache-Control": "no-store"},
            content={"detail": details.get(error.code, "统计暂时不可用，请稍后重试。"), "code": error.code})

    @application.exception_handler(AuditPersistenceError)
    async def audit_unavailable(request, _error):
        return JSONResponse(status_code=503, content={
            "detail": "这次操作暂时无法安全保存，请同步进度后重试。", "code": "audit_unavailable",
            "requestId": request.scope.get("request_id") or str(uuid.uuid4()),
        })

    @application.exception_handler(GuardFailure)
    async def guarded_request(request, error):
        headers = dict(error.headers or {})
        if request.scope.get("path") in {"/api/metrics/admin", "/api/metrics/admin/export"}:
            headers["Cache-Control"] = "no-store"
        return JSONResponse(status_code=error.status_code, headers=headers, content={
            "detail": error.detail, "code": error.code,
            "requestId": request.scope.get("request_id") or str(uuid.uuid4()),
        })

    @application.exception_handler(FeedbackError)
    async def feedback_failure(request, error):
        return JSONResponse(status_code=error.status, content={
            "detail": "反馈状态或输入已变化，请刷新后核对；暂时无法保存时可稍后重试。",
            "code": error.code, "requestId": request.scope.get("request_id") or str(uuid.uuid4()),
        })

    @application.exception_handler(PostPublicationError)
    async def observation_failure(request, error):
        return JSONResponse(status_code=error.status, headers={'Cache-Control': 'no-store'}, content={
            'detail': '发布后复查暂时无法安全完成，请核对来源或稍后重试；已有计划不会自动重跑。',
            'code': error.code, 'requestId': request.scope.get('request_id') or str(uuid.uuid4()),
        })

    @application.exception_handler(AgentError)
    async def agent_failure(request, error):
        return JSONResponse(status_code=error.status, content={
            "detail": "任务状态或权限已变化，请刷新核对；暂时不可用时可稍后重试。",
            "code": error.code, "requestId": request.scope.get("request_id") or str(uuid.uuid4()),
        })

    @application.exception_handler(db.GameConflict)
    async def game_conflict(request, error):
        return JSONResponse(status_code=409, content={
            "detail": "这局游戏状态已变化，请同步进度后再操作。", "code": error.code,
            "requestId": request.scope.get("request_id") or str(uuid.uuid4()),
        })

    @application.exception_handler(db.GameNotFound)
    async def game_not_found(request, _error):
        return JSONResponse(status_code=404, content={"detail": "游戏或请求不存在。", "code": "game_not_found",
                                                   "requestId": request.scope.get("request_id") or str(uuid.uuid4())})

    @application.exception_handler(RequestValidationError)
    async def invalid_request(_request, _error):
        # FastAPI's default error body can echo the original player text.
        return JSONResponse(status_code=422, content={
            "detail": "请求字段格式或长度不符合要求。", "code": "request_validation_error",
            "requestId": str(uuid.uuid4()),
        })

    @application.exception_handler(db.SessionCompatibilityError)
    async def incompatible_session(_request, _error):
        return JSONResponse(status_code=410, content={
            "detail": "这局旧游戏无法可靠恢复，历史已保留，请联系管理员核对。",
            "code": "legacy_session_incompatible",
        })

    @application.exception_handler(db.baselines.SnapshotError)
    async def invalid_snapshot(request, _error):
        return JSONResponse(status_code=503, content={
            "detail": "游戏版本暂时不可用，请稍后重试。", "code": "snapshot_unavailable",
            "requestId": request.scope.get("request_id") or str(uuid.uuid4()),
        })

    application.add_middleware(RuntimeMiddleware, owner=application)
    application.include_router(router)
    from .routers.audit import router as audit_router
    application.include_router(audit_router)
    from .routers.feedback import router as feedback_router
    application.include_router(feedback_router)
    from .routers.agent_runs import router as agent_router
    application.include_router(agent_router)
    from .routers.admin_candidates import router as candidate_router
    application.include_router(candidate_router)
    from .routers.admin_regressions import router as observation_router
    application.include_router(observation_router)
    from .routers.metrics import router as metrics_router
    application.include_router(metrics_router)
    return application


# Keep uvicorn app.main:app compatible, but importing it performs no data I/O.
app = create_app()
