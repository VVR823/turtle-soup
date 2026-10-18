"""Private bounded run intent/status/cancel; never review or publication."""
from fastapi import APIRouter, Depends, Header, Query, Request

from ..agents.admin_contracts import AgentStart, AgentCancel
from ..agents.contracts import AgentError
from ..audit_events import CanonicalId
from ..rate_limit import rate_limit
from ..request_contract import StrictJSONRoute
from ..request_guards import require_admin_token
from ..runtime import get_runtime
from ..task_context import TOOLS

router = APIRouter(route_class=StrictJSONRoute)
_TOOLS = tuple(sorted(TOOLS))


def _admin(x_admin_token: str | None = Header(None)):
    require_admin_token(x_admin_token, get_runtime().settings)


def _worker(*, admitting=False):
    active = get_runtime()
    if not active.settings.ENABLE_AGENT or active.agent_worker is None:
        raise AgentError("agent_disabled", 503)
    worker = active.agent_worker
    if admitting and worker.snapshot().admissionClosed:
        raise AgentError("agent_unavailable", 503)
    return worker


@router.get("/api/feedback/admin/agent-runs",
    dependencies=[Depends(_admin), Depends(rate_limit(30, 60))])
def list_runs(limit: int = Query(50, ge=1, le=100), start: float | None = None, end: float | None = None,
    cursor: str | None = Query(None, max_length=512), feedbackId: CanonicalId | None = None):
    from ..candidate_review import CandidateReviewStore
    return CandidateReviewStore(get_runtime()).list_runs(limit=limit, start=start, end=end,
        cursor=cursor, feedback_id=feedbackId).model_dump(mode="json")


@router.post("/api/feedback/admin/agent-runs", status_code=202,
    dependencies=[Depends(_admin), Depends(rate_limit(20, 60))])
def start(req: AgentStart, request: Request):
    request.scope["request_id"] = req.requestId
    worker = _worker(admitting=True)
    run = worker.store.create(request_id=req.requestId, feedback_id=req.feedbackId,
        expected_feedback_version=req.expectedFeedbackVersion, allowed_tools=_TOOLS,
        suite_manifest_digest=worker.agent.executor.regression.suite_manifest_digest)
    # Stable acknowledgement even if an idempotent retry sees progressed state.
    return {"runId": run.id}


@router.get("/api/feedback/admin/agent-runs/{run_id}",
    dependencies=[Depends(_admin), Depends(rate_limit(30, 60))])
def status(run_id: CanonicalId):
    return _worker().store.read_status(run_id).model_dump(mode="json")


@router.post("/api/feedback/admin/agent-runs/{run_id}/cancel",
    dependencies=[Depends(_admin), Depends(rate_limit(20, 60))])
def cancel(run_id: CanonicalId, req: AgentCancel):
    return _worker().store.cancel(run_id, expected_row_version=req.expectedRowVersion).model_dump(mode="json")
