"""Private bounded CAS feedback API; no runtime JSONL or publication route."""
from fastapi import APIRouter, Depends, Header, Query

from .. import baselines, feedback_store
from ..feedback_contract import FeedbackReview, PrivacyReview, RowVersion
from ..rate_limit import rate_limit
from ..request_contract import StrictJSONRoute
from ..request_guards import require_admin_token, require_site_token
from ..runtime import get_runtime
from ..schemas import FeedbackSubmit


def _site(x_site_token: str | None = Header(None)):
    require_site_token(x_site_token, get_runtime().settings)


def _admin(x_admin_token: str | None = Header(None)):
    require_admin_token(x_admin_token, get_runtime().settings)


class FeedbackPrivacyReview(PrivacyReview):
    expectedRowVersion: RowVersion


router = APIRouter(route_class=StrictJSONRoute)


@router.post("/api/feedback", dependencies=[Depends(_site), Depends(rate_limit(20, 60))])
def submit_feedback(req: FeedbackSubmit):
    value = feedback_store.submit_feedback(req)
    return {"ok": True, "id": value.id}


@router.get("/api/feedback/admin", dependencies=[Depends(_admin), Depends(rate_limit(30, 60))])
def list_feedback(limit: int = Query(50, ge=1, le=100), start: float | None = None, end: float | None = None,
    cursor: str | None = Query(None, max_length=512), status: str | None = None,
    soupId: str | None = Query(None, min_length=1, max_length=200)):
    return feedback_store.list_feedback(limit=limit, start=start, end=end, cursor=cursor, status=status,
        soup_id=soupId).model_dump(mode="json")


@router.post("/api/feedback/admin/{feedback_id}/approve", dependencies=[Depends(_admin), Depends(rate_limit(20, 60))])
def approve_feedback(feedback_id: str, req: FeedbackReview):
    value = feedback_store.review_feedback(feedback_id, req.expectedRowVersion, status="approved")
    return {"ok": True, "feedback": value.model_dump(mode="json")}


@router.post("/api/feedback/admin/{feedback_id}/reject", dependencies=[Depends(_admin), Depends(rate_limit(20, 60))])
def reject_feedback(feedback_id: str, req: FeedbackReview):
    value = feedback_store.review_feedback(feedback_id, req.expectedRowVersion, status="rejected")
    return {"ok": True, "feedback": value.model_dump(mode="json")}


@router.post("/api/feedback/admin/{feedback_id}/privacy", dependencies=[Depends(_admin), Depends(rate_limit(20, 60))])
def privacy_review(feedback_id: str, req: FeedbackPrivacyReview):
    review = PrivacyReview.model_validate_json(baselines.canonical_json(req.model_dump(mode="json", exclude={"expectedRowVersion"})))
    value = feedback_store.set_model_permission(feedback_id, req.expectedRowVersion, review=review)
    return {"ok": True, "feedback": value.model_dump(mode="json")}
