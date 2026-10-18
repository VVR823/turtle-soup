"""Feedback HTTP never infers approval/truth/permission or writes legacy JSONL."""
import json
from uuid import uuid4

import pytest
from fastapi.testclient import TestClient

from app import db
from app.config import Settings
from app.main import create_app
from app.runtime import runtime_context
from app.schemas import Soup
from app.testing import FakeModel

ADMIN = {"X-Admin-Token": "synthetic-admin"}
SITE = {"X-Site-Token": "synthetic-site"}


@pytest.fixture
def api(tmp_path):
    app = create_app(Settings.for_test(tmp_path / "feedback-http", SITE_PASSWORD="synthetic-site",
        ADMIN_TOKEN="synthetic-admin"), model=FakeModel("是"), soups=[Soup(id="synthetic", title="T",
        surface="S", bottom="Synthetic private fact")])
    with TestClient(app, raise_server_exceptions=False) as client:
        yield app, client


def body(**changes):
    return dict(soupId="synthetic", question="是谁？", hostAnswer="是", expectedAnswer="不知道",
        reason="PRIVATE synthetic claim", **changes)


def submit(api):
    response = api[1].post("/api/feedback", json=body(), headers=SITE)
    assert response.status_code == 200, response.text
    return response.json()["id"]


def test_feedback_http_stores_claim_in_db_not_legacy_file(api):
    identity = submit(api)
    listed = api[1].get("/api/feedback/admin", headers=ADMIN)
    assert listed.status_code == 200
    page = listed.json(); assert page["totalInRange"] == 1 and page["nextCursor"] is None
    item = page["feedbacks"][0]
    assert item["id"] == identity and item["expectedAnswer"] == "不知道"
    assert item["rowVersion"] == 0 and item["status"] == "pending" and not item["safeForModel"]
    assert not (api[0].state.runtime.settings.DATA_DIR / "feedback.jsonl").exists()
    assert api[0].state.runtime.model.calls == []


@pytest.mark.parametrize("headers", [{}, SITE, {"X-Admin-Token": "wrong"}])
def test_feedback_admin_still_requires_independent_credential(api, headers):
    assert api[1].get("/api/feedback/admin", headers=headers).status_code == 401


def test_missing_admin_configuration_is_closed_not_site_password_fallback(tmp_path):
    app = create_app(Settings.for_test(tmp_path / "no-admin", SITE_PASSWORD="synthetic-site"),
        model=FakeModel(), soups=[Soup(id="synthetic", title="T", surface="S", bottom="Fact")])
    with TestClient(app, raise_server_exceptions=False) as client:
        assert client.get("/api/feedback/admin", headers=SITE).status_code == 503


@pytest.mark.parametrize("action", ["approve", "reject"])
def test_review_requires_expected_version_and_returns_actual_server_item(api, action):
    identity = submit(api); path = f"/api/feedback/admin/{identity}/{action}"
    assert api[1].post(path, headers=ADMIN).status_code == 422
    reviewed = api[1].post(path, headers=ADMIN, json={"expectedRowVersion": 0})
    assert reviewed.status_code == 200, reviewed.text
    item = reviewed.json()["feedback"]
    assert item["rowVersion"] == 1 and item["status"] == ("approved" if action == "approve" else "rejected")
    assert item["reviewedAt"] and item["safeForModel"] is False
    stale = api[1].post(path, headers=ADMIN, json={"expectedRowVersion": 0})
    assert stale.status_code == 409 and stale.json()["code"] == "feedback_version_conflict"
    assert api[0].state.runtime.model.calls == []


@pytest.mark.parametrize("extra", [{"safeForModel": True}, {"status": "approved"}, {"rowVersion": 100}])
def test_player_cannot_send_permission_status_or_version(api, extra):
    response = api[1].post("/api/feedback", json={**body(), **extra}, headers=SITE)
    assert response.status_code == 422 and "PRIVATE" not in response.text


def test_permission_http_is_explicit_manual_cas_and_has_no_model_call(api):
    identity = submit(api); path = f"/api/feedback/admin/{identity}/privacy"
    content = dict(expectedRowVersion=0, safeForModel=True, reviewedForPrivacy=True, reviewNote="Synthetic review",
        sanitizedQuestion="谁是凶手？", sanitizedHostAnswer="是", sanitizedExpectedClaim="不知道", sanitizedReason=None)
    assert api[1].post(path, json=content, headers=SITE).status_code == 401
    assert api[1].post(path, json={**content, "reviewedForPrivacy": False}, headers=ADMIN).status_code == 422
    allowed = api[1].post(path, json=content, headers=ADMIN)
    assert allowed.status_code == 200, allowed.text
    assert allowed.json()["feedback"]["safeForModel"] and allowed.json()["feedback"]["rowVersion"] == 1
    assert api[1].post(path, json=content, headers=ADMIN).status_code == 409
    revoked = api[1].post(path, json={"expectedRowVersion": 1, "safeForModel": False, "reviewNote": "Revoke"}, headers=ADMIN)
    assert revoked.status_code == 200 and not revoked.json()["feedback"]["safeForModel"]
    assert revoked.json()["feedback"]["rowVersion"] == 2 and api[0].state.runtime.model.calls == []


@pytest.mark.parametrize("query", ["limit=101", "limit=0", "start=0&end=999999999", "cursor=not-valid", "status=anything"])
def test_list_has_bounded_query_and_no_raw_input_validation_echo(api, query):
    response = api[1].get("/api/feedback/admin?" + query, headers=ADMIN)
    assert response.status_code == 422 and "PRIVATE" not in response.text


def test_legacy_merge_remains_disabled_and_no_rule_publish_endpoint(api):
    response = api[1].post("/api/feedback/admin/merge-verified", headers=ADMIN)
    assert response.status_code == 410
    assert api[1].post("/api/rules/publish", json={}, headers=ADMIN).status_code == 404
    assert not (api[0].state.runtime.settings.DATA_DIR / "verified_qa_pairs.jsonl").exists()


def test_feedback_write_audit_failure_is_safe_and_rolls_back(api, monkeypatch):
    from app import audit_store
    insert = audit_store.insert_business_event
    def fail(conn, event):
        if event.eventType == "feedback_submitted":
            raise audit_store.AuditPersistenceError("PRIVATE failure")
        return insert(conn, event)
    monkeypatch.setattr(audit_store, "insert_business_event", fail)
    response = api[1].post("/api/feedback", json=body(), headers=SITE)
    assert response.status_code == 503 and "PRIVATE" not in response.text
    with runtime_context(api[0].state.runtime):
        conn = db._connect()
        try:
            assert conn.execute("SELECT count(*) FROM feedback_items").fetchone()[0] == 0
        finally: conn.close()


def test_session_restore_reports_suspension_without_truth_leak(api):
    from .test_rule_publication import prepare
    from .test_rule_suspension import stopped
    created = api[1].post("/api/chat", json={"soupId": "synthetic", "requestId": str(uuid4())}, headers=SITE)
    assert created.status_code == 200
    session_id = created.json()["sessionId"]
    with runtime_context(api[0].state.runtime): stopped(prepare())
    restored = api[1].get(f"/api/session/{session_id}", headers=SITE)
    assert restored.status_code == 200 and restored.json()["ruleSuspended"] is True
    assert restored.json()["messages"] == [] and "Synthetic private fact" not in restored.text
    rejected = api[1].post("/api/chat", json={"sessionId": session_id, "question": "他是凶手吗？",
        "requestId": str(uuid4())}, headers=SITE)
    assert rejected.status_code == 409 and rejected.json()["code"] == "rule_version_suspended"
