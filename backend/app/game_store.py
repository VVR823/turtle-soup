"""Short game-request transactions; never call a model under a write lock."""
import math
import time
from contextlib import contextmanager
from contextvars import ContextVar
from dataclasses import dataclass
from uuid import NAMESPACE_URL, uuid4, uuid5

from . import baselines
from . import game_responses
from .runtime import get_runtime
from .schemas import ChatCreateResponse, ChatReplyResponse, EvaluationResult, HostResult, HostVersions, HOST_ENGINE_VERSION
from .scoring import ConfirmedTurn, SCORE_VERSION
from .audit_context import current_attempt
from .audit_events import AuditEvent, BusinessDetails, MAX_EVENT_BYTES

_after_commit = ContextVar("game_audit_after_commit", default=None)


def _pinned_versions(session):
    # A session pins puzzle/rules, not the engine that produced all old turns.
    return HostVersions(puzzleVersion=session["puzzle_version"], ruleVersion=session["rule_version"],
        engineVersion="unversioned", normalizationVersion="unversioned")


def _host_details(host, *, reason=None):
    ids = tuple(value for value in host.evidenceIds if isinstance(value, str) and 1 <= len(value) <= 200)[:128]
    return BusinessDetails(source=host.source, kind=host.kind, charged=host.chargeable,
        cacheHit=host.cacheHit, versions=host.versions, reasonCode=reason or host.errorCode or host.kind,
        evidenceIds=ids, evidenceCount=len(host.evidenceIds), evidenceTruncated=len(ids) != len(host.evidenceIds),
        trafficClass="test" if get_runtime().settings.TESTING else "real")


def _audit_business(conn, event_type, session_id, *, now, request_id=None, turn_id=None, details):
    from . import audit_store
    header = dict(eventId=str(uuid5(NAMESPACE_URL, "turtle-soup/business/v1/" + event_type + "/" + (turn_id or session_id))),
        eventType=event_type, sessionId=session_id, requestId=request_id, turnId=turn_id, createdAt=float(now))
    values = details.model_dump(mode="python")
    while len(baselines.canonical_json({**header, "schemaVersion": 1, "runId": None,
        "details": BusinessDetails(**values).model_dump(mode="json")}).encode()) > MAX_EVENT_BYTES:
        if values["evidenceIds"]:
            values["evidenceIds"] = values["evidenceIds"][:-1]; values["evidenceTruncated"] = True
        elif values["versions"] is not None:
            values["versions"] = None; values["metadataTruncated"] = True
        else:
            raise audit_store.AuditPersistenceError("Business audit metadata exceeds byte budget")
    audit_store.insert_business_event(conn, AuditEvent(**header, details=BusinessDetails(**values)))


def _publish_after_commit(session_id, *, request_id=None, turn_id=None, details=None, replayed=False):
    collector, pending = current_attempt(), _after_commit.get()
    if collector is None or pending is None:
        return
    def publish():
        if collector.bind_ids(session_id=session_id, request_id=request_id, turn_id=turn_id) and details is not None:
            collector.observe_metadata(details, replayed=replayed)
    pending.append(publish)


class GameConflict(RuntimeError):
    def __init__(self, code):
        self.code = code
        super().__init__(code)


class GameNotFound(RuntimeError):
    pass


@dataclass(frozen=True)
class TurnReservation:
    turnId: str
    sessionId: str
    requestId: str
    question: str
    leaseToken: str
    expectedRowVersion: int
    puzzleVersion: str
    ruleVersion: str
    engineVersion: str = HOST_ENGINE_VERSION


@dataclass(frozen=True)
class TurnReplay:
    state: str
    httpStatus: int
    safeResponse: dict


@contextmanager
def _transaction():
    from . import db
    db.initialize()
    conn = db._connect()
    pending = []
    token = _after_commit.set(pending)
    committed = False
    try:
        conn.execute("BEGIN IMMEDIATE")
        yield conn
        conn.commit()
        committed = True
    except BaseException:
        conn.rollback()
        raise
    finally:
        conn.close()
        _after_commit.reset(token)
    if committed:
        for publish in pending:
            try:
                publish()
            except Exception:
                collector = current_attempt()
                if collector is not None:
                    collector.note_metadata_gap()


