"""Permanent TS-04 independent-review regressions; guarded synthetic inputs."""
from contextlib import closing
import json
import time
from concurrent.futures import ThreadPoolExecutor
from threading import Event
from uuid import UUID, uuid4

import pytest
from fastapi.testclient import TestClient

from app import db, game_service, migrations
from app.config import Settings
from app.main import create_app
from app.runtime import runtime_context
from app.schemas import DifficultyLimits, HostResult, HostVersions, Soup
from app.testing import FakeModel


@pytest.fixture
def api(tmp_path):
    soup = Soup(id="synthetic", title="Synthetic", surface="Public surface",
                bottom="Synthetic private truth", genre="本格",
                difficultyLimits=DifficultyLimits(xuermu=3, baozi=4, tianyi=5))
    app = create_app(Settings.for_test(tmp_path / "api"), model=FakeModel(), soups=[soup])
    with TestClient(app, raise_server_exceptions=False) as client:
        yield app, client


def start(client):
    response = client.post("/api/chat", json={"soupId": "synthetic", "requestId": str(uuid4())})
    assert response.status_code == 200
    return response.json()["sessionId"]


def answer(client, sid):
    payload = {"sessionId": sid, "requestId": str(uuid4()), "question": "这是本格吗？"}
    response = client.post("/api/chat", json=payload)
    assert response.status_code == 200
    return payload, response


def test_saved_turn_rejects_unknown_private_fields(api):
    app, client = api
    sid = start(client)
    payload, first = answer(client, sid)
    with runtime_context(app.state.runtime), closing(db._connect()) as conn, conn:
        row = conn.execute("SELECT response_json FROM turns WHERE session_id=? AND request_id=?",
                           (sid, payload["requestId"])).fetchone()
        envelope = json.loads(row[0])
        envelope["body"]["bottom"] = "Synthetic private truth"
        envelope["body"]["providerDebug"] = "synthetic internal detail"
        conn.execute("UPDATE turns SET response_json=? WHERE session_id=? AND request_id=?",
                     (json.dumps(envelope), sid, payload["requestId"]))
    response = client.get(f"/api/session/{sid}/turns/{payload['requestId']}")
    print("unknown-fields replay:", response.status_code, response.json())
    assert response.status_code == 503, "Corrupt saved response must fail closed"


def test_saved_turn_rejects_another_sessions_valid_envelope(api):
    app, client = api
    first_sid, other_sid = start(client), start(client)
    payload, _ = answer(client, first_sid)
    other_payload, _ = answer(client, other_sid)
    with runtime_context(app.state.runtime), closing(db._connect()) as conn, conn:
        other = conn.execute("SELECT response_json FROM turns WHERE session_id=? AND request_id=?",
                             (other_sid, other_payload["requestId"])).fetchone()[0]
        conn.execute("UPDATE turns SET response_json=? WHERE session_id=? AND request_id=?",
                     (other, first_sid, payload["requestId"]))
    response = client.get(f"/api/session/{first_sid}/turns/{payload['requestId']}")
    print("foreign-envelope replay:", response.status_code,
          "foreign capability returned:", response.json().get("sessionId") == other_sid)
    assert response.status_code == 503, "Replay identity must agree with its stored turn"


@pytest.mark.parametrize("field,value", [("state", "failed"), ("kind", "reminder"),
                                        ("isFreeReminder", True), ("isWin", True)])
def test_saved_turn_rejects_status_or_charge_disagreement_with_its_own_row(api, field, value):
    app, client = api
    sid = start(client)
    payload, _ = answer(client, sid)
    with runtime_context(app.state.runtime), closing(db._connect()) as conn, conn:
        raw = conn.execute("SELECT response_json FROM turns WHERE session_id=? AND request_id=?",
                           (sid, payload["requestId"])).fetchone()[0]
        saved = json.loads(raw)
        saved["body"][field] = value
        conn.execute("UPDATE turns SET response_json=? WHERE session_id=? AND request_id=?",
                     (json.dumps(saved), sid, payload["requestId"]))
    response = client.get(f"/api/session/{sid}/turns/{payload['requestId']}")
    assert response.status_code == 503
    assert response.json()["code"] == "snapshot_unavailable"


def test_saved_creation_rejects_another_sessions_valid_response(api):
    app, client = api
    first_id, second_id = str(uuid4()), str(uuid4())
    payload = {"soupId": "synthetic", "requestId": first_id}
    first = client.post("/api/chat", json=payload).json()
    second = client.post("/api/chat", json={"soupId": "synthetic", "requestId": second_id}).json()
    with runtime_context(app.state.runtime), closing(db._connect()) as conn, conn:
        conn.execute("UPDATE creation_requests SET response_json=? WHERE request_id=?",
                     (json.dumps(second), first_id))
    response = client.post("/api/chat", json=payload)
    print("foreign creation replay:", response.status_code,
          "foreign capability returned:", response.json().get("sessionId") == second["sessionId"],
          "original capability returned:", response.json().get("sessionId") == first["sessionId"])
    assert response.status_code == 503, "Saved creation identity must match the creation row"


