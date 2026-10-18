"""Explicit offline import of a bounded stopped-writer copy, never startup IO."""
import hashlib
import math
import re
import time
from datetime import datetime
from pathlib import Path
from typing import Annotated, Literal
from uuid import NAMESPACE_URL, uuid5

from pydantic import Field, StrictInt

from . import audit_store, baselines, migrations
from .audit_events import AuditEvent, FeedbackBusinessDetails
from .feedback_contract import FeedbackView, PrivacyRecord, StrictFeedbackModel, feedback_required_fields_valid
from .scripts.migrate_data import _safe_path
from .paths import canonical_path

MAX_SOURCE_BYTES, MAX_ROWS, MAX_LINE_BYTES = 100 * 1024 * 1024, 5000, 32768
_DIGEST = re.compile(r"[0-9a-f]{64}\Z")


class FeedbackImportError(RuntimeError):
    def __init__(self, code):
        self.code = code
        super().__init__(code)


class BadFeedbackRow(StrictFeedbackModel):
    lineNumber: Annotated[StrictInt, Field(ge=1, le=5000)]
    lineDigest: Annotated[str, Field(pattern=r"^[0-9a-f]{64}$")]
    code: Literal["feedback_row_invalid", "feedback_line_limit", "feedback_partial_tail"]


class FeedbackImportReport(StrictFeedbackModel):
    imported: Annotated[StrictInt, Field(ge=0, le=5000)]
    duplicates: Annotated[StrictInt, Field(ge=0, le=5000)]
    badRows: Annotated[tuple[BadFeedbackRow, ...], Field(max_length=5000)]
    sourceDigest: Annotated[str, Field(pattern=r"^[0-9a-f]{64}$")]
    needsReview: bool
    productionReady: Literal[False] = False


def legacy_row_identity(source_digest, line_number, line_digest):
    if (not isinstance(source_digest, str) or not _DIGEST.fullmatch(source_digest)
        or not isinstance(line_digest, str) or not _DIGEST.fullmatch(line_digest)
        or type(line_number) is not int or not 1 <= line_number <= MAX_ROWS):
        raise FeedbackImportError("feedback_source_invalid")
    return str(uuid5(NAMESPACE_URL, f"turtle-soup/legacy-feedback/v1/{source_digest}/{line_number}/{line_digest}"))


def checked_source(source):
    if not isinstance(source, Path) or not source.is_absolute():
        raise FeedbackImportError("feedback_source_invalid")
    try:
        if canonical_path(source) != source.absolute() or source.is_symlink():
            raise ValueError("Source alias")
        _safe_path(str(source))
        stat = source.stat()
        if not source.is_file():
            raise ValueError("File required")
        if stat.st_size > MAX_SOURCE_BYTES:
            raise FeedbackImportError("feedback_source_limit")
        return stat.st_size, stat.st_mtime_ns, stat.st_ino
    except FeedbackImportError:
        raise
    except Exception:
        raise FeedbackImportError("feedback_source_invalid") from None


def _timestamp(value):
    if not isinstance(value, str) or not 1 <= len(value) <= 40:
        raise ValueError("Invalid timestamp")
    date = datetime.fromisoformat(value.replace("Z", "+00:00"))
    stamp = date.timestamp() if date.tzinfo is not None else float("nan")
    if not math.isfinite(stamp) or stamp < 0:
        raise ValueError("Invalid timestamp")
    return stamp


def _legacy_payload(raw, identity):
    value = baselines.strict_json(raw.decode("utf-8"))
    allowed = {"id", "ts", "soupId", "soupTitle", "question", "hostAnswer", "expectedAnswer", "reason",
        "status", "reviewedAt", "mergedAt", "mergedAnswer"}
    if (type(value) is not dict or not set(value) <= allowed or not isinstance(value.get("id"), str)
        or not 1 <= len(value["id"]) <= 200):
        raise ValueError("Invalid legacy record")
    created = _timestamp(value.get("ts"))
    reviewed = None if value.get("reviewedAt") is None else _timestamp(value["reviewedAt"])
    if value.get("mergedAt") is not None:
        _timestamp(value["mergedAt"])
    if value.get("mergedAnswer") is not None and (not isinstance(value["mergedAnswer"], str) or len(value["mergedAnswer"]) > 100):
        raise ValueError("Invalid legacy merge history")
    payload = {key: value.get(key) for key in ("soupId", "soupTitle", "question", "hostAnswer", "expectedAnswer", "reason")}
    view = FeedbackView(**payload, id=identity, ts=value["ts"], status=value.get("status", "pending"),
        reviewedAt=value.get("reviewedAt"), rowVersion=0, safeForModel=False, sourceState="legacy")
    if not feedback_required_fields_valid(view):
        raise ValueError("Blank legacy required fields")
    history = {key: value.get(key) for key in ("status", "reviewedAt", "mergedAt", "mergedAnswer")}
    return payload, view, created, reviewed, hashlib.sha256(value["id"].encode()).hexdigest(), history