def _timestamp(now):
    value = time.time() if now is None else now
    if isinstance(value, bool) or not isinstance(value, (int, float)) or not math.isfinite(value) or value < 0:
        raise ValueError("Invalid operation time")
    return value


def _session(conn, session_id):
    from . import db
    row = conn.execute("SELECT * FROM sessions WHERE id=?", (session_id,)).fetchone()
    if row is None:
        raise GameNotFound("session_not_found")
    db.require_compatible({"compatState": row["compat_state"]})
    return row


def _bound_soup(conn, session):
    soup = baselines.session_baseline(conn, session["puzzle_version"], session["rule_version"])
    if soup.id != session["soup_id"]:
        raise baselines.SnapshotError("Session/puzzle identity mismatch")
    return soup


def _require_rule_available(conn, rule_version):
    from .rule_contract import rule_suspension_state
    if rule_suspension_state(conn, rule_version):
        raise GameConflict("rule_version_suspended")


def _envelope(replay):
    return baselines.canonical_json({"schemaVersion": 1, "httpStatus": replay.httpStatus,
                                     "body": replay.safeResponse})


def _replay(row):
    details = BusinessDetails(reasonCode="turn_reserved", versions=HostVersions(
        puzzleVersion=row["puzzle_version"], ruleVersion=row["rule_version"], engineVersion=row["engine_version"]))
    if row["state"] == "reserved":
        _publish_after_commit(row["session_id"], request_id=row["request_id"], turn_id=row["id"], details=details, replayed=True)
        return TurnReplay("reserved", 202, {
            "state": "reserved", "turnId": row["id"], "sessionId": row["session_id"],
            "requestId": row["request_id"], "code": "turn_in_progress", "detail": "这次提问正在处理，请稍候。",
        })
    if row["response_json"] is None:
        _publish_after_commit(row["session_id"], request_id=row["request_id"], turn_id=row["id"],
            details=BusinessDetails(reasonCode="legacy_unverified", trafficClass="legacy"), replayed=True)
        return TurnReplay(row["state"], 409, {
            "state": row["state"], "turnId": row["id"], "sessionId": row["session_id"],
            "requestId": row["request_id"], "code": "legacy_result_unavailable",
            "detail": "这条旧请求没有可核验的响应，历史已保留。",
        })
    status, body = game_responses.turn_response(row)
    if row["result_json"] is not None:
        details = _host_details(game_responses._decode(HostResult, row["result_json"]),
            reason="turn_expired" if row["state"] == "expired" else None)
    else:
        details = BusinessDetails(source="flow", kind="reminder", charged=False, cacheHit=False,
            versions=details.versions, reasonCode="reminder", trafficClass="test" if get_runtime().settings.TESTING else "real")
    _publish_after_commit(row["session_id"], request_id=row["request_id"], turn_id=row["id"], details=details, replayed=True)
    return TurnReplay(row["state"], status, body)


