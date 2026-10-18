"""Normal gameplay and model formatting failures stay separate."""
import json

import pytest
from fastapi.testclient import TestClient
from langchain_core.messages import AIMessage
from langchain_core.runnables import RunnableLambda

from app import ai_host, db
from app.config import Settings
from app.main import create_app
from app.schemas import HostResult, Soup
from app.runtime import runtime_context
from app.soups import SEED_SOUPS


@pytest.mark.parametrize("question", ["他是凶手吗？", "是不是被杀了", "有没有别人", "所以他其实是凶手，对吗"])
def test_ordinary_questions_receive_a_typed_normal_answer(runtime, question):
    soup = Soup(id="synthetic", title="Synthetic", surface="Surface", bottom="A synthetic fact.")
    result = ai_host.handle_host_response(soup, [], question)
    assert isinstance(result, HostResult)
    assert result.kind == "answer"
    assert result.chargeable is True


def test_open_question_is_a_friendly_reminder_not_a_system_failure(runtime):
    soup = Soup(id="synthetic", title="Synthetic", surface="Surface", bottom="A synthetic fact.")
    result = ai_host.handle_host_response(soup, [], "为什么会这样")
    assert isinstance(result, HostResult)
    assert result.kind == "reminder"
    assert result.chargeable is False
    assert not runtime.model.calls


def test_bad_provider_output_is_not_irrelevant_and_does_not_charge(tmp_path):
    outputs = []
    def malformed(_):
        outputs.append(1)
        return AIMessage(content="synthetic-secret-key: 我不知道")
    model = RunnableLambda(malformed)
    soup = Soup(id="synthetic", title="Synthetic", surface="Surface", bottom="private-synthetic-truth")
    app = create_app(Settings.for_test(tmp_path), model=model, soups=[soup])
    with TestClient(app) as client:
        sid = client.post("/api/chat", json={"soupId": soup.id}).json()["sessionId"]
        response = client.post("/api/chat", json={"sessionId": sid, "question": "他是凶手吗？"})
        assert response.status_code == 503
        assert response.json()["kind"] == "system_error"
        assert response.json()["code"] == "model_output_invalid"
        assert response.json()["isFreeReminder"] is True
        assert "synthetic-secret-key" not in response.text
        assert "private-synthetic-truth" not in response.text
        assert len(outputs) == 2
        with runtime_context(app.state.runtime):
            assert db.get_session(sid)["questionsAsked"] == 0


def test_one_format_retry_can_recover_a_normal_game_without_extra_game_charge(tmp_path):
    outputs = iter(["not-json", json.dumps({"answer": "不是", "reasoning": "fixture"}, ensure_ascii=False)])
    model = RunnableLambda(lambda _: AIMessage(content=next(outputs)))
    soup = Soup(id="synthetic", title="Synthetic", surface="Surface", bottom="A synthetic fact.")
    with TestClient(create_app(Settings.for_test(tmp_path), model=model, soups=[soup])) as client:
        sid = client.post("/api/chat", json={"soupId": soup.id}).json()["sessionId"]
        answer = client.post("/api/chat", json={"sessionId": sid, "question": "他是凶手吗？"})
        assert answer.status_code == 200
        assert answer.json()["reply"] == "不是"
        assert answer.json()["kind"] == "answer"
        assert client.get(f"/api/session/{sid}").json()["questionsAsked"] == 1


@pytest.mark.parametrize("raw", SEED_SOUPS, ids=lambda raw: raw["id"])
def test_bundled_puzzle_normal_model_path_fits_budget_and_keeps_full_truth(runtime, raw):
    soup = Soup(**raw)
    records = [message for _ in range(12) for message in (
        {"role": "user", "content": "合成历史问题" * 30 + "吗？"}, {"role": "host", "content": "是"},
    )]
    question = "合成问法" * 124 + "吗？"  # 498 characters, legal API size.
    result = ai_host.call_llm(soup, records, question)
    assert result.kind == "answer"
    assert len(runtime.model.calls) == 1
    messages = runtime.model.calls[0]
    assert soup.bottom in messages[1]["content"]
    assert sum(len(message["content"]) for message in messages) <= 8000
