"""Independent TS06 review probes: synthetic inputs, guarded pytest only.

Failures assert the required behavior, not that today's buggy output is correct.
No production data, dotenv, real model, source edits or external connections.
"""
from contextlib import closing
import json
from uuid import uuid4

import pytest
from fastapi.testclient import TestClient

from app import ai_host, db
from app.config import Settings
from app.main import create_app
from app.runtime import runtime_context
from app.schemas import Checkpoint, ConfusionPoint, DifficultyLimits, Soup
from app.testing import FakeModel


def selected(**changes):
    return Soup(**{
        "id": "review-synthetic", "title": "Public synthetic review puzzle",
        "surface": "小明、小红、小王在一个故事里。",
        "bottom": "Synthetic: 小明是凶手，小红不是凶手，小王是警察。",
        "difficultyLimits": DifficultyLimits(xuermu=12, baozi=12, tianyi=12),
        **changes,
    })


def start(client):
    response = client.post("/api/chat", json={"soupId": "review-synthetic"})
    assert response.status_code == 200, response.text
    return response.json()["sessionId"]


def ask(client, sid, question):
    response = client.post("/api/chat", json={
        "sessionId": sid, "question": question, "requestId": str(uuid4()),
    })
    assert response.status_code == 200, response.text
    return response.json()


def stored(active):
    with runtime_context(active), closing(db._connect()) as conn, conn:
        return [json.loads(row[0]) for row in conn.execute(
            "SELECT result_json FROM turns ORDER BY rowid"
        )]


@pytest.mark.parametrize("reference", ["前者", "后者", "自己", "本人", "the former person"])
def test_authored_reference_needs_opposite_history_judgment(tmp_path, reference):
    soup = selected(confusionPoints=[ConfusionPoint(q=f"{reference}是凶手吗", a="是")])
    model = FakeModel("是")
    app = create_app(Settings.for_test(tmp_path), soups=[soup], model=model)
    with TestClient(app) as client:
        a, b = start(client), start(client)
        ask(client, a, f"接下来{reference}指的是小明，对吗？")
        ask(client, b, f"接下来{reference}指的是小红，对吗？")
        model.answer = "是"
        first = ask(client, a, f"{reference}是凶手吗？")
        model.answer = "不是"
        second = ask(client, b, f"{reference}是凶手吗？")
        rows = stored(app.state.runtime)[-2:]
        print("REFERENCE", reference, {
            "replies": [first["reply"], second["reply"]],
            "sources": [row["source"] for row in rows],
            "independent": [row["contextIndependent"] for row in rows],
            "cache_hits": [row["cacheHit"] for row in rows],
            "model_calls": len(model.calls),
            "charged": [client.get(f"/api/session/{sid}").json()["questionsAsked"] for sid in (a, b)],
        })
        assert [first["reply"], second["reply"]] == ["是", "不是"]
        assert all(row["source"] == "llm" and not row["cacheHit"] for row in rows)


@pytest.mark.parametrize("guard", ["如果", "假如", "即使", "只要", "除非"])
def test_conditional_checkpoint_cannot_prove_unconditional_consequent(tmp_path, guard):
    soup = selected(
        bottom="Synthetic: 小明不是医生，小王是警察，不是凶手。条件命题不陈述小王实际是凶手。",
        checkpoints=[Checkpoint(key=f"{guard}小明是医生，小王是凶手", answer=True,
                                aliases=["小王是凶手吗"])],
    )
    model = FakeModel("不是")
    app = create_app(Settings.for_test(tmp_path), soups=[soup], model=model)
    with TestClient(app) as client:
        reply = ask(client, start(client), "小王是凶手吗？")
        row = stored(app.state.runtime)[-1]
        print("CONDITIONAL", guard, {
            "reply": reply["reply"], "source": row["source"],
            "independent": row["contextIndependent"], "evidence": row["evidenceIds"],
            "model_calls": len(model.calls),
        })
        assert row["source"] == "llm" and reply["reply"] == "不是"
        assert len(model.calls) == 1


def test_bare_count_cannot_override_explicit_subset_history(tmp_path):
    soup = selected(castCount=3, bottom="Synthetic: 卧室里有小明、小红两个人，院子里只有小王。故事总共三个人。")
    model = FakeModel("是")
    app = create_app(Settings.for_test(tmp_path), soups=[soup], model=model)
    with TestClient(app) as client:
        sid = start(client)
        ask(client, sid, "接下来只讨论卧室里的人，对吗？")
        response = ask(client, sid, "有2个人吗？")
        row = stored(app.state.runtime)[-1]
        print("SUBSET_COUNT", {
            "reply": response["reply"], "source": row["source"],
            "independent": row["contextIndependent"], "model_calls": len(model.calls),
        })
        assert row["source"] == "llm" and response["reply"] == "是"
        assert len(model.calls) == 2


def test_retained_diagnostic_helper_handles_nonmatching_text():
    soup = selected(confusionPoints=[ConfusionPoint(q="小明是凶手吗", a="是")])
    assert ai_host.match_confusion_point(soup, "小红是医生吗") is None