def create_game_once(soup_id: str, level: str | None, request_id: str) -> dict:
    payload_hash = baselines.digest({"soupId": soup_id, "level": level})
    now = _timestamp(None)
    with _transaction() as conn:
        old = conn.execute("SELECT * FROM creation_requests WHERE request_id=?", (request_id,)).fetchone()
        if old is not None:
            if old["payload_hash"] != payload_hash:
                raise GameConflict("creation_payload_conflict")
            session = _session(conn, old["session_id"])
            response = game_responses.creation_response(old, session, _bound_soup(conn, session))
            _publish_after_commit(session["id"], request_id=request_id,
                details=BusinessDetails(reasonCode="session_created", versions=_pinned_versions(session)), replayed=True)
            return response
        active = baselines.active_manifest(conn)
        _require_rule_available(conn, active["ruleVersion"])
        version = active["puzzleVersions"].get(soup_id)
        if version is None:
            raise GameNotFound("soup_not_found")
        soup = baselines.session_baseline(conn, version, active["ruleVersion"])
        limit = None
        if not soup.unlimited and soup.difficultyLimits is not None:
            selected = level if level in {"xuermu", "baozi", "tianyi"} else "xuermu"
            limit = getattr(soup.difficultyLimits, selected)
        session_id = str(uuid4())
        conn.execute("""INSERT INTO sessions
            (id,soup_id,status,questions_asked,question_limit,created_at,puzzle_version,
             rule_version,compat_state,last_activity_at,traffic_class)
            VALUES (?,?,'playing',0,?,?,?,?,'compatible',?,?)""",
            (session_id, soup_id, limit, now, version, active["ruleVersion"], now,
             "test" if get_runtime().settings.TESTING else "real"))
        response = ChatCreateResponse(soupTitle=soup.title, soupSurface=soup.surface, sessionId=session_id,
                                      questionLimit=limit, unlocks=soup.unlocks, requestId=request_id).model_dump(mode="json")
        conn.execute("""INSERT INTO creation_requests
            (request_id,payload_hash,session_id,response_json,created_at) VALUES (?,?,?,?,?)""",
            (request_id, payload_hash, session_id, baselines.canonical_json(response), now))
        details = BusinessDetails(reasonCode="session_created", versions=HostVersions(puzzleVersion=version,
            ruleVersion=active["ruleVersion"], engineVersion="unversioned", normalizationVersion="unversioned"),
            trafficClass="test" if get_runtime().settings.TESTING else "real")
        _audit_business(conn, "session_created", session_id, now=now, request_id=request_id, details=details)
        _publish_after_commit(session_id, request_id=request_id, details=details)
        return response


def reserve_turn(session_id: str, request_id: str, question: str, *, soup_id: str | None = None,
                 now: float | None = None) -> TurnReservation | TurnReplay:
    # One short transaction expires stale reservations and replays the same
    # request/payload before reserving a new turn. Reservation does not charge;
    # the caller runs the model only after this transaction has ended.
    payload_hash = baselines.digest({"question": question})
    with _transaction() as conn:
        now = _timestamp(now)
        session = _session(conn, session_id)
        if soup_id is not None and soup_id != session["soup_id"]:
            raise GameConflict("session_soup_conflict")
        _expire(conn, session_id, now)
        session = _session(conn, session_id)
        old = conn.execute("SELECT * FROM turns WHERE session_id=? AND request_id=?", (session_id, request_id)).fetchone()
        if old is not None:
            if old["payload_hash"] != payload_hash:
                raise GameConflict("turn_payload_conflict")
            return _replay(old)
        if session["status"] != "playing":
            raise GameConflict("game_ended")
        _require_rule_available(conn, session["rule_version"])
        _bound_soup(conn, session)
        if conn.execute("SELECT 1 FROM turns WHERE session_id=? AND state='reserved'", (session_id,)).fetchone():
            raise GameConflict("turn_in_progress")
        turn_id, token = str(uuid4()), str(uuid4())
        conn.execute("""INSERT INTO turns
            (id,session_id,request_id,payload_hash,question,state,lease_token,lease_expires_at,
             puzzle_version,rule_version,engine_version,created_at)
            VALUES (?,?,?,?,?,'reserved',?,?,?,?,?,?)""",
            (turn_id, session_id, request_id, payload_hash, question, token, now + 90,
             session["puzzle_version"], session["rule_version"], HOST_ENGINE_VERSION, now))
        conn.execute("UPDATE sessions SET row_version=row_version+1,last_activity_at=? WHERE id=?", (now, session_id))
        if session["question_limit"] is not None and session["questions_asked"] >= session["question_limit"]:
            response = ChatReplyResponse(reply="❌ 本局提问次数已用完，正在揭晓真相……", sessionId=session_id,
                                         remaining=0, limitReached=True, isFreeReminder=True,
                                         requestId=request_id, kind="reminder", state="completed").model_dump(mode="json")
            response["turnId"] = turn_id
            replay = TurnReplay("completed", 200, response)
            conn.execute("""UPDATE turns SET state='completed',kind='reminder',response_json=?,
                lease_token=NULL,lease_expires_at=NULL,completed_at=? WHERE id=?""", (_envelope(replay), now, turn_id))
            details = BusinessDetails(source="flow", kind="reminder", charged=False, cacheHit=False,
                reasonCode="reminder", versions=HostVersions(puzzleVersion=session["puzzle_version"], ruleVersion=session["rule_version"]),
                trafficClass="test" if get_runtime().settings.TESTING else "real")
            _audit_business(conn, "turn_committed", session_id, now=now, request_id=request_id, turn_id=turn_id, details=details)
            _publish_after_commit(session_id, request_id=request_id, turn_id=turn_id, details=details)
            return replay
        _publish_after_commit(session_id, request_id=request_id, turn_id=turn_id,
            details=BusinessDetails(reasonCode="turn_reserved", versions=HostVersions(
                puzzleVersion=session["puzzle_version"], ruleVersion=session["rule_version"])))
        return TurnReservation(turn_id, session_id, request_id, question, token, session["row_version"] + 1,
                               session["puzzle_version"], session["rule_version"])