def test_saved_evaluation_rejects_another_sessions_response(api):
    app, client = api
    first_sid, second_sid = start(client), start(client)
    for sid in (first_sid, second_sid):
        assert client.post("/api/evaluate", json={"sessionId": sid}).status_code == 200
    with runtime_context(app.state.runtime), closing(db._connect()) as conn, conn:
        raw = conn.execute("SELECT response_json FROM evaluations WHERE session_id=?", (second_sid,)).fetchone()[0]
        conn.execute("UPDATE evaluations SET response_json=? WHERE session_id=?", (raw, first_sid))
    assert client.get(f"/api/session/{first_sid}").status_code == 503


@pytest.mark.parametrize("target", ["creation", "evaluate", "restore"])
def test_malformed_saved_json_returns_safe_recoverable_error(api, target):
    app, client = api
    request_id = str(uuid4())
    payload = {"soupId": "synthetic", "requestId": request_id}
    sid = client.post("/api/chat", json=payload).json()["sessionId"]
    if target != "creation":
        assert client.post("/api/evaluate", json={"sessionId": sid}).status_code == 200
    with runtime_context(app.state.runtime), closing(db._connect()) as conn, conn:
        if target == "creation":
            conn.execute("UPDATE creation_requests SET response_json=? WHERE session_id=?", ("{", sid))
        else:
            conn.execute("UPDATE evaluations SET response_json=? WHERE session_id=?", ("{", sid))
    if target == "creation":
        response = client.post("/api/chat", json=payload)
    elif target == "evaluate":
        response = client.post("/api/evaluate", json={"sessionId": sid})
    else:
        response = client.get(f"/api/session/{sid}")
    print("malformed saved JSON:", target, response.status_code, response.text)
    assert response.status_code == 503
    assert response.json()["code"] == "snapshot_unavailable"
    UUID(response.json()["requestId"])


def test_empty_migrated_game_cannot_reopen_through_legacy_writer(tmp_path):
    from .test_migrations import old_database, puzzle
    root = tmp_path / "empty-legacy"
    root.mkdir()
    conn = old_database(root / "sessions.db")
    conn.execute("DELETE FROM messages")
    conn.execute("UPDATE sessions SET questions_asked=0")
    conn.commit()
    report = migrations.migrate(conn, [puzzle()], target_version=2)  # Existing HTTP regression now boots M2.
    assert report["compatibleSessions"] == 1
    assert conn.execute("SELECT count(*) FROM turns").fetchone()[0] == 0
    conn.close()
    app = create_app(Settings.for_test(root), model=FakeModel(), soups=[puzzle()])
    with TestClient(app) as client:
        first = client.post("/api/evaluate", json={"sessionId": "old"})
        assert first.status_code == 200
        with runtime_context(app.state.runtime):
            assert db.get_session("old")["status"] == "given_up"
            blocked = False
            try:
                db.update_session_status("old", "playing")
            except db.GameConflict:
                blocked = True
        later = client.post("/api/chat", json={"sessionId": "old", "question": "这是本格吗？",
                                              "requestId": str(uuid4())})
        restored = client.get("/api/session/old").json()
        print("empty-legacy bypass:", "blocked:", blocked, "late chat:", later.status_code,
              "status:", restored["status"], "questionsAsked:", restored["questionsAsked"],
              "old evaluation retained:", restored["evaluation"] == first.json())
        assert blocked, "Evaluation-managed empty legacy games must reject split writers"


def test_restore_status_and_evaluation_share_one_snapshot(api, monkeypatch):
    app, client = api
    sid = start(client)
    entered, release = Event(), Event()
    connect = db._connect

    class Cursor:
        def __init__(self, inner):
            self.inner = inner

        def fetchone(self):
            row = self.inner.fetchone()
            self.inner.fetchall()
            entered.set()
            assert release.wait(3)
            return row

    class Connection:
        def __init__(self):
            self.inner = connect()

        def execute(self, sql, args=()):
            cursor = self.inner.execute(sql, args)
            if sql.strip() == "SELECT * FROM sessions WHERE id = ?":
                return Cursor(cursor)
            return cursor

        def __getattr__(self, name):
            return getattr(self.inner, name)

    monkeypatch.setattr(db, "_connect", Connection)
    with ThreadPoolExecutor(max_workers=1) as pool:
        future = pool.submit(client.get, f"/api/session/{sid}")
        try:
            assert entered.wait(2)
            reveal = client.post("/api/evaluate", json={"sessionId": sid})
            assert reveal.status_code == 200
        finally:
            release.set()
        response = future.result(2)
    body = response.json()
    assert response.status_code == 200
    assert (body["status"] == "playing") == (body["evaluation"] is None)

