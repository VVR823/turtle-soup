"""Short SQLite feedback transactions. Original text stays private in payloads."""
import base64
import math
import re
import time
from contextlib import contextmanager
from datetime import datetime, timezone
from uuid import NAMESPACE_URL, uuid4, uuid5

from pydantic import ValidationError

from . import audit_store, baselines, db
from .audit_events import AuditEvent, FeedbackBusinessDetails, UUID_PATTERN
from .feedback_contract import FeedbackError, FeedbackPage, FeedbackReview, FeedbackView, PrivacyRecord, PrivacyReview, SanitizedInput
from .migrations import CHECKSUM_002
from .runtime import get_runtime
from .schemas import FeedbackSubmit, HostResult


def _utc(stamp):
    return datetime.fromtimestamp(stamp, timezone.utc).isoformat().replace("+00:00", "Z")


@contextmanager
def _transaction(*, write=True):
    db.initialize(); conn = db._connect()
    try:
        conn.execute("BEGIN IMMEDIATE" if write else "BEGIN")
        phase = conn.execute("SELECT checksum FROM schema_migrations WHERE version=2").fetchone()
        if phase is None or phase[0] != CHECKSUM_002:
            raise FeedbackError("feedback_unavailable", 503)
        yield conn
        conn.commit()
    except (FeedbackError, audit_store.AuditPersistenceError):
        conn.rollback()
        raise
    except Exception:
        conn.rollback()
        raise FeedbackError("feedback_unavailable", 503) from None
    finally:
        conn.close()


def _view(row):
    payload, source = baselines.strict_json(row["payload_json"]), baselines.strict_json(row["source_json"])
    if (type(source) is not dict or source.get("schemaVersion") != 1
        or source.get("state") not in {"unverified", "linked", "legacy"}
        or type(row["safe_for_model"]) is not int or row["safe_for_model"] not in (0, 1)):
        raise FeedbackError("feedback_unavailable", 503)
    value = FeedbackView(**payload, id=row["id"], ts=_utc(row["created_at"]), status=row["status"],
        turnId=row["turn_id"], rowVersion=row["row_version"], safeForModel=bool(row["safe_for_model"]),
        reviewedAt=None if row["reviewed_at"] is None else _utc(row["reviewed_at"]), sourceState=source["state"])
    if value.soupId != row["soup_id"]:
        raise FeedbackError("feedback_unavailable", 503)
    return value


def _item(conn, identity):
    row = conn.execute("SELECT id,soup_id,turn_id,payload_json,source_json,status,safe_for_model,row_version,created_at,reviewed_at "
        "FROM feedback_items WHERE id=?", (identity,)).fetchone()
    if row is None:
        raise FeedbackError("feedback_not_found", 404)
    value = _view(row)
    return row, value


def _source(conn, req):
    if req.turnId is None:
        return {"schemaVersion": 1, "state": "unverified"}, None
    row = conn.execute("SELECT t.*,s.soup_id,s.compat_state,s.puzzle_version AS session_puzzle,s.rule_version AS session_rule "
        "FROM turns t JOIN sessions s ON s.id=t.session_id WHERE t.id=?", (req.turnId,)).fetchone()
    if row is None or row["state"] not in ("completed", "failed") or row["result_json"] is None:
        raise FeedbackError("feedback_source_unavailable", 422)
    if (row["soup_id"] != req.soupId or row["question"] != req.question
        or row["puzzle_version"] != row["session_puzzle"] or row["rule_version"] != row["session_rule"]
        or row["compat_state"] != "compatible"):
        raise FeedbackError("feedback_source_mismatch", 422)
    host = HostResult.model_validate_json(row["result_json"])
    frozen = baselines.session_baseline(conn, row["puzzle_version"], row["rule_version"])
    if (frozen.id != req.soupId or host.reply != req.hostAnswer
        or host.versions.puzzleVersion != row["puzzle_version"] or host.versions.ruleVersion != row["rule_version"]
        or host.versions.engineVersion != row["engine_version"]):
        raise FeedbackError("feedback_source_mismatch", 422)
    return {"schemaVersion": 1, "state": "linked", "sessionId": row["session_id"], "turnId": row["id"],
        "soupId": req.soupId, "puzzleVersion": row["puzzle_version"], "ruleVersion": row["rule_version"],
        "engineVersion": row["engine_version"], "resultDigest": baselines.digest(host.model_dump(mode="json"))}, frozen


