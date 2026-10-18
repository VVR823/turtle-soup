"""Synthetic local API scene/length checks; never a live endpoint."""
from uuid import UUID
import asyncio

import pytest


def test_strict_request_decodes_owned_body_once_and_reuses_the_checked_object():
    from app.request_contract import StrictJSONRequest

    async def scenario():
        receives = 0

        async def receive():
            nonlocal receives
            receives += 1
            return {"type": "http.request", "body": b'{"value":1}', "more_body": False}

        request = StrictJSONRequest({"type": "http", "method": "POST", "path": "/", "headers": []}, receive=receive)
        first = await request.json()
        second = await request.json()
        assert first is second
        assert first == {"value": 1}
        assert receives == 1

    asyncio.run(scenario())


def start(client):
    response = client.post("/api/chat", json={"soupId": "xin", "level": "tianyi"})
    assert response.status_code == 200
    return response.json()


@pytest.mark.parametrize("question", ["", " \n\t ", "问" * 501])
def test_invalid_question_length_is_422_not_an_empty_game(client, question):
    sid = start(client)["sessionId"]
    response = client.post("/api/chat", json={"sessionId": sid, "question": question})
    assert response.status_code == 422


@pytest.mark.parametrize("payload", [
    {}, {"soupId": "xin", "question": "会被丢弃的问题吗？"},
    {"sessionId": "synthetic", "question": "问题吗？", "level": "tianyi"},
    {"sessionId": "synthetic"},
])
def test_mixed_or_missing_business_scene_is_400(client, payload):
    response = client.post("/api/chat", json=payload)
    assert response.status_code == 400
    assert response.json()["code"] == "request_scene_invalid"


def test_legacy_redundant_soup_id_is_allowed_only_when_equal(client):
    sid = start(client)["sessionId"]
    equal = client.post("/api/chat", json={"sessionId": sid, "soupId": "xin", "question": "这是本格吗？"})
    assert equal.status_code == 200
    conflict = client.post("/api/chat", json={"sessionId": sid, "soupId": "not-xin", "question": "这是本格吗？"})
    assert conflict.status_code == 409
    assert conflict.json()["code"] == "session_soup_conflict"


def test_legacy_ids_generated_and_explicit_id_returned(client):
    created = start(client)
    UUID(created["requestId"])
    request_id = "a3c42ef1-6fc5-43bc-98cd-16d2c817642e"
    response = client.post("/api/chat", json={
        "sessionId": created["sessionId"], "question": "这是本格吗？", "requestId": request_id,
    })
    assert response.status_code == 200
    assert response.json()["requestId"] == request_id
    assert response.json()["kind"] in {"answer", "reminder", "win", "system_error"}


def test_malformed_id_and_wrong_scalar_types_are_422(client):
    for body in ({"soupId": "xin", "requestId": "not-a-uuid"}, {"soupId": 123}):
        response = client.post("/api/chat", json=body)
        assert response.status_code == 422


def test_validation_error_does_not_echo_player_input(client):
    private = "synthetic-private-input" * 40
    response = client.post("/api/chat", json={"sessionId": "synthetic", "question": private})
    assert response.status_code == 422
    assert private not in response.text
    assert "input" not in response.json()


@pytest.mark.parametrize("field,value", [
    ("question", "问" * 501), ("hostAnswer", "答" * 101),
    ("expectedAnswer", "答" * 101), ("reason", "理" * 2001),
])
def test_feedback_size_limits_are_validated(client, field, value):
    payload = {"soupId": "xin", "question": "问题吗？", "hostAnswer": "是",
               "expectedAnswer": "不是", "reason": ""}
    payload[field] = value
    assert client.post("/api/feedback", json=payload).status_code == 422