def _response(owner, result, remaining):
    body = ChatReplyResponse(
        reply=result.reply, isReveal=result.kind == "win", isWin=result.kind == "win",
        sessionId=owner.sessionId, remaining=remaining, isFreeReminder=not result.chargeable,
        requestId=owner.requestId, turnId=owner.turnId, kind=result.kind,
        state="failed" if result.kind == "system_error" else "completed",
    ).model_dump(mode="json")
    if result.kind == "system_error":
        body.update(code=result.errorCode, detail=result.reply)
    return TurnReplay("failed" if result.kind == "system_error" else "completed",
                      503 if result.kind == "system_error" else 200, body)


def _expire(conn, session_id, now):
    # Persist a zero-charge terminal response and revoke the old business lease.
    # This does not release a gateway owner whose transport is still running.
    expired = conn.execute("""SELECT * FROM turns
        WHERE session_id=? AND state='reserved' AND lease_expires_at<=?""", (session_id, now)).fetchall()
    if not expired:
        return 0
    session = _session(conn, session_id)
    remaining = None if session["question_limit"] is None else max(0, session["question_limit"] - session["questions_asked"])
    for row in expired:
        owner = TurnReservation(row["id"], session_id, row["request_id"], row["question"], row["lease_token"],
                                session["row_version"], row["puzzle_version"], row["rule_version"], row["engine_version"])
        result = HostResult(kind="system_error", source="flow", chargeable=False, errorCode="model_timeout",
                            reply="这次提问处理已超时，没有扣次数；请重新提问。", versions=HostVersions(
                                puzzleVersion=owner.puzzleVersion, ruleVersion=owner.ruleVersion,
                                engineVersion=owner.engineVersion))
        response = _response(owner, result, remaining)
        response.safeResponse["code"] = "turn_expired"
        response.safeResponse["state"] = "expired"
        conn.execute("""UPDATE turns SET state='expired',kind='system_error',charged=0,
            response_json=?,result_json=?,lease_token=NULL,lease_expires_at=NULL,completed_at=? WHERE id=?""",
            (_envelope(response), result.model_dump_json(), now, row["id"]))
        _audit_business(conn, "turn_expired", session_id, now=now, request_id=row["request_id"],
            turn_id=row["id"], details=_host_details(result, reason="turn_expired"))
    conn.execute("UPDATE sessions SET row_version=row_version+1,last_activity_at=? WHERE id=?", (now, session_id))
    return len(expired)


def expire_reserved_turns(session_id: str, *, now: float | None = None) -> int:
    with _transaction() as conn:
        _session(conn, session_id)
        return _expire(conn, session_id, _timestamp(now))


def get_turn_response(session_id: str, request_id: str, *, now: float | None = None) -> TurnReplay | None:
    with _transaction() as conn:
        _session(conn, session_id)
        _expire(conn, session_id, _timestamp(now))
        row = conn.execute("SELECT * FROM turns WHERE session_id=? AND request_id=?", (session_id, request_id)).fetchone()
        return _replay(row) if row is not None else None