def _read_source(source, expected_digest):
    before = checked_source(source); file_hash = hashlib.sha256(); records, bad = [], []
    total, number = 0, 0
    with source.open("rb") as stream:
        while True:
            raw = stream.readline(MAX_LINE_BYTES + 1)
            if not raw:
                break
            number += 1
            if number > MAX_ROWS:
                raise FeedbackImportError("feedback_source_limit")
            line_hash = hashlib.sha256(); prefix = raw
            oversized = len(raw) > MAX_LINE_BYTES
            while True:
                file_hash.update(raw); line_hash.update(raw); total += len(raw)
                if total > MAX_SOURCE_BYTES:
                    raise FeedbackImportError("feedback_source_limit")
                if raw.endswith(b"\n"):
                    terminated = True; break
                raw = stream.readline(MAX_LINE_BYTES + 1)
                if not raw:
                    terminated = False; break
                oversized = True
            digest = line_hash.hexdigest()
            identity = legacy_row_identity(expected_digest, number, digest)
            code = "feedback_line_limit" if oversized else "feedback_partial_tail" if not terminated else None
            if code is None:
                try:
                    parsed = _legacy_payload(prefix, identity)
                    records.append((identity, number, digest, parsed))
                except Exception:
                    code = "feedback_row_invalid"
            if code:
                bad.append(BadFeedbackRow(lineNumber=number, lineDigest=digest, code=code))
    if checked_source(source) != before or file_hash.hexdigest() != expected_digest:
        raise FeedbackImportError("feedback_source_changed")
    return records, tuple(bad), before


def import_feedback_jsonl(conn, source, *, source_digest):
    if not isinstance(source_digest, str) or not _DIGEST.fullmatch(source_digest) or conn.in_transaction:
        raise FeedbackImportError("feedback_source_invalid")
    try:
        records, bad, before = _read_source(source, source_digest)
        conn.execute("BEGIN IMMEDIATE")
        migrations.verify_schema(conn, required_version=2)
        imported, duplicates = 0, 0
        for identity, number, line_digest, parsed in records:
            payload, view, created, reviewed, old_id_hash, history = parsed
            origin = {"schemaVersion": 1, "state": "legacy", "sourceFileDigest": source_digest,
                "lineNumber": number, "lineDigest": line_digest, "originalIdDigest": old_id_hash,
                "legacyHistory": history}
            old = conn.execute("SELECT payload_json,source_json,soup_id,turn_id,safe_for_model,row_version FROM feedback_items WHERE id=?", (identity,)).fetchone()
            if old is not None:
                old_origin = baselines.strict_json(old[1])
                if type(old_origin) is not dict:
                    raise FeedbackImportError("feedback_import_conflict")
                # Immutable provenance is separate from subsequent manual privacy
                # decisions. Validate, but never reset those decisions on replay.
                if "privacy" in old_origin:
                    try:
                        privacy = PrivacyRecord.model_validate_json(baselines.canonical_json(old_origin["privacy"]))
                        if (type(old[4]) is not int or old[4] not in (0, 1)
                            or type(old[5]) is not int or not 1 <= privacy.rowVersion <= old[5]
                            or bool(old[4]) != (privacy.sanitizedInput is not None)
                            or (old[4] == 1 and not privacy.reviewedForPrivacy)):
                            raise ValueError("Inconsistent permission")
                    except Exception:
                        raise FeedbackImportError("feedback_import_conflict") from None
                    old_origin = {key: value for key, value in old_origin.items() if key != "privacy"}
                elif old[4] != 0:
                    raise FeedbackImportError("feedback_import_conflict")
                if (baselines.strict_json(old[0]) != payload or old_origin != origin
                    or old[2] != view.soupId or old[3] is not None):
                    raise FeedbackImportError("feedback_import_conflict")
                duplicates += 1; continue
            conn.execute("INSERT INTO feedback_items(id,soup_id,turn_id,payload_json,source_json,status,safe_for_model,row_version,created_at,reviewed_at) "
                "VALUES(?,?,NULL,?,?,?,0,0,?,?)", (identity, view.soupId, baselines.canonical_json(payload),
                    baselines.canonical_json(origin), view.status, created, reviewed))
            audit_store.insert_business_event(conn, AuditEvent(eventId=str(uuid5(NAMESPACE_URL, "turtle-soup/feedback-import-audit/v1/" + identity)),
                eventType="feedback_imported", createdAt=float(time.time()),
                details=FeedbackBusinessDetails(feedbackId=identity, soupId=view.soupId, rowVersion=0,
                    action="imported", payloadDigest=baselines.digest({"payload": payload, "source": origin}),
                    sourceState="legacy", trafficClass="legacy")))
            imported += 1
        if checked_source(source) != before:
            raise FeedbackImportError("feedback_source_changed")
        conn.commit()
        return FeedbackImportReport(imported=imported, duplicates=duplicates, badRows=bad,
            sourceDigest=source_digest, needsReview=bool(bad))
    except Exception as error:
        if conn.in_transaction:
            conn.rollback()
        if isinstance(error, FeedbackImportError):
            raise
        raise FeedbackImportError("feedback_import_unavailable") from None
