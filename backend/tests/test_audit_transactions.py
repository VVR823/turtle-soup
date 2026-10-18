"""Business events must commit/rollback with real game rows, not a second write."""
import json
from threading import Event
from uuid import uuid4

import pytest

from app import db, game_service
from app.audit_context import AttemptCollector, attempt_context
from app.audit_events import AuditEvent
from app.runtime import get_runtime
from app.schemas import DifficultyLimits, HostResult, HostVersions, Soup


@pytest.fixture
def store(runtime):
    runtime.soups = [Soup(id="audit-synthetic", title="Public title", surface="Public surface",
        bottom="PRIVATE SYNTHETIC FACT", difficultyLimits=DifficultyLimits(xuermu=2, baozi=3, tianyi=4))]
    db.initialize()
    return runtime


def create(request_id=None):
    return db.create_game_once("audit-synthetic", "xuermu", request_id or str(uuid4()))


def rows(table):
    conn = db._connect()
    try:
        return [dict(row) for row in conn.execute(f"SELECT * FROM {table} ORDER BY rowid")]
    finally:
        conn.close()


def snapshot():
    return {name: rows(name) for name in ("sessions", "creation_requests", "turns", "messages", "evaluations", "audit_events")}


def host(owner, **changes):
    args = dict(kind="answer", answer="是", source="llm", chargeable=True, reply="PRIVATE DISPLAY",
        versions=HostVersions(puzzleVersion=owner.puzzleVersion, ruleVersion=owner.ruleVersion,
            engineVersion=owner.engineVersion))
    args.update(changes)
    return HostResult(**args)


def event_rows():
    return [AuditEvent.model_validate_json(row["details_json"]) for row in rows("audit_events")]


@pytest.mark.parametrize("operation", ["creation", "limit", "finish", "expire", "evaluation"])
def test_audit_insert_failure_rolls_back_entire_business_transaction(store, monkeypatch, operation):
    from app import audit_store
    if operation == "creation":
        action = create
    else:
        sid = create()["sessionId"]
        if operation == "limit":
            conn = db._connect()
            try:
                conn.execute("UPDATE sessions SET questions_asked=2 WHERE id=?", (sid,)); conn.commit()
            finally:
                conn.close()
            action = lambda: db.reserve_turn(sid, str(uuid4()), "PRIVATE QUESTION", now=100)
        elif operation in {"finish", "expire"}:
            owner = db.reserve_turn(sid, str(uuid4()), "PRIVATE QUESTION", now=100)
            action = (lambda: db.finish_turn(owner, host(owner), now=101)) if operation == "finish" else (
                lambda: db.expire_reserved_turns(sid, now=191))
        else:
            action = lambda: db.evaluate_once(sid, game_service.evaluate_snapshot)
    before = snapshot()
    def denied(conn, item):
        assert conn.in_transaction
        raise audit_store.AuditPersistenceError("Business audit could not be persisted")
    monkeypatch.setattr(audit_store, "insert_business_event", denied)
    with pytest.raises(audit_store.AuditPersistenceError):
        action()
    assert snapshot() == before


def test_missing_audit_table_blocks_new_game_without_partial_rows(store):
    from app.audit_store import AuditPersistenceError
    conn = db._connect()
    try:
        conn.execute("DROP TABLE audit_events"); conn.commit()
    finally:
        conn.close()
    with pytest.raises(AuditPersistenceError):
        create()
    assert rows("sessions") == rows("creation_requests") == []


def test_replays_never_duplicate_business_events(store):
    request = str(uuid4()); created = create(request); sid = created["sessionId"]
    assert create(request) == created
    turn_request = str(uuid4())
    owner = db.reserve_turn(sid, turn_request, "PRIVATE QUESTION", now=100)
    result = db.finish_turn(owner, host(owner), now=101)
    assert db.reserve_turn(sid, turn_request, "PRIVATE QUESTION", now=102) == result
    assert db.get_turn_response(sid, turn_request, now=102) == result
    evaluation = db.evaluate_once(sid, game_service.evaluate_snapshot)
    assert db.evaluate_once(sid, game_service.evaluate_snapshot) == evaluation
    events = event_rows()
    assert [event.eventType for event in events] == ["session_created", "turn_committed", "evaluation_created"]
    assert events[0].requestId == request and events[0].sessionId == sid
    assert events[1].turnId == owner.turnId and events[1].requestId == turn_request
    assert events[1].details.charged is True and events[1].details.source == "llm"
    assert events[1].details.versions == host(owner).versions
    assert not any(private in str(rows("audit_events")) for private in ("PRIVATE QUESTION", "PRIVATE DISPLAY", "PRIVATE SYNTHETIC FACT"))