def _audit(conn, value, *, action, now, source):
    event_type = ("feedback_submitted" if action == "submitted" else "feedback_privacy"
        if action in {"privacy_granted", "privacy_revoked"} else "feedback_reviewed")
    digest = baselines.digest({"view": value.model_dump(mode="json"), "source": source})
    audit_store.insert_business_event(conn, AuditEvent(
        eventId=str(uuid5(NAMESPACE_URL, f"turtle-soup/feedback/v1/{value.id}/{value.rowVersion}/{action}")),
        eventType=event_type, createdAt=float(now), turnId=value.turnId,
        details=FeedbackBusinessDetails(feedbackId=value.id, soupId=value.soupId, rowVersion=value.rowVersion,
            action=action, payloadDigest=digest, sourceState=value.sourceState,
            trafficClass="test" if get_runtime().settings.TESTING else "real")))


def submit_feedback(req):
    req = FeedbackSubmit.model_validate_json(req.model_dump_json())
    with _transaction() as conn:
        source, frozen = _source(conn, req)
        soup = frozen or db.get_soup_by_id(req.soupId)
        if soup is None:
            raise FeedbackError("feedback_soup_unknown", 422)
        now, identity = time.time(), str(uuid4())
        payload = {**req.model_dump(exclude={"turnId"}), "soupTitle": soup.title}
        value = FeedbackView(**payload, id=identity, ts=_utc(now), turnId=req.turnId, rowVersion=0,
            safeForModel=False, sourceState=source["state"])
        conn.execute("INSERT INTO feedback_items(id,soup_id,turn_id,payload_json,source_json,status,created_at) "
            "VALUES(?,?,?,?,?,'pending',?)", (identity, req.soupId, req.turnId, baselines.canonical_json(payload),
                baselines.canonical_json(source), now))
        _audit(conn, value, action="submitted", now=now, source=source)
        return value


def review_feedback(feedback_id, expected_row_version, *, status):
    try:
        version = FeedbackReview(expectedRowVersion=expected_row_version).expectedRowVersion
        if status not in {"approved", "rejected"} or not isinstance(feedback_id, str) or not UUID_PATTERN.fullmatch(feedback_id):
            raise ValueError("Invalid review")
    except (ValidationError, ValueError, TypeError):
        raise FeedbackError("feedback_review_invalid", 422) from None
    with _transaction() as conn:
        row, current = _item(conn, feedback_id)
        if row["row_version"] != version:
            raise FeedbackError("feedback_version_conflict", 409)
        if version == 9223372036854775807:
            raise FeedbackError("feedback_version_conflict", 409)
        from .feedback_contract import feedback_required_fields_valid
        if status == "approved" and not feedback_required_fields_valid(current):
            raise FeedbackError("feedback_required_fields_invalid", 422)
        now = time.time()
        changed = conn.execute("UPDATE feedback_items SET status=?,row_version=row_version+1,reviewed_at=? "
            "WHERE id=? AND row_version=?", (status, now, feedback_id, version))
        if changed.rowcount != 1:
            raise FeedbackError("feedback_version_conflict", 409)
        _, value = _item(conn, feedback_id)
        _audit(conn, value, action=status, now=now, source=baselines.strict_json(row["source_json"]))
        return value


def _query_invalid():
    raise FeedbackError("feedback_query_invalid", 422)


def set_model_permission(feedback_id, expected_row_version, *, review):
    try:
        version = FeedbackReview(expectedRowVersion=expected_row_version).expectedRowVersion
        checked = PrivacyReview.model_validate_json(review.model_dump_json())
        if not isinstance(feedback_id, str) or not UUID_PATTERN.fullmatch(feedback_id):
            raise ValueError("Invalid feedback identity")
    except (ValidationError, ValueError, TypeError, AttributeError):
        raise FeedbackError("feedback_review_invalid", 422) from None
    with _transaction() as conn:
        row, current = _item(conn, feedback_id)
        if row["row_version"] != version or version == 9223372036854775807:
            raise FeedbackError("feedback_version_conflict", 409)
        from .feedback_contract import feedback_required_fields_valid
        if checked.safeForModel and not feedback_required_fields_valid(current):
            raise FeedbackError("feedback_required_fields_invalid", 422)
        source = baselines.strict_json(row["source_json"])
        now = time.time()
        privacy = {"schemaVersion": 1, "reviewedForPrivacy": checked.reviewedForPrivacy,
            "reviewNote": checked.reviewNote, "reviewedAt": _utc(now), "rowVersion": version + 1,
            "sanitizedInput": None, "inputDigest": None}
        if checked.safeForModel:
            sanitized = SanitizedInput(question=checked.sanitizedQuestion, hostAnswer=checked.sanitizedHostAnswer,
                expectedClaim=checked.sanitizedExpectedClaim, reason=checked.sanitizedReason).model_dump(mode="json")
            privacy.update(sanitizedInput=sanitized, inputDigest=baselines.digest(sanitized))
        source["privacy"] = PrivacyRecord.model_validate_json(baselines.canonical_json(privacy)).model_dump(mode="json")
        changed = conn.execute("UPDATE feedback_items SET safe_for_model=?,source_json=?,row_version=row_version+1 "
            "WHERE id=? AND row_version=?", (int(checked.safeForModel), baselines.canonical_json(source), feedback_id, version))
        if changed.rowcount != 1:
            raise FeedbackError("feedback_version_conflict", 409)
        _, value = _item(conn, feedback_id)
        _audit(conn, value, action="privacy_granted" if checked.safeForModel else "privacy_revoked", now=now, source=source)
        return value


