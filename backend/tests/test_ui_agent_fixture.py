"""Owned synthetic UI fixture executes real HTTP/worker/tools; never seeds a passing report."""
import time
from uuid import uuid4

from fastapi.testclient import TestClient

from app.config import Settings
from app.test_server import fixture_app

ADMIN = {"X-Admin-Token": "e2e-test-only"}
QUESTION = "小明是凶手吗？"


def app(tmp_path):
    return fixture_app(Settings.for_test(tmp_path / "owned-ui", ADMIN_TOKEN="e2e-test-only",
        TEST_INSTANCE_ID=str(uuid4())), ui_testing=True)


def prepare_feedback(client):
    created = client.post("/api/chat", json={"soupId": "synthetic-ui", "requestId": str(uuid4())})
    assert created.status_code == 200, created.text
    session = created.json()["sessionId"]
    turn = client.post("/api/chat", json={"sessionId": session, "question": QUESTION, "requestId": str(uuid4())})
    assert turn.status_code == 200 and turn.json()["reply"] == "不是", turn.text
    submitted = client.post("/api/feedback", json={"soupId": "synthetic-ui", "question": QUESTION,
        "hostAnswer": "不是", "expectedAnswer": "是", "reason": "Declared synthetic UI claim, not human quality",
        "turnId": turn.json()["turnId"]})
    assert submitted.status_code == 200, submitted.text
    fid = submitted.json()["id"]
    approved = client.post(f"/api/feedback/admin/{fid}/approve", headers=ADMIN, json={"expectedRowVersion": 0})
    assert approved.status_code == 200 and not approved.json()["feedback"]["safeForModel"]
    privacy = client.post(f"/api/feedback/admin/{fid}/privacy", headers=ADMIN,
        json={"expectedRowVersion": 1, "safeForModel": True, "reviewedForPrivacy": True,
            "reviewNote": "Synthetic manual privacy fixture", "sanitizedQuestion": QUESTION,
            "sanitizedHostAnswer": "不是", "sanitizedExpectedClaim": "是", "sanitizedReason": None})
    assert privacy.status_code == 200 and privacy.json()["feedback"]["rowVersion"] == 2
    return fid, session


def start_and_wait(client, fid):
    start = client.post("/api/feedback/admin/agent-runs", headers=ADMIN,
        json={"feedbackId": fid, "requestId": str(uuid4()), "expectedFeedbackVersion": 2})
    assert start.status_code == 202, start.text
    run = start.json()["runId"]
    deadline = time.monotonic() + 10
    while time.monotonic() < deadline:
        response = client.get(f"/api/feedback/admin/agent-runs/{run}", headers=ADMIN)
        assert response.status_code == 200, response.text
        value = response.json()
        if value["state"] not in {"queued", "running"}:
            return value
        time.sleep(0.03)
    raise AssertionError("Owned synthetic worker did not terminate within observation window")


def test_owned_ui_prepares_only_source_schema_corpus_not_a_candidate_or_approval(tmp_path):
    application = app(tmp_path)
    with TestClient(application) as client:
        runtime = application.state.runtime
        assert runtime.settings.TESTING and not runtime.settings.ALLOW_REAL_MODEL
        assert runtime.settings.ENABLE_AGENT and runtime.agent_worker is not None
        assert runtime.repair_corpus.manifest.inputCount == 2
        page = client.get("/api/feedback/admin/agent-runs", headers=ADMIN)
        assert page.status_code == 200 and page.json()["runs"] == []
        assert client.post("/api/chat", json={"soupId": "xin"}).status_code == 200
    assert runtime.agent_shutdown.cleanupConfirmed and not runtime.agent_shutdown.coordinatorAlive
    assert runtime.model_shutdown["active"] == 0


def test_owned_ui_metrics_schema_is_explicit_four_and_test_game_is_excluded(tmp_path):
    application = app(tmp_path)
    with TestClient(application) as client:
        created = client.post("/api/chat", json={"soupId": "synthetic-ui", "requestId": str(uuid4())})
        assert created.status_code == 200
        response = client.get("/api/metrics/admin", headers=ADMIN)
        assert response.status_code == 200
        value = response.json()
        assert value["summary"]["counts"]["sessionsCreated"] == 0
        assert value["summary"]["excluded"]["test"]["sessionsCreated"] == 1
        assert value["summary"]["excluded"]["test"]["httpAttempts"] == 1


def test_browser_fixture_real_worker_creates_own_complete_report_and_pending_candidate(tmp_path):
    application = app(tmp_path)
    with TestClient(application) as client:
        fid, session = prepare_feedback(client)
        status = start_and_wait(client, fid)
        assert status["state"] == "awaiting_review", status
        assert status["modelAttemptsUsed"] == 3 and status["toolAttemptsUsed"] == 2
        detail = client.get(f'/api/feedback/admin/rule-candidates/{status["candidateId"]}', headers=ADMIN)
        assert detail.status_code == 200, detail.text
        value = detail.json()
        assert value["candidateStatus"] == "pending" and value["review"] is None and value["reviewVersion"] == 0
        report = value["material"]["report"]
        assert report["status"] == "complete" and report["evidenceKind"] == "synthetic_fixture"
        assert report["inputCaseCount"] == report["passedCaseCount"] == len(report["caseResults"]) == 7
        assert value["material"]["oldTarget"]["answer"] == "不是" and value["material"]["draft"]["answer"] == "是"
        original = client.get(f"/api/session/{session}").json()
        assert original["questionsAsked"] == 1 and original["messages"][-1]["content"] == "不是"


def test_current_missing_corpus_is_real_unavailable_detail_not_a_fake_ready_ui(tmp_path):
    application = app(tmp_path)
    with TestClient(application) as client:
        fid, _ = prepare_feedback(client)
        status = start_and_wait(client, fid)
        assert status["state"] == "awaiting_review", status
        application.state.runtime.repair_corpus = None  # Explicit isolated withdrawal, not changing any gold labels.
        detail = client.get(f'/api/feedback/admin/rule-candidates/{status["candidateId"]}', headers=ADMIN).json()
        assert detail["availability"] == "unavailable" and detail["material"] is None and detail["proofDigest"] is None
        assert detail["blockers"] == ["candidate_corpus_missing"]


def test_recovered_public_pairs_keep_their_actual_completed_turn_id_without_private_host_result(tmp_path):
    application = app(tmp_path)
    with TestClient(application) as client:
        created = client.post("/api/chat", json={"soupId": "synthetic-ui"}).json()
        turn = client.post("/api/chat", json={"sessionId": created["sessionId"], "question": QUESTION}).json()
        restored = client.get(f'/api/session/{created["sessionId"]}').json()
        assert [message.get("turnId") for message in restored["messages"]] == [turn["turnId"], turn["turnId"]]
        assert all(set(message) == {"role", "content", "timestamp", "isFreeReminder", "turnId"} for message in restored["messages"])
        assert "hostResult" not in restored and "bottom" not in restored


def test_added_ui_agent_transport_preserves_unknown_question_fake_host_in_the_original_game(tmp_path):
    application = app(tmp_path)
    with TestClient(application) as client:
        created = client.post("/api/chat", json={"soupId": "xin"}).json()
        answer = client.post("/api/chat", json={"sessionId": created["sessionId"], "question": "这封信是在测试恢复吗？"})
        assert answer.status_code == 200, answer.text
        assert answer.json()["kind"] == "answer" and answer.json()["reply"] == "与此无关", answer.text
        restored = client.get(f'/api/session/{created["sessionId"]}').json()
        assert restored["questionsAsked"] == 1