def test_expiry_and_limit_events_report_actual_noncharged_outcomes(store):
    sid = create()["sessionId"]
    owner = db.reserve_turn(sid, str(uuid4()), "PRIVATE QUESTION", now=100)
    assert db.expire_reserved_turns(sid, now=191) == 1
    assert db.expire_reserved_turns(sid, now=192) == 0
    expiry = event_rows()[-1]
    assert expiry.eventType == "turn_expired" and expiry.turnId == owner.turnId
    assert expiry.details.charged is False and expiry.details.reasonCode == "turn_expired"
    conn = db._connect()
    try:
        conn.execute("UPDATE sessions SET questions_asked=2 WHERE id=?", (sid,)); conn.commit()
    finally:
        conn.close()
    limit = db.reserve_turn(sid, str(uuid4()), "PRIVATE LIMIT QUESTION", now=193)
    reminder = event_rows()[-1]
    assert reminder.eventType == "turn_committed" and reminder.turnId == limit.safeResponse["turnId"]
    assert reminder.details.kind == "reminder" and reminder.details.charged is False
    assert rows("messages") == [] and rows("sessions")[0]["questions_asked"] == 2


def test_cancellation_event_describes_final_cancelled_result_not_model_answer(store):
    sid = create()["sessionId"]; owner = db.reserve_turn(sid, str(uuid4()), "PRIVATE QUESTION", now=100)
    cancellation = Event(); cancellation.set()
    result = db.finish_turn(owner, host(owner), now=101, cancelled=cancellation)
    assert result.httpStatus == 503
    item = event_rows()[-1]
    assert item.details.source == "flow" and item.details.charged is False
    assert item.details.reasonCode == "model_cancelled" and item.details.kind == "system_error"
    assert rows("sessions")[0]["questions_asked"] == 0


def test_http_metadata_is_only_published_after_business_commit(store, monkeypatch):
    from app import audit_store
    sid = create()["sessionId"]; request = str(uuid4())
    owner = db.reserve_turn(sid, request, "PRIVATE QUESTION", now=100)
    collector = AttemptCollector(str(uuid4()))
    def denied(*args):
        raise audit_store.AuditPersistenceError("Audit unavailable")
    monkeypatch.setattr(audit_store, "insert_business_event", denied)
    with attempt_context(collector), pytest.raises(audit_store.AuditPersistenceError):
        db.finish_turn(owner, host(owner), now=101)
    sealed = collector.finish(status_code=503, method="POST", route_template="/api/chat",
        response_started=True, disconnected=False)
    assert sealed.details.charged is None and sealed.details.kind is None
    assert rows("sessions")[0]["questions_asked"] == 0


def test_large_evidence_is_truncated_without_failing_a_legal_turn(store):
    sid = create()["sessionId"]; owner = db.reserve_turn(sid, str(uuid4()), "PRIVATE QUESTION", now=100)
    evidence = tuple("safe-" + str(index) + "x" * 190 for index in range(400))
    assert db.finish_turn(owner, host(owner, evidenceIds=evidence), now=101).httpStatus == 200
    item = event_rows()[-1]
    assert item.details.evidenceCount == 400 and item.details.evidenceTruncated
    assert len(item.details.evidenceIds) < 128
    assert len(item.model_dump_json().encode()) <= 16384
    assert rows("sessions")[0]["questions_asked"] == 1


def test_business_audit_ignores_diagnostic_trace_flag(store):
    assert not get_runtime().settings.ENABLE_TRACE
    create()
    assert len(event_rows()) == 1 and event_rows()[0].eventType == "session_created"