def finish_turn(owner: TurnReservation, result: HostResult, *, now: float | None = None, cancelled=None) -> TurnReplay:
    # Fence the lease/version before one atomic commit of the linked message
    # pair, charge, saved response and audit. A completed request replays its
    # receipt; an expired owner cannot overwrite the recovered terminal state.
    # Revalidate copied/injected HostResult objects too; model_copy bypasses
    # Pydantic's constructor validation and must never grant a charge.
    result = HostResult.model_validate(result.model_dump(mode="python"))
    if (result.versions.puzzleVersion, result.versions.ruleVersion, result.versions.engineVersion) != (
            owner.puzzleVersion, owner.ruleVersion, owner.engineVersion):
        raise GameConflict("result_version_conflict")
    expired = False
    with _transaction() as conn:
        now = _timestamp(now)
        session = _session(conn, owner.sessionId)
        row = conn.execute("SELECT * FROM turns WHERE id=? AND session_id=?", (owner.turnId, owner.sessionId)).fetchone()
        if row is None or (row["request_id"], row["question"], row["lease_token"], row["puzzle_version"],
                           row["rule_version"], row["engine_version"]) != (
                owner.requestId, owner.question, owner.leaseToken, owner.puzzleVersion, owner.ruleVersion, owner.engineVersion):
            raise GameConflict("turn_owner_stale")
        if row["state"] != "reserved":
            return _replay(row)
        if row["lease_expires_at"] is None or row["lease_expires_at"] <= now:
            # Persist expiry before reporting the stale owner's failure. Raising
            # inside the transaction would silently undo the recovery.
            _expire(conn, owner.sessionId, now)
            expired = True
        else:
            _require_rule_available(conn, session["rule_version"])
            if (session["row_version"] != owner.expectedRowVersion or session["status"] != "playing"
                    or session["puzzle_version"] != owner.puzzleVersion or session["rule_version"] != owner.ruleVersion):
                raise GameConflict("turn_owner_stale")
            _bound_soup(conn, session)
            # Commit decision is the linearization point: cancellation observed
            # here becomes a failed noncharged turn. A later disconnect may
            # instead mean a committed response was lost, recovered by its ID.
            if cancelled is not None and cancelled.is_set():
                result = HostResult(kind="system_error", source="flow", chargeable=False, versions=result.versions,
                                    errorCode="model_cancelled", reply="这次提问已中止，没有扣次数；请重新提问。")
            charged = int(result.chargeable)
            if charged and session["question_limit"] is not None and session["questions_asked"] >= session["question_limit"]:
                raise GameConflict("turn_owner_stale")
            count = session["questions_asked"] + charged
            remaining = None if session["question_limit"] is None else max(0, session["question_limit"] - count)
            response = _response(owner, result, remaining)
            for role, content in (("user", owner.question), ("host", result.reply)):
                conn.execute("""INSERT INTO messages
                    (session_id,role,content,timestamp,is_free_reminder,turn_id) VALUES (?,?,?,?,?,?)""",
                    (owner.sessionId, role, content, now, 0 if charged else 1, owner.turnId))
            conn.execute("""UPDATE sessions SET questions_asked=?,status=?,solved_at=?,
                row_version=row_version+1,last_activity_at=? WHERE id=? AND row_version=?""",
                (count, "solved" if result.kind == "win" else "playing", now if result.kind == "win" else None,
                 now, owner.sessionId, owner.expectedRowVersion))
            conn.execute("""UPDATE turns SET state=?,kind=?,charged=?,response_json=?,result_json=?,
                lease_expires_at=NULL,completed_at=? WHERE id=? AND state='reserved' AND lease_token=?""",
                (response.state, result.kind, charged, _envelope(response), result.model_dump_json(), now,
                 owner.turnId, owner.leaseToken))
            details = _host_details(result)
            _audit_business(conn, "turn_committed", owner.sessionId, now=now, request_id=owner.requestId,
                turn_id=owner.turnId, details=details)
            _publish_after_commit(owner.sessionId, request_id=owner.requestId, turn_id=owner.turnId, details=details)
            return response
    if expired:
        raise GameConflict("turn_owner_stale")


