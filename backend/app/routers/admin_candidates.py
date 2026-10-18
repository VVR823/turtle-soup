"""Private human review actions; no player or model publication capability."""
from fastapi import APIRouter, Depends, Header, Request

from ..audit_events import CanonicalId
from ..candidate_review import CandidateReviewStore
from ..candidate_review_contracts import CandidateApprove, CandidateReject, CandidatePublish, CandidateRollback
from ..rate_limit import rate_limit
from ..request_contract import StrictJSONRoute
from ..request_guards import require_admin_token
from ..runtime import get_runtime


router = APIRouter(route_class=StrictJSONRoute)


def _admin(x_admin_token: str | None = Header(None)):
    require_admin_token(x_admin_token, get_runtime().settings)


@router.get("/api/feedback/admin/rule-candidates/{candidate_id}",
    dependencies=[Depends(_admin), Depends(rate_limit(30, 60))])
def detail(candidate_id: CanonicalId):
    return CandidateReviewStore(get_runtime()).detail(candidate_id).model_dump(mode="json")


@router.post("/api/feedback/admin/rule-candidates/{candidate_id}/approve",
    dependencies=[Depends(_admin), Depends(rate_limit(20, 60))])
def approve(candidate_id: CanonicalId, req: CandidateApprove, request: Request):
    request.scope["request_id"] = req.operationKey
    return CandidateReviewStore(get_runtime()).approve(candidate_id, req).model_dump(mode="json")


@router.post("/api/feedback/admin/rule-candidates/{candidate_id}/reject",
    dependencies=[Depends(_admin), Depends(rate_limit(20, 60))])
def reject(candidate_id: CanonicalId, req: CandidateReject, request: Request):
    request.scope["request_id"] = req.operationKey
    return CandidateReviewStore(get_runtime()).reject(candidate_id, req).model_dump(mode="json")


@router.post("/api/feedback/admin/rule-candidates/{candidate_id}/publish",
    dependencies=[Depends(_admin), Depends(rate_limit(20, 60))])
def publish(candidate_id: CanonicalId, req: CandidatePublish, request: Request):
    request.scope["request_id"] = req.operationKey
    return CandidateReviewStore(get_runtime()).publish(candidate_id, req).model_dump(mode="json")


@router.post("/api/feedback/admin/rule-releases/rollback",
    dependencies=[Depends(_admin), Depends(rate_limit(20, 60))])
def rollback(req: CandidateRollback, request: Request):
    request.scope["request_id"] = req.operationKey
    return CandidateReviewStore(get_runtime()).rollback(req).model_dump(mode="json")
