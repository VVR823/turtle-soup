"""Only the explicit owned UI fixture may withdraw its original synthetic corpus."""
from uuid import uuid4

import pytest
from fastapi.testclient import TestClient

from app.config import Settings
from app.main import create_app
from app.test_server import fixture_app
from .test_ui_agent_fixture import app, prepare_feedback, start_and_wait, ADMIN

PATH = "/testing/corpus-availability"


@pytest.mark.parametrize("ui", [None, False])
def test_regular_and_api_only_app_have_no_corpus_control(tmp_path, ui):
    configured = Settings.for_test(tmp_path / "without-ui", TEST_INSTANCE_ID=str(uuid4()))
    application = create_app(configured) if ui is None else fixture_app(configured, ui_testing=False)
    with TestClient(application) as client:
        assert client.post(PATH, json={"available": False}).status_code == 404
        assert application.state.runtime.repair_corpus is None


@pytest.mark.parametrize("nonce", [None, "foreign-instance"])
def test_corpus_control_refuses_foreign_nonce_without_withdrawing(tmp_path, nonce):
    application = app(tmp_path)
    with TestClient(application) as client:
        original = application.state.runtime.repair_corpus
        headers = {} if nonce is None else {"X-Test-Instance-Id": nonce}
        response = client.post(PATH, json={"available": False}, headers=headers)
        assert response.status_code == 403, response.text
        assert application.state.runtime.repair_corpus == original


@pytest.mark.parametrize("body", [{"available": "false"}, {"available": 0},
    {"available": False, "path": "PRIVATE_TEST_CANARY"}, {}])
def test_corpus_control_cannot_coerce_or_select_external_material(tmp_path, body):
    application = app(tmp_path)
    with TestClient(application) as client:
        runtime = application.state.runtime
        original = runtime.repair_corpus
        response = client.post(PATH, json=body, headers={"X-Test-Instance-Id": runtime.settings.TEST_INSTANCE_ID})
        assert response.status_code == 422, response.text
        assert runtime.repair_corpus == original


def test_actual_withdrawal_refuses_loaded_approval_preserves_state_and_restores_original(tmp_path):
    application = app(tmp_path)
    with TestClient(application) as client:
        runtime = application.state.runtime
        corpus = runtime.repair_corpus
        headers = {"X-Test-Instance-Id": runtime.settings.TEST_INSTANCE_ID}
        fid, sid = prepare_feedback(client)
        status = start_and_wait(client, fid)
        assert status["state"] == "awaiting_review", status
        path = f'/api/feedback/admin/rule-candidates/{status["candidateId"]}'
        before = client.get(path, headers=ADMIN).json()
        game = client.get(f"/api/session/{sid}").json()
        assert before["availability"] == "ready" and before["candidateStatus"] == "pending"
        approval = dict(operationKey=str(uuid4()), expectedReviewVersion=before["reviewVersion"],
            expectedProofDigest=before["proofDigest"], answerSupported=True, contextIndependent=True,
            reviewNote="Declared synthetic corpus withdrawal scenario, not human quality")
        unavailable = client.post(PATH, json={"available": False}, headers=headers)
        assert unavailable.status_code == 200 and unavailable.json() == {"available": False}, unavailable.text
        assert runtime.repair_corpus is None
        declined = client.post(path + "/approve", json=approval, headers=ADMIN)
        assert declined.status_code == 409, declined.text
        after = client.get(path, headers=ADMIN).json()
        assert after["availability"] == "unavailable" and after["blockers"] == ["candidate_corpus_missing"]
        assert after["material"] is None and after["proofDigest"] is None
        for name in ["candidateStatus", "reviewVersion", "review", "activeRuleVersion", "activePointerVersion", "publishedRuleVersion"]:
            assert after[name] == before[name]
        assert client.get(f"/api/session/{sid}").json() == game
        restored = client.post(PATH, json={"available": True}, headers=headers)
        assert restored.status_code == 200 and restored.json() == {"available": True}, restored.text
        assert runtime.repair_corpus == corpus
        ready = client.get(path, headers=ADMIN).json()
        assert ready["availability"] == "ready" and ready["proofDigest"] == before["proofDigest"]
        valid = client.post(path + "/approve", json=approval, headers=ADMIN)
        assert valid.status_code == 200 and valid.json()["candidateStatus"] == "approved", valid.text
    assert runtime.agent_shutdown.cleanupConfirmed and runtime.model_shutdown["active"] == 0