def require_atomic_writer(conn, session_id):
    # Kept for embedded callers, but no managed/pinned/empty game may bypass
    # reserve/finish/evaluate. The old single-row writers are fully retired.
    raise GameConflict("atomic_writer_required")


def _messages(conn, session_id):
    rows = conn.execute("""SELECT role,content,timestamp,is_free_reminder,turn_id FROM messages
        WHERE session_id=? ORDER BY id""", (session_id,)).fetchall()
    return [{"role": m["role"], "content": m["content"], "timestamp": m["timestamp"],
             "isFreeReminder": bool(m["is_free_reminder"]), "turnId": m["turn_id"]} for m in rows]


def get_evaluation(session_id: str):
    from . import db
    session = db.get_session(session_id)
    if session is None:
        raise GameNotFound("session_not_found")
    db.require_compatible(session)
    return session["evaluation"]


def _read_scoring_snapshot(conn, session, soup):
    """Check linked rows under the caller's one read/write snapshot.

    Only the explicit 001 unverified marker is legacy. A malformed current
    result cannot be silently skipped as if it were ordinary uncertainty.
    """
    if soup.id != session["soup_id"]:
        raise baselines.SnapshotError("Scoring snapshot identity mismatch")
    rows = conn.execute("SELECT * FROM turns WHERE session_id=? ORDER BY rowid", (session["id"],)).fetchall()
    messages = _messages(conn, session["id"])
    pairs = {}
    row_ids = {row["id"] for row in rows}
    for message in messages:
        if message["turnId"] not in row_ids:
            raise baselines.SnapshotError("Unlinked or foreign scoring message")
        pairs.setdefault(message["turnId"], []).append(message)
    turns, history, excluded, private_results = [], [], 0, {}
    for row in rows:
        linked = pairs.get(row["id"], [])
        if row["payload_hash"] != baselines.digest({"question": row["question"]}):
            raise baselines.SnapshotError("Scoring request question digest mismatch")
        if (row["puzzle_version"], row["rule_version"]) != (session["puzzle_version"], session["rule_version"]):
            raise baselines.SnapshotError("Scoring turn/pinned session mismatch")
        if row["state"] == "reserved":
            if linked or row["result_json"] is not None:
                raise baselines.SnapshotError("Reserved turn has committed scoring data")
            continue
        if linked and (len(linked) != 2 or [message["role"] for message in linked] != ["user", "host"]
                       or linked[0]["content"] != row["question"]
                       or any(message["isFreeReminder"] != (row["charged"] == 0) for message in linked)):
            raise baselines.SnapshotError("Scoring turn/message pair mismatch")
        if row["engine_version"] == "legacy-unversioned":
            try:
                marker = baselines.strict_json(row["result_json"])
            except (ValueError, TypeError) as error:
                raise baselines.SnapshotError("Invalid unverified legacy marker") from error
            if (not isinstance(marker, dict) or set(marker) != {"schemaVersion", "source", "answerVerified"}
                    or type(marker["schemaVersion"]) is not int or marker["schemaVersion"] != 1
                    or marker["source"] != "legacy" or marker["answerVerified"] is not False
                    or row["state"] != "completed" or row["kind"] != ("answer" if row["charged"] else "reminder")
                    or len(linked) != 2 or row["response_json"] is not None):
                raise baselines.SnapshotError("Invalid unverified legacy turn")
            excluded += row["charged"]
            continue
        # Validates strict JSON/result, state, charge, row versions and saved
        # response identity even for failed/free rows that will earn no points.
        game_responses.turn_response(row)
        if row["result_json"] is None:
            if linked:
                raise baselines.SnapshotError("Limit-only turn unexpectedly has messages")
            continue
        result = game_responses._decode(HostResult, row["result_json"])
        if row["state"] != "expired" and (len(linked) != 2 or linked[1]["content"] != result.reply):
            raise baselines.SnapshotError("Committed turn lacks its original pair")
        private_results[row["id"]] = result
        if row["state"] == "completed" and row["charged"] and result.kind in {"answer", "win"}:
            try:
                turn = ConfirmedTurn(row["question"], result, row["id"], tuple(history))
            except ValueError as error:
                raise baselines.SnapshotError("Invalid confirmed turn") from error
            turns.append(turn)
            if result.kind == "answer" and result.source != "legacy":
                history.append((row["question"], result.answer))
    by_id = {turn.turnId: turn for turn in turns}
    for message in messages:
        result = private_results.get(message["turnId"])
        if result is not None:
            message["kind"] = result.kind
            if message["role"] == "host":
                message["hostResult"] = result
                if result.kind == "answer":
                    message["answer"] = result.answer
                if message["turnId"] in by_id:
                    message["confirmedTurn"] = by_id[message["turnId"]]
    return tuple(turns), excluded, messages


