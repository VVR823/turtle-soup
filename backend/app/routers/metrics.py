"""Thin private aggregate routes; no startup or read-triggered migrations."""
import time

from fastapi import APIRouter, Depends, Header, Request
from fastapi.responses import Response

from ..metrics import export_metrics, query_metrics
from ..metrics_contracts import MetricsError, parse_metrics_query
from ..rate_limit import rate_limit
from ..request_contract import StrictJSONRoute
from ..request_guards import require_admin_token
from ..runtime import get_runtime


def _admin(x_admin_token: str | None = Header(None)):
    require_admin_token(x_admin_token, get_runtime().settings)


async def _empty_body(request: Request):
    if await request.body():
        raise MetricsError()


router = APIRouter(route_class=StrictJSONRoute, dependencies=[Depends(_admin), Depends(_empty_body)])


@router.get("/api/metrics/admin", dependencies=[Depends(rate_limit(30, 60))])
def metrics_page(request: Request):
    query = parse_metrics_query(list(request.query_params.multi_items()), now=time.time())
    page = query_metrics(get_runtime(), query)
    return Response(page.model_dump_json(warnings="error"), media_type="application/json",
        headers={"Cache-Control": "no-store"})


@router.get("/api/metrics/admin/export", dependencies=[Depends(rate_limit(5, 60))])
def metrics_export(request: Request):
    query = parse_metrics_query(list(request.query_params.multi_items()), now=time.time(), export=True)
    exported = export_metrics(get_runtime(), query)
    return Response(exported.model_dump_json(warnings="error"), media_type="application/json",
        headers={"Cache-Control": "no-store", "Content-Disposition": 'attachment; filename="turtle-soup-metrics.json"'})