def _cursor(fields):
    raw = base64.urlsafe_b64encode(baselines.canonical_json(fields).encode()).decode().rstrip("=")
    if len(raw) > 512:
        _query_invalid()
    return raw


def _window(start, end):
    return (all(type(v) in (int, float) and math.isfinite(v) and v >= 0 for v in (start, end))
        and 0 <= end - start <= 31 * 86400)


def list_feedback(*, limit=50, start=None, end=None, cursor=None, status=None, soup_id=None):
    if (type(limit) is not int or not 1 <= limit <= 100 or status not in (None, "pending", "approved", "rejected")
        or soup_id is not None and (not isinstance(soup_id, str) or not 1 <= len(soup_id) <= 200)):
        _query_invalid()
    soup_digest = None if soup_id is None else baselines.digest(soup_id)
    point = None
    if cursor is not None:
        try:
            if not isinstance(cursor, str) or not 1 <= len(cursor) <= 512 or not re.fullmatch(r"[A-Za-z0-9_-]+", cursor):
                raise ValueError("Invalid cursor")
            fields = baselines.strict_json(base64.b64decode(cursor + "=" * (-len(cursor) % 4), altchars=b"-_", validate=True).decode())
            if (type(fields) is not dict or set(fields) != {"createdAt", "id", "start", "end", "status", "soupDigest"}
                or not _window(fields["start"], fields["end"])
                or type(fields["createdAt"]) not in (int, float) or not math.isfinite(fields["createdAt"])
                or not fields["start"] <= fields["createdAt"] <= fields["end"]
                or not isinstance(fields["id"], str) or not UUID_PATTERN.fullmatch(fields["id"])
                or fields["status"] not in (None, "pending", "approved", "rejected")
                or fields["soupDigest"] != soup_digest or _cursor(fields) != cursor
                or start is not None and start != fields["start"] or end is not None and end != fields["end"]
                or status is not None and status != fields["status"]):
                raise ValueError("Changed cursor scope")
            start, end, status = fields["start"], fields["end"], fields["status"]
            point = fields["createdAt"], fields["id"]
        except Exception:
            _query_invalid()
    end = time.time() if end is None else end
    start = end - 7 * 86400 if start is None and type(end) in (int, float) else start
    if not _window(start, end):
        _query_invalid()
    where, args = "created_at>=? AND created_at<=?", [start, end]
    if status is not None:
        where += " AND status=?"; args.append(status)
    if soup_id is not None:
        where += " AND soup_id=?"; args.append(soup_id)
    with _transaction(write=False) as conn:
        total = conn.execute("SELECT COUNT(*) FROM feedback_items WHERE " + where, tuple(args)).fetchone()[0]
        if point is not None:
            where += " AND (created_at<? OR (created_at=? AND id<?))"
            args.extend((point[0], point[0], point[1]))
        records = conn.execute("SELECT id,soup_id,turn_id,payload_json,source_json,status,safe_for_model,row_version,created_at,reviewed_at "
            "FROM feedback_items WHERE " + where + " ORDER BY created_at DESC,id DESC LIMIT ?",
            (*args, limit + 1)).fetchmany(limit + 1)
        values = tuple(_view(row) for row in records[:limit])
        next_cursor = None
        if len(records) > limit:
            last = records[limit - 1]
            next_cursor = _cursor({"createdAt": float(last["created_at"]), "id": last["id"], "start": float(start),
                "end": float(end), "status": status, "soupDigest": soup_digest})
        return FeedbackPage(feedbacks=values, totalInRange=total, nextCursor=next_cursor)
