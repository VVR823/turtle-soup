"""Permanent TS07 I1 regressions, synthetic source and guarded transport only.

An opaque predicate containing another assertion is not an atomic fact,
regardless of its connecting word. Conservative fallback is normal gameplay.
"""
from contextlib import closing
from uuid import uuid4

from fastapi.testclient import TestClient
import pytest

from app import baselines, db
from app.config import Settings
from app.host_rules import checkpoint_question_expectation, question_has_static_scope
from app.main import create_app
from app.runtime import runtime_context
from app.schemas import Checkpoint, HostResult, HostVersions, Soup
from app.scoring import ConfirmedTurn, score_confirmed_coverage
from app.testing import FakeModel


def puzzle(key):
    return Soup(id="ts07-review", title="Synthetic", surface="Synthetic public story",
                bottom="Synthetic: " + key, checkpoints=[Checkpoint(key=key, answer=True)])


def coverage(soup, question, answer):
    versions = HostVersions(
        puzzleVersion="p1:" + baselines.digest({"schemaVersion": 1, "soup": soup.model_dump(mode="json")}),
        ruleVersion="r1:" + "1" * 64,
    )
    host = HostResult(kind="answer", source="llm", answer=answer, chargeable=True,
                      versions=versions, reply=answer)
    return score_confirmed_coverage(soup, (ConfirmedTurn(question, host, "owned-turn"),), versions=versions)


@pytest.mark.parametrize("connector", ["且", "以及", "同时", "外加", "另一个身份", "。另外", "\n", "（"])
def test_denied_nested_assertion_never_confirms_entire_source(connector):
    soup = puzzle(f"小明是医生{connector}小王是舞者")
    question = f"小明不是医生{connector}小王是舞者吗"
    result = coverage(soup, question, "不是")
    assert result.verifiedCoverage == 0 and result.keyPointsCovered == ()
    assert checkpoint_question_expectation(soup, 0, question, []) is None


@pytest.mark.parametrize("key,question", [
    ("小明和小王是医生", "小明和小王不是医生吗"),
    ("小明是医生兼舞者", "小明不是医生兼舞者吗"),
    ("小明是既医生又舞者", "小明不是既医生又舞者吗"),
])
def test_coordinated_subject_or_predicate_is_not_a_single_polarity_proof(key, question):
    soup = puzzle(key)
    assert not question_has_static_scope(soup, key)
    assert coverage(soup, question, "不是").verifiedCoverage == 0


@pytest.mark.parametrize("connector", ["、", "而且", "并且"])
def test_recognized_complete_positive_conjunction_still_confirms(connector):
    soup = puzzle(f"小明是医生{connector}小王是舞者")
    assert coverage(soup, f"小明是医生{connector}小王是舞者吗", "是").verifiedCoverage == 100
    assert coverage(soup, f"小明不是医生{connector}小王是舞者吗", "不是").verifiedCoverage == 0


@pytest.mark.parametrize("key,question", [
    ("小明是医生", "小明不是医生吗"),
    ("小明被父亲杀死", "小明不是被父亲杀死的吗"),
])
def test_atomic_identity_and_passive_opposite_polarity_proof_remains(key, question):
    assert coverage(puzzle(key), question, "不是").verifiedCoverage == 100


@pytest.mark.parametrize("connector", ["且", "以及", "同时"])
def test_api_nested_compound_falls_through_normally_without_false_coverage(tmp_path, connector):
    key = f"小明是医生{connector}小王是舞者"
    soup = puzzle(key)
    model = FakeModel("不是")
    app = create_app(Settings.for_test(tmp_path / "compound-api"), model=model, soups=[soup])
    with TestClient(app) as client:
        create = client.post("/api/chat", json={"soupId": soup.id, "requestId": str(uuid4())})
        assert create.status_code == 200
        sid = create.json()["sessionId"]
        response = client.post("/api/chat", json={"sessionId": sid, "requestId": str(uuid4()),
                                                  "question": f"小明不是医生{connector}小王是舞者吗"})
        assert response.status_code == 200 and response.json()["reply"] == "不是"
        result = client.post("/api/evaluate", json={"sessionId": sid})
        assert result.status_code == 200
        assert result.json()["verifiedCoverage"] == 0 and result.json()["keyPointsCovered"] == []
        assert len(model.calls) == 1  # unsupported grammar is an ordinary answer, not system_error
        with runtime_context(app.state.runtime), closing(db._connect()) as conn, conn:
            row = conn.execute("SELECT result_json FROM turns WHERE session_id=?", (sid,)).fetchone()
            stored = baselines.strict_json(row[0])
            assert stored["source"] == "llm" and stored["cacheHit"] is False
        assert client.get(f"/api/session/{sid}").json()["questionsAsked"] == 1