def read_confirmed_turns(conn, session, soup) -> tuple[ConfirmedTurn, ...]:
    return _read_scoring_snapshot(conn, session, soup)[0]


def get_private_host_history(session_id: str) -> list[dict]:
    from . import db
    db.initialize()
    conn = db._connect()
    try:
        conn.execute("BEGIN")
        session = _session(conn, session_id)
        soup = _bound_soup(conn, session)
        return _read_scoring_snapshot(conn, session, soup)[2]
    finally:
        conn.rollback()
        conn.close()


def evaluate_once(session_id: str, evaluator) -> dict:
    """Callback contract is trusted deterministic CPU work, never a model call."""
    with _transaction() as conn:
        session = _session(conn, session_id)
        now = _timestamp(None)
        _expire(conn, session_id, now)
        session = _session(conn, session_id)
        if conn.execute("SELECT 1 FROM turns WHERE session_id=? AND state='reserved'", (session_id,)).fetchone():
            raise GameConflict("turn_in_progress")
        old = conn.execute("SELECT * FROM evaluations WHERE session_id=?", (session_id,)).fetchone()
        if old is not None:
            response = game_responses.evaluation_response(old, session)
            _publish_after_commit(session_id, details=BusinessDetails(reasonCode="evaluation_created",
                versions=_pinned_versions(session)), replayed=True)
            return response
        _require_rule_available(conn, session["rule_version"])
        if session["status"] not in {"playing", "solved", "given_up"}:
            raise GameConflict("game_ended")
        soup = _bound_soup(conn, session)
        turns, excluded, _history = _read_scoring_snapshot(conn, session, soup)
        versions = HostVersions(puzzleVersion=session["puzzle_version"], ruleVersion=session["rule_version"])
        response = EvaluationResult.model_validate(evaluator(soup, turns, versions=versions,
            excluded_legacy_count=excluded), strict=True).model_dump(mode="json")
        basis = {"schemaVersion": 1, "puzzleVersion": session["puzzle_version"], "ruleVersion": session["rule_version"],
                 "scoreVersion": SCORE_VERSION, "questionsAsked": session["questions_asked"],
                 "excludedLegacyCount": excluded, "turns": [
                     {"turnId": turn.turnId, "question": turn.question, "result": turn.result.model_dump(mode="json"),
                      "history": turn.history} for turn in turns]}
        conn.execute("INSERT INTO evaluations (session_id,response_json,basis_hash,created_at) VALUES (?,?,?,?)",
                     (session_id, game_responses.pack_evaluation(session, response), baselines.digest(basis), now))
        conn.execute("""UPDATE sessions SET status=?,given_up_at=?,row_version=row_version+1,last_activity_at=? WHERE id=?""",
                     ("solved" if session["status"] == "solved" else "given_up",
                      session["given_up_at"] if session["status"] == "solved" else (session["given_up_at"] or now), now, session_id))
        details = BusinessDetails(reasonCode="evaluation_created", versions=_pinned_versions(session),
            trafficClass="test" if get_runtime().settings.TESTING else "real")
        _audit_business(conn, "evaluation_created", session_id, now=now, details=details)
        _publish_after_commit(session_id, details=details)
        return response
