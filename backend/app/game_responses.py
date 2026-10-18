"""Strict private-storage replay boundaries; never return unvalidated dictionaries."""
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, StrictInt, StrictStr

from . import baselines
from .schemas import ChatCreateResponse, ChatReplyResponse, EvaluationResult, HostKind, HostResult, ModelErrorCode


class StoredCreation(ChatCreateResponse):
    model_config = ConfigDict(extra="forbid", strict=True, frozen=True)
    sessionId: StrictStr = Field(min_length=1, max_length=200)
    requestId: StrictStr = Field(min_length=1, max_length=200)


class StoredTurnBody(ChatReplyResponse):
    model_config = ConfigDict(extra="forbid", strict=True, frozen=True)
    reply: StrictStr = Field(min_length=1, max_length=2000)
    sessionId: StrictStr = Field(min_length=1, max_length=200)
    requestId: StrictStr = Field(min_length=1, max_length=200)
    turnId: StrictStr = Field(min_length=1, max_length=200)
    kind: HostKind
    state: Literal["completed", "failed", "expired"]
    isReveal: bool
    isGiveup: bool
    isWin: bool
    isFreeReminder: bool
    limitReached: bool
    remaining: StrictInt | None = Field(ge=0)
    code: ModelErrorCode | Literal["turn_expired"] | None = None
    detail: StrictStr | None = Field(default=None, max_length=2000)


class StoredTurnEnvelope(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True, frozen=True)
    schemaVersion: StrictInt = Field(ge=1, le=1)
    httpStatus: Literal[200, 503]
    body: StoredTurnBody


class StoredEvaluationBody(EvaluationResult):
    model_config = ConfigDict(extra="forbid", strict=True, frozen=True)


class StoredEvaluation(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True, frozen=True)
    schemaVersion: StrictInt = Field(ge=1, le=1)
    sessionId: StrictStr = Field(min_length=1, max_length=200)
    puzzleVersion: StrictStr = Field(min_length=1, max_length=200)
    ruleVersion: StrictStr = Field(min_length=1, max_length=200)
    body: StoredEvaluationBody


def _decode(model, raw):
    try:
        # Pydantic's JSON mode understands immutable tuples, while strict_json
        # rejects duplicate keys/nonfinite numbers before its decoder can erase them.
        return model.model_validate_json(baselines.canonical_json(baselines.strict_json(raw)), strict=True)
    except (ValueError, TypeError, KeyError) as error:
        raise baselines.SnapshotError("Stored game response is invalid") from error


def creation_response(row, session, soup):
    parsed = _decode(StoredCreation, row["response_json"])
    if (parsed.requestId != row["request_id"] or parsed.sessionId != row["session_id"]
            or parsed.sessionId != session["id"] or soup.id != session["soup_id"]
            or parsed.soupTitle != soup.title or parsed.soupSurface != soup.surface
            or parsed.questionLimit != session["question_limit"] or parsed.unlocks != soup.unlocks):
        raise baselines.SnapshotError("Stored creation identity mismatch")
    return parsed.model_dump(mode="json", exclude_unset=True)


def turn_response(row):
    saved = _decode(StoredTurnEnvelope, row["response_json"])
    body = saved.body
    if (body.sessionId != row["session_id"] or body.requestId != row["request_id"] or body.turnId != row["id"]
            or body.state != row["state"] or body.kind != row["kind"]
            or body.isFreeReminder != (row["charged"] == 0) or body.isGiveup
            or body.isWin != (body.kind == "win") or body.isReveal != (body.kind == "win")
            or saved.httpStatus != (503 if body.kind == "system_error" else 200)
            or (body.state in {"failed", "expired"}) != (body.kind == "system_error")):
        raise baselines.SnapshotError("Stored turn identity or state mismatch")
    if row["result_json"] is not None:
        result = _decode(HostResult, row["result_json"])
        if (result.kind != row["kind"] or result.chargeable != bool(row["charged"]) or result.reply != body.reply
                or (result.versions.puzzleVersion, result.versions.ruleVersion, result.versions.engineVersion)
                != (row["puzzle_version"], row["rule_version"], row["engine_version"])):
            raise baselines.SnapshotError("Stored turn result mismatch")
        expected_code = "turn_expired" if body.state == "expired" else result.errorCode
        if body.code != expected_code:
            raise baselines.SnapshotError("Stored turn error mismatch")
    elif not (body.kind == "reminder" and body.limitReached and body.remaining == 0 and row["charged"] == 0):
        raise baselines.SnapshotError("Stored turn result is missing")
    if body.kind == "system_error":
        if body.code is None or body.detail != body.reply:
            raise baselines.SnapshotError("Stored failure fields mismatch")
    elif body.code is not None or body.detail is not None:
        raise baselines.SnapshotError("Unexpected stored failure fields")
    return saved.httpStatus, body.model_dump(mode="json", exclude_unset=True)


def pack_evaluation(session, response):
    body = StoredEvaluationBody.model_validate(response, strict=True)
    return StoredEvaluation(schemaVersion=1, sessionId=session["id"], puzzleVersion=session["puzzle_version"],
                            ruleVersion=session["rule_version"], body=body).model_dump_json()


def evaluation_response(row, session):
    saved = _decode(StoredEvaluation, row["response_json"])
    if (saved.sessionId != row["session_id"] or saved.sessionId != session["id"]
            or saved.puzzleVersion != session["puzzle_version"] or saved.ruleVersion != session["rule_version"]
            or session["status"] not in {"solved", "given_up"}):
        raise baselines.SnapshotError("Stored evaluation identity or state mismatch")
    return saved.body.model_dump(mode="json")