def test_restore_count_and_pair_share_one_snapshot(api, monkeypatch):
    app, client = api
    sid = start(client)
    with runtime_context(app.state.runtime):
        owner = db.reserve_turn(sid, str(uuid4()), "这是本格吗？")
    entered, release = Event(), Event()
    connect = db._connect

    class Cursor:
        def __init__(self, inner):
            self.inner = inner

        def fetchone(self):
            row = self.inner.fetchone()
            self.inner.fetchall()
            entered.set()
            assert release.wait(3)
            return row

    class Connection:
        def __init__(self):
            self.inner = connect()

        def execute(self, sql, args=()):
            cursor = self.inner.execute(sql, args)
            if sql.strip() == "SELECT * FROM sessions WHERE id = ?":
                return Cursor(cursor)
            return cursor

        def __getattr__(self, name):
            return getattr(self.inner, name)

    monkeypatch.setattr(db, "_connect", Connection)
    with ThreadPoolExecutor(max_workers=1) as pool:
        future = pool.submit(client.get, f"/api/session/{sid}")
        try:
            assert entered.wait(2)
            with runtime_context(app.state.runtime):
                versions = HostVersions(puzzleVersion=owner.puzzleVersion, ruleVersion=owner.ruleVersion)
                result = HostResult(kind="answer", answer="是", chargeable=True, source="deterministic",
                                    reply="是", versions=versions)
                db.finish_turn(owner, result)
        finally:
            release.set()
        response = future.result(2)
    body = response.json()
    print("restore charge race:", response.status_code, "questionsAsked:", body["questionsAsked"],
          "remaining:", body["remaining"], "messages:", len(body["messages"]))
    assert body["questionsAsked"] == len(body["messages"]) // 2


def test_success_and_failure_replay_keep_original_remaining_after_new_work_and_reveal(api):
    app, client = api
    sid = start(client)
    payload, first = answer(client, sid)
    second_payload, second = answer(client, sid)
    assert first.json()["remaining"] == 2 and second.json()["remaining"] == 1
    with runtime_context(app.state.runtime):
        owner = db.reserve_turn(sid, str(uuid4()), "Synthetic failed question?")
        versions = HostVersions(puzzleVersion=owner.puzzleVersion, ruleVersion=owner.ruleVersion)
        failure = HostResult(kind="system_error", chargeable=False, source="flow", reply="Synthetic failure",
                             errorCode="model_unavailable", versions=versions)
        failed = db.finish_turn(owner, failure)
    assert client.post("/api/evaluate", json={"sessionId": sid}).status_code == 200
    assert client.post("/api/chat", json=payload).content == first.content
    response = client.get(f"/api/session/{sid}/turns/{owner.requestId}")
    assert response.status_code == 503 and response.json() == failed.safeResponse


def test_free_reminder_does_not_consume_last_opportunity_during_concurrent_requests(api, monkeypatch):
    from app import ai_host
    app, client = api
    sid = start(client)
    answer(client, sid)
    answer(client, sid)
    entered, release = Event(), Event()
    original = ai_host.handle_host_response

    def blocked_reminder(soup, messages, question, *, versions=None):
        if question != "Synthetic reminder":
            return original(soup, messages, question, versions=versions)
        entered.set()
        assert release.wait(3)
        return HostResult(kind="reminder", source="flow", chargeable=False, reply="Synthetic reminder", versions=versions)

    monkeypatch.setattr(ai_host, "handle_host_response", blocked_reminder)
    with ThreadPoolExecutor(max_workers=1) as pool:
        future = pool.submit(client.post, "/api/chat", json={"sessionId": sid, "question": "Synthetic reminder",
                                                           "requestId": str(uuid4())})
        try:
            assert entered.wait(2)
            competing = client.post("/api/chat", json={"sessionId": sid, "question": "这是本格吗？",
                                                       "requestId": str(uuid4())})
            assert competing.status_code == 409
        finally:
            release.set()
        reminder = future.result(2)
    assert reminder.status_code == 200 and reminder.json()["remaining"] == 1
    _, final = answer(client, sid)
    assert final.json()["remaining"] == 0
    assert client.get(f"/api/session/{sid}").json()["questionsAsked"] == 3


def test_asgi_disconnect_after_multichunk_body_keeps_noncharged_failure(tmp_path, monkeypatch):
    from app import main
    from .test_request_disconnect import test_asgi_disconnect_persists_failure_and_late_answer_cannot_charge
    original = main.run_request

    async def multichunk(app, scope, receive, send):
        fragments = []

        async def chunked_receive():
            if fragments:
                return fragments.pop(0)
            message = await receive()
            if message["type"] == "http.request" and len(message.get("body", b"")) > 32:
                body = message["body"]
                split = len(body) // 2
                fragments.append({**message, "body": body[split:]})
                return {**message, "body": body[:split], "more_body": True}
            return message

        await original(app, scope, chunked_receive, send)

    monkeypatch.setattr(main, "run_request", multichunk)
    test_asgi_disconnect_persists_failure_and_late_answer_cannot_charge(tmp_path)
