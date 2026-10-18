"""Strict legacy JSON import inside the migration transaction, with source provenance."""
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, StrictBool, StrictInt, ValidationError

from .baselines import digest

SQLITE_INTEGER_MAX = 2 ** 63 - 1


class LegacyMessage(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True)
    id: StrictInt | None = Field(default=None, gt=0, le=SQLITE_INTEGER_MAX)
    role: Literal["user", "host"]
    content: str
    timestamp: float = Field(ge=0, allow_inf_nan=False)
    isFreeReminder: StrictBool = False


class LegacySession(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True)
    id: str = Field(min_length=1)
    soupId: str = Field(min_length=1)
    status: Literal["playing", "solved", "given_up"] = "playing"
    questionsAsked: StrictInt = Field(ge=0, le=SQLITE_INTEGER_MAX)
    questionLimit: StrictInt | None = Field(default=None, ge=0, le=SQLITE_INTEGER_MAX)
    createdAt: float = Field(ge=0, allow_inf_nan=False)
    solvedAt: float | None = Field(default=None, ge=0, allow_inf_nan=False)
    givenUpAt: float | None = Field(default=None, ge=0, allow_inf_nan=False)
    messages: list[LegacyMessage] = Field(default_factory=list)


def import_records(conn, records: list) -> dict:
    issues, imported = [], 0
    validated = []
    reserved_ids = set()
    for number, raw in enumerate(records, 1):
        locator = {"source": "sessions.json", "recordNumber": number, "recordHash": digest(raw)}
        try:
            session = LegacySession.model_validate(raw)
            if not session.id.strip() or not session.soupId.strip():
                raise ValueError("blank ID")
        except (ValidationError, ValueError, TypeError):
            issues.append({**locator, "code": "invalid_json_record"})
            continue
        validated.append((session, locator))
        reserved_ids.update(message.id for message in session.messages if message.id is not None)
    next_id = max([conn.execute("SELECT coalesce(max(id),0) FROM messages").fetchone()[0], *reserved_ids]) + 1
    for session, locator in validated:
        if conn.execute("SELECT 1 FROM sessions WHERE id=?", (session.id,)).fetchone():
            issues.append({**locator, "code": "duplicate_session_id"})
            continue
        supplied_ids = [m.id for m in session.messages if m.id is not None]
        if len(set(supplied_ids)) != len(supplied_ids) or any(
            conn.execute("SELECT 1 FROM messages WHERE id=?", (mid,)).fetchone() for mid in supplied_ids
        ):
            issues.append({**locator, "code": "duplicate_message_id"})
            continue
        conn.execute("INSERT INTO sessions (id,soup_id,status,questions_asked,question_limit,created_at,solved_at,given_up_at) VALUES (?,?,?,?,?,?,?,?)",
                     (session.id, session.soupId, session.status, session.questionsAsked, session.questionLimit,
                      session.createdAt, session.solvedAt, session.givenUpAt))
        for message in session.messages:
            mid = message.id
            if mid is None:
                mid, next_id = next_id, next_id + 1
            conn.execute("INSERT INTO messages (id,session_id,role,content,timestamp,is_free_reminder) VALUES (?,?,?,?,?,?)",
                         (mid, session.id, message.role, message.content, message.timestamp, int(message.isFreeReminder)))
        imported += 1
    return {"legacyRecords": len(records), "importedSessions": imported, "issues": issues}