def test_plain_named_rule_and_unsupported_question_preserve_normal_routes(tmp_path, request):
    assert getattr(request.config, "_turtle_network_guard", None) is not None
    soup = selected(checkpoints=[Checkpoint(key="小明是凶手", answer=True)])
    model = FakeModel("不是")
    app = create_app(Settings.for_test(tmp_path), soups=[soup], model=model)
    with TestClient(app) as client:
        a, b = start(client), start(client)
        assert ask(client, a, "小明是凶手吗？")["reply"] == "是"
        assert ask(client, b, "小明是凶手吗？")["reply"] == "是"
        rows = stored(app.state.runtime)
        assert rows[0]["cacheHit"] is False and rows[1]["cacheHit"] is True
        assert ask(client, a, "小红是医生吗？")["reply"] == "不是"
        assert stored(app.state.runtime)[-1]["source"] == "llm"
        assert len(model.calls) == 1
        assert client.get(f"/api/session/{a}").json()["questionsAsked"] == 2
        assert client.get(f"/api/session/{b}").json()["questionsAsked"] == 1
        assert client.get("/api/soups", params={"q": "不是凶手"}).json() == {"soups": []}
        reveal = client.post("/api/evaluate", json={"sessionId": a})
        assert reveal.status_code == 200 and reveal.json()["bottom"] == soup.bottom


def test_true_conjunction_still_licenses_supported_atoms(tmp_path):
    soup = selected(checkpoints=[Checkpoint(key="小明是凶手，小王是警察", answer=True)])
    model = FakeModel("不是")
    app = create_app(Settings.for_test(tmp_path), soups=[soup], model=model)
    with TestClient(app) as client:
        assert ask(client, start(client), "小王是警察吗？")["reply"] == "是"
        assert not model.calls


def test_existing_seed_reflexive_checkpoint_cannot_override_history(tmp_path):
    from app.soups import SEED_SOUPS

    # This is checked-in source, not a runtime catalog or private data file.
    soup = Soup(**next(raw for raw in SEED_SOUPS if raw.get("id") == "shuangyu-yupei"))
    assert any(cp.key == "自己也是复制体" for cp in soup.checkpoints)
    model = FakeModel("是")
    app = create_app(Settings.for_test(tmp_path), soups=[soup], model=model)
    with TestClient(app) as client:
        response = client.post("/api/chat", json={"soupId": soup.id})
        assert response.status_code == 200, response.text
        sid = response.json()["sessionId"]
        ask(client, sid, "接下来用自己指玩家本人，对吗？")
        model.answer = "不是"
        response = ask(client, sid, "自己也是复制体吗？")
        row = stored(app.state.runtime)[-1]
        print("EXISTING_SEED_REFLEXIVE", {
            "reply": response["reply"], "source": row["source"],
            "independent": row["contextIndependent"], "model_calls": len(model.calls),
        })
        assert row["source"] == "llm" and not row["contextIndependent"]
        assert len(model.calls) == 2


def test_unrecognized_authored_question_does_not_automatically_prove_static_scope(tmp_path):
    soup = selected(confusionPoints=[ConfusionPoint(q="former person has died吗", a="是")])
    model = FakeModel("不是")
    app = create_app(Settings.for_test(tmp_path), soups=[soup], model=model)
    with TestClient(app) as client:
        assert ask(client, start(client), "former person has died吗？")["reply"] == "不是"
        row = stored(app.state.runtime)[-1]
        assert row["source"] == "llm" and not row["contextIndependent"] and not row["cacheHit"]
        assert len(model.calls) == 1


def test_implicit_presence_metadata_cannot_prime_cache_for_subset_history(tmp_path):
    from app.schemas import TruthItem
    soup = selected(truthItems=[TruthItem(subject="故事", relation="不存在", object="魔法")])
    model = FakeModel("是")
    app = create_app(Settings.for_test(tmp_path), soups=[soup], model=model)
    with TestClient(app) as client:
        a, b = start(client), start(client)
        assert ask(client, a, "有魔法吗？")["reply"] == "不是"
        first = stored(app.state.runtime)[-1]
        assert not first["contextIndependent"] and not first["cacheHit"]
        ask(client, b, "接下来只讨论小红想象的世界，对吗？")
        assert ask(client, b, "有魔法吗？")["reply"] == "是"
        last = stored(app.state.runtime)[-1]
        assert last["source"] == "llm" and not last["cacheHit"]
        assert len(model.calls) == 2


def test_explicit_story_count_still_reuses_pure_source_bound_metadata(tmp_path):
    soup = selected(castCount=3)
    model = FakeModel("是")
    app = create_app(Settings.for_test(tmp_path), soups=[soup], model=model)
    with TestClient(app) as client:
        a, b = start(client), start(client)
        assert ask(client, a, "故事里一共有3个人吗？")["reply"] == "是"
        ask(client, b, "接下来只讨论卧室的人，对吗？")
        assert ask(client, b, "故事里一共有3个人吗？")["reply"] == "是"
        row = stored(app.state.runtime)[-1]
        assert row["source"] == "deterministic" and row["contextIndependent"] and row["cacheHit"]
        assert len(model.calls) == 1


@pytest.mark.parametrize("question", ["，", "吗？"])
def test_empty_assertion_scope_cannot_become_pure_by_vacuous_clause_check(tmp_path, question):
    soup = selected(confusionPoints=[ConfusionPoint(q=question, a="是")])
    app = create_app(Settings.for_test(tmp_path), soups=[soup], model=FakeModel("不是"))
    with TestClient(app) as client:
        ask(client, start(client), question)
        row = stored(app.state.runtime)[-1]
        assert row["source"] != "deterministic" and not row["contextIndependent"] and not row["cacheHit"]


def test_question_marks_only_get_friendly_free_reminder_not_system_failure(tmp_path):
    model = FakeModel("不是")
    app = create_app(Settings.for_test(tmp_path), soups=[selected()], model=model)
    with TestClient(app) as client:
        sid = start(client)
        reply = ask(client, sid, "？？？")
        assert reply["kind"] == "reminder" and reply["isFreeReminder"]
        assert client.get(f"/api/session/{sid}").json()["questionsAsked"] == 0
        assert not model.calls
