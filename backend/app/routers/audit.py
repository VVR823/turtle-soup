"""Independent admin credentials, no raw-text logs or arbitrary recovery paths."""
import base64
import math
import re
import time
from dataclasses import asdict

from fastapi import APIRouter, Depends, Header, Query, Request
from fastapi.responses import JSONResponse

from ..audit_events import AUDIT_EVENT_TYPES, AuditEventType, UUID_PATTERN
from ..audit_store import AuditPersistenceError
from ..baselines import canonical_json, strict_json
from ..rate_limit import rate_limit
from ..request_contract import StrictJSONRoute
from ..request_guards import GuardFailure, require_admin_token
from ..runtime import get_runtime


def _require_admin(x_admin_token: str | None = Header(None)):
    require_admin_token(x_admin_token, get_runtime().settings)


router = APIRouter(route_class=StrictJSONRoute, dependencies=[Depends(_require_admin)])
EventType = AuditEventType


def _invalid():
    raise GuardFailure(422, "audit_query_invalid", "审计查询格式或范围不符合要求。")


def encode_cursor(stamp, event_id, *, start, end, event_type):
    raw = canonical_json({"createdAt": float(stamp), "eventId": event_id,
        "start": float(start), "end": float(end), "eventType": event_type}).encode()
    return base64.urlsafe_b64encode(raw).decode().rstrip("=")


def decode_cursor(value):
    try:
        if not 1 <= len(value) <= 512 or not re.fullmatch(r"[A-Za-z0-9_-]+", value):
            raise ValueError("Invalid cursor characters")
        raw = base64.b64decode(value + "=" * (-len(value) % 4), altchars=b"-_", validate=True)
        fields = strict_json(raw.decode("utf-8"))
        if (type(fields) is not dict or set(fields) != {"createdAt", "eventId", "start", "end", "eventType"}
            or type(fields["createdAt"]) not in (int, float) or not math.isfinite(fields["createdAt"]) or fields["createdAt"] < 0
            or not isinstance(fields["eventId"], str) or not UUID_PATTERN.fullmatch(fields["eventId"])
            or any(type(fields[key]) not in (int, float) or not math.isfinite(fields[key]) or fields[key] < 0 for key in ("start", "end"))
            or not 0 <= fields["end"] - fields["start"] <= 31 * 86400
            or not fields["start"] <= fields["createdAt"] <= fields["end"]
            or fields["eventType"] is not None and fields["eventType"] not in AUDIT_EVENT_TYPES
            or encode_cursor(fields["createdAt"], fields["eventId"], start=fields["start"],
                end=fields["end"], event_type=fields["eventType"]) != value):
            raise ValueError("Noncanonical audit cursor")
        return fields
    except Exception:
        _invalid()


def _store():
    value = get_runtime().audit_store
    if value is None:
        raise AuditPersistenceError("Audit store unavailable")
    return value


@router.get("/api/audit/admin")
def list_audit(limit: int = Query(50, ge=1, le=100), start: float | None = None, end: float | None = None,
    cursor: str | None = Query(None, max_length=512), eventType: EventType | None = None,
    _rate: None = Depends(rate_limit(30, 60))):
    point = None
    if cursor is not None:
        fields = decode_cursor(cursor)
        if (start is not None and start != fields["start"] or end is not None and end != fields["end"]
            or eventType is not None and eventType != fields["eventType"]):
            _invalid()
        start, end, eventType = fields["start"], fields["end"], fields["eventType"]
        point = fields["createdAt"], fields["eventId"]
    end = time.time() if end is None else end
    start = end - 7 * 86400 if start is None else start
    if not all(math.isfinite(value) and value >= 0 for value in (start, end)) or not 0 <= end - start <= 31 * 86400:
        _invalid()
    events, more = _store().query_events(limit=limit, start=start, end=end, cursor=point, event_type=eventType)
    next_cursor = encode_cursor(events[-1].createdAt, events[-1].eventId,
        start=start, end=end, event_type=eventType) if more else None
    return {"events": [item.model_dump(mode="json") for item in events], "nextCursor": next_cursor}


@router.get("/api/audit/admin/status")
def audit_status(_rate: None = Depends(rate_limit(30, 60))):
    return asdict(_store().status())


@router.post("/api/audit/admin/recover")
async def recover_audit(request: Request, _rate: None = Depends(rate_limit(5, 60))):
    if request.query_params or await request.body():
        _invalid()  # No client-supplied paths, payloads, options, or defaults.
    report = await _store().recover(wait_ms=500)
    if report is None:
        return JSONResponse(status_code=202, content={"state": "pending", "persisted": False})
    return asdict(report)
