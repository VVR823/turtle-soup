"""Synthetic UI setup lives only in the explicit owned fixture, never production."""
from dataclasses import replace
from uuid import uuid4

import pytest
from fastapi.testclient import TestClient

from app.config import Settings
from app.main import create_app


def settings(tmp_path, **changed):
    return Settings.for_test(tmp_path / "ui-stop", TEST_INSTANCE_ID=str(uuid4()), **changed)


def test_regular_app_never_exposes_rule_fixture_even_in_testing(tmp_path):
    with TestClient(create_app(settings(tmp_path))) as client:
        assert client.post("/testing/rule-suspension", json={}).status_code == 404


def test_api_only_fixture_has_no_rule_setup_route(tmp_path):
    from app.test_server import fixture_app
    with TestClient(fixture_app(settings(tmp_path), ui_testing=False)) as client:
        assert client.post("/testing/rule-suspension", json={}).status_code == 404


@pytest.mark.parametrize("nonce", [None, "foreign-instance"])
def test_ui_rule_setup_requires_exact_owned_instance_nonce(tmp_path, nonce):
    from app.test_server import fixture_app
    configured = settings(tmp_path)
    with TestClient(fixture_app(configured, ui_testing=True)) as client:
        session = client.post("/api/chat", json={"soupId": "xin"}).json()["sessionId"]
        headers = {} if nonce is None else {"X-Test-Instance-Id": nonce}
        denied = client.post("/testing/rule-suspension", json={"sessionId": session, "suspended": True}, headers=headers)
        assert denied.status_code == 403 and not client.get(f"/api/session/{session}").json()["ruleSuspended"]


def test_owned_ui_fixture_only_changes_real_marker_for_same_original_game(tmp_path):
    from app.test_server import fixture_app
    configured = settings(tmp_path)
    with TestClient(fixture_app(configured, ui_testing=True)) as client:
        session = client.post("/api/chat", json={"soupId": "xin"}).json()["sessionId"]
        original = client.get(f"/api/session/{session}").json()
        headers = {"X-Test-Instance-Id": configured.TEST_INSTANCE_ID}
        for paused in (True, False):
            marked = client.post("/testing/rule-suspension", json={"sessionId": session, "suspended": paused}, headers=headers)
            assert marked.status_code == 200, marked.text
            restored = client.get(f"/api/session/{session}").json()
            assert restored["ruleSuspended"] is paused and restored["sessionId"] == session
            assert restored["puzzleVersion"] == original["puzzleVersion"] and restored["ruleVersion"] == original["ruleVersion"]
            assert restored["messages"] == [] and restored["questionsAsked"] == 0
        assert client.post("/testing/rule-suspension", json={"sessionId": session, "suspended": "yes"}, headers=headers).status_code == 422


def test_ui_fixture_refuses_non_testing_settings_or_absent_nonce(tmp_path):
    from app.test_server import fixture_app
    configured = settings(tmp_path)
    for altered in (replace(configured, TESTING=False), replace(configured, TEST_INSTANCE_ID="")):
        with pytest.raises(ValueError): fixture_app(altered, ui_testing=True)
