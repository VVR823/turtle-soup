"""Public discovery cannot be used as a private truth-existence oracle."""
import pytest
from fastapi.testclient import TestClient
from langchain_core.messages import AIMessage
from langchain_core.runnables import RunnableLambda

from app import db
from app.config import Settings
from app.main import create_app
from app.runtime import runtime_context
from app.schemas import Checkpoint, Soup, TruthItem
from app.testing import FakeModel


def selected(hidden=False):
    return Soup(id="hidden" if hidden else "synthetic", title="Public Lighthouse",
                surface="Public seaside surface", tags=["PublicTag"], hidden=hidden,
                bottom="private-bottom-462", bottomSummary="private-summary-917",
                checkpoints=[Checkpoint(key="private-checkpoint-274", answer=True)],
                truthItems=[TruthItem(subject="private-subject-863", relation="身份是", object="private-object-859")])


@pytest.fixture
def public_client(tmp_path):
    app = create_app(Settings.for_test(tmp_path), model=FakeModel(), soups=[selected(), selected(True)])
    with TestClient(app) as client:
        yield client


@pytest.mark.parametrize("query", ["private-bottom-462", "private-summary-917", "private-checkpoint-274",
                                   "private-subject-863", "private-object-859"])
def test_private_only_terms_cannot_select_a_soup_even_when_hidden_is_unlocked(public_client, query):
    absent = public_client.get("/api/soups", params={"q": "no-such-public-word", "unlocked": "hidden"})
    response = public_client.get("/api/soups", params={"q": query, "unlocked": "hidden"})
    assert response.status_code == 200 and response.content == absent.content
    assert response.json() == {"soups": []}


@pytest.mark.parametrize("query", ["LIGHTHOUSE", "seaside", "publictag"])
def test_title_surface_tags_still_search_case_insensitively(public_client, query):
    response = public_client.get("/api/soups", params={"q": query})
    assert response.status_code == 200
    assert [item["id"] for item in response.json()["soups"]] == ["synthetic"]
    assert "private-" not in response.text


def test_public_overlap_selects_only_the_public_source_not_private_matching_soup(tmp_path):
    other = Soup(id="other", title="Other", surface="Public text mentions private-bottom-462.", bottom="Other private truth")
    app = create_app(Settings.for_test(tmp_path), model=FakeModel(), soups=[selected(), other])
    with TestClient(app) as client:
        assert [item["id"] for item in client.get("/api/soups", params={"q": "private-bottom-462"}).json()["soups"]] == ["other"]


def test_private_search_change_preserves_hidden_and_filter_semantics(public_client):
    assert [item["id"] for item in public_client.get("/api/soups").json()["soups"]] == ["synthetic"]
    assert {item["id"] for item in public_client.get("/api/soups", params={"unlocked": "hidden"}).json()["soups"]} == {"synthetic", "hidden"}
    with runtime_context(public_client.app.state.runtime):
        assert [s.id for s in db.get_all_soups(tag="PublicTag", difficulty=3)] == ["synthetic"]
        assert db.get_all_soups(tag="other") == []


def test_list_and_playing_state_omit_private_records_and_legal_reveal_keeps_truth(public_client):
    data = public_client.get("/api/soups").json()["soups"][0]
    assert not {"bottom", "bottomSummary", "checkpoints", "truthItems", "confusionPoints", "symbolMappings"} & data.keys()
    start = public_client.post("/api/chat", json={"soupId": "synthetic"})
    sid = start.json()["sessionId"]
    restored = public_client.get(f"/api/session/{sid}")
    assert restored.json()["status"] == "playing" and "private-" not in start.text + restored.text
    reveal = public_client.post("/api/evaluate", json={"sessionId": sid})
    assert reveal.status_code == 200 and reveal.json()["bottom"] == selected().bottom
    ended = public_client.get(f"/api/session/{sid}")
    assert ended.json()["evaluation"] == reveal.json()
    assert public_client.post("/api/evaluate", json={"sessionId": sid}).content == reveal.content
    assert public_client.get("/api/soups", params={"q": selected().bottom}).json() == {"soups": []}


def test_site_guard_still_protects_search_and_reveal_without_changing_legal_reveal(tmp_path):
    app = create_app(Settings.for_test(tmp_path, SITE_PASSWORD="synthetic-site"), model=FakeModel(), soups=[selected()])
    with TestClient(app) as client:
        headers = {"X-Site-Token": "synthetic-site"}
        assert client.get("/api/soups", params={"q": selected().bottom}).status_code == 401
        sid = client.post("/api/chat", headers=headers, json={"soupId": "synthetic"}).json()["sessionId"]
        assert client.post("/api/evaluate", json={"sessionId": sid}).status_code == 401
        assert client.get("/api/soups", headers=headers, params={"q": selected().bottom}).json() == {"soups": []}
        assert client.post("/api/evaluate", headers=headers, json={"sessionId": sid}).json()["bottom"] == selected().bottom


def test_model_and_not_found_errors_do_not_expose_private_puzzle_text(tmp_path):
    app = create_app(Settings.for_test(tmp_path), soups=[selected()], model=RunnableLambda(lambda _: AIMessage(content="malformed")))
    with TestClient(app) as client:
        sid = client.post("/api/chat", json={"soupId": "synthetic"}).json()["sessionId"]
        failed = client.post("/api/chat", json={"sessionId": sid, "question": "他是凶手吗？"})
        assert failed.status_code == 503 and "private-" not in failed.text
        missing = client.get("/api/session/nonexistent")
        assert missing.status_code == 404 and "private-" not in missing.text
