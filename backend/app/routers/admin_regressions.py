"""Explicit private observations; no game hook, Agent tool or background job."""
from fastapi import APIRouter, Depends, Header, Request
from fastapi.responses import Response

from ..post_publication_contracts import ObservationReceipt
from ..post_publication_regression import ObservationRequest, PostPublicationRegression
from ..rate_limit import rate_limit
from ..request_contract import StrictJSONRoute
from ..request_guards import require_admin_token
from ..runtime import get_runtime

router = APIRouter(route_class=StrictJSONRoute)


def _admin(x_admin_token: str | None = Header(None)):
    require_admin_token(x_admin_token, get_runtime().settings)


@router.post('/api/feedback/admin/post-publication-regressions',
    dependencies=[Depends(_admin), Depends(rate_limit(5, 60))])
def observe(req: ObservationRequest, request: Request):
    request.scope['request_id'] = req.operationKey
    record = PostPublicationRegression(get_runtime()).run(req)
    receipt = ObservationReceipt(plan=record.plan, result=record.result, state=record.state)
    return Response(receipt.model_dump_json(warnings='error'), media_type='application/json',
        headers={'Cache-Control': 'no-store'})
