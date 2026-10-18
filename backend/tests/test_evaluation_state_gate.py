"""Frozen one-time reveal, terminal-state safety and concurrent calls."""
from contextlib import closing
from concurrent.futures import ThreadPoolExecutor
from threading import Barrier
from uuid import uuid4

from app import db
from app.runtime import runtime_context


def test_repeated_reveal_preserves_one_snapshot_and_ended_game_can_restore(client, application):
    sid = client.post("/api/chat", json={"soupId": "xin"}).json()["sessionId"]
    first = client.post("/api/evaluate", json={"sessionId": sid})
    assert first.status_code == 200
    assert client.post("/api/evaluate", json={"sessionId": sid}).content == first.content
    restored = client.get(f"/api/session/{sid}")
    assert restored.status_code == 200
    assert restored.json()["status"] == "given_up"
    assert restored.json()["evaluation"] == first.json()
    with runtime_context(application.state.runtime), closing(db._connect()) as conn, conn:
        assert conn.execute("SELECT COUNT(*) FROM evaluations WHERE session_id=?", (sid,)).fetchone()[0] == 1
    assert client.post("/api/chat", json={"sessionId": sid, "question": "他是凶手吗？"}).status_code == 409


def test_win_stays_solved_after_reveal_and_original_win_request_replays(client, application):
    sid = client.post("/api/chat", json={"soupId": "xinshijie"}).json()["sessionId"]
    payload = {"sessionId": sid, "question": "我是不是还在织梦者的那个梦里", "requestId": str(uuid4())}
    win = client.post("/api/chat", json=payload)
    assert win.status_code == 200 and win.json()["isWin"] is True
    assert client.post("/api/evaluate", json={"sessionId": sid}).status_code == 200
    with runtime_context(application.state.runtime):
        session = db.get_session(sid)
        assert session["status"] == "solved" and session["givenUpAt"] is None
        assert session["questionsAsked"] == 1
    assert client.post("/api/chat", json=payload).content == win.content


def test_concurrent_reveal_returns_one_response_and_one_persisted_basis(client, application):
    sid = client.post("/api/chat", json={"soupId": "xin"}).json()["sessionId"]
    gate = Barrier(3)

    def reveal():
        gate.wait(timeout=2)
        return client.post("/api/evaluate", json={"sessionId": sid})

    with ThreadPoolExecutor(max_workers=3) as pool:
        responses = list(pool.map(lambda _: reveal(), range(3)))
    assert all(response.status_code == 200 and response.content == responses[0].content for response in responses)
    with runtime_context(application.state.runtime), closing(db._connect()) as conn, conn:
        assert conn.execute("SELECT COUNT(*) FROM evaluations WHERE session_id=?", (sid,)).fetchone()[0] == 1
