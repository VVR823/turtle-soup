"""Real local HTTP recovery contracts, including a blocked injected model."""
from contextlib import closing
from concurrent.futures import ThreadPoolExecutor
from threading import Event
from uuid import uuid4

import pytest
from fastapi.testclient import TestClient
from langchain_core.messages import AIMessage
from langchain_core.runnables import RunnableLambda

from app import db
from app.config import Settings
from app.main import create_app
from app.runtime import runtime_context
from app.schemas import Soup


def game(client, soup_id="synthetic", request_id=None):
    response = client.post("/api/chat", json={"soupId": soup_id, "requestId": request_id or str(uuid4())})
    assert response.status_code == 200
    return response.json()["sessionId"]


def synthetic():
    return Soup(id="synthetic", title="Synthetic", surface="Surface", bottom="Synthetic private truth")


def test_api_creation_retry_recovers_original_game_and_changed_payload_conflicts(client):
    request_id = str(uuid4())
    payload = {"soupId": "xin", "level": "tianyi", "requestId": request_id}
    first = client.post("/api/chat", json=payload)
    assert client.post("/api/chat", json=payload).content == first.content
    conflict = client.post("/api/chat", json={**payload, "level": "baozi"})
    assert conflict.status_code == 409 and conflict.json()["code"] == "creation_payload_conflict"
    assert conflict.json()["requestId"] == request_id


@pytest.mark.parametrize("output,status,count", [
    ('{"answer":"是","reasoning":"synthetic"}', 200, 1), ("malformed-synthetic", 503, 0),
])
def test_lost_answer_or_failure_response_replays_exactly_without_another_model_call(tmp_path, output, status, count):
    calls = []
    model = RunnableLambda(lambda _: (calls.append(1), AIMessage(content=output))[1])
    app = create_app(Settings.for_test(tmp_path), model=model, soups=[synthetic()])
    with TestClient(app) as client:
        sid, request_id = game(client), str(uuid4())
        payload = {"sessionId": sid, "question": "他是凶手吗？", "requestId": request_id}
        first = client.post("/api/chat", json=payload)
        assert first.status_code == status
        assert first.json()["state"] == ("completed" if status == 200 else "failed")
        attempts = len(calls)
        assert attempts == (1 if status == 200 else 2)
        assert client.post("/api/chat", json=payload).content == first.content
        queried = client.get(f"/api/session/{sid}/turns/{request_id}")
        assert queried.status_code == status and queried.content == first.content
        assert len(calls) == attempts
        assert client.get(f"/api/session/{sid}").json()["questionsAsked"] == count
        assert client.post("/api/chat", json={**payload, "question": "他不是凶手吗？"}).status_code == 409
        other_sid = game(client)
        assert client.get(f"/api/session/{other_sid}/turns/{request_id}").status_code == 404
        assert client.get(f"/api/session/{sid}/turns/not-a-uuid").status_code == 422


def test_blocked_model_allows_db_write_but_rejects_other_turn_and_reveal(tmp_path):
    entered, release = Event(), Event()
    calls = []

    def block(_):
        calls.append(1)
        entered.set()
        assert release.wait(timeout=3)
        return AIMessage(content='{"answer":"不是","reasoning":"synthetic"}')

    app = create_app(Settings.for_test(tmp_path), model=RunnableLambda(block), soups=[synthetic()])
    with TestClient(app) as client, ThreadPoolExecutor(max_workers=1) as pool:
        sid, request_id = game(client), str(uuid4())
        payload = {"sessionId": sid, "question": "他是凶手吗？", "requestId": request_id}
        future = pool.submit(client.post, "/api/chat", json=payload)
        try:
            assert entered.wait(timeout=1)
            with runtime_context(app.state.runtime), closing(db._connect()) as independent, independent:
                independent.execute("BEGIN IMMEDIATE")
                independent.rollback()
            replay = client.post("/api/chat", json=payload)
            assert replay.status_code == 202 and replay.json()["state"] == "reserved"
            query = client.get(f"/api/session/{sid}/turns/{request_id}")
            assert query.status_code == 202
            conflict = client.post("/api/chat", json={**payload, "requestId": str(uuid4())})
            assert conflict.status_code == 409 and conflict.json()["code"] == "turn_in_progress"
            reveal = client.post("/api/evaluate", json={"sessionId": sid})
            assert reveal.status_code == 409 and reveal.json()["code"] == "turn_in_progress"
        finally:
            release.set()
        assert future.result(timeout=2).status_code == 200
        assert len(calls) == 1
        assert client.get(f"/api/session/{sid}").json()["questionsAsked"] == 1


def test_manual_reveal_command_is_a_real_free_idempotent_turn(client):
    sid, request_id = game(client, "xin"), str(uuid4())
    payload = {"sessionId": sid, "requestId": request_id, "question": "我放弃了"}
    first = client.post("/api/chat", json=payload)
    assert first.status_code == 200 and first.json()["kind"] == "reminder"
    assert first.json()["isFreeReminder"] is True
    assert first.json()["turnId"]
    assert client.post("/api/chat", json=payload).content == first.content
    assert client.get(f"/api/session/{sid}").json()["questionsAsked"] == 0
