"""Real private ASGI routes over actually generated isolated candidates."""
from dataclasses import replace
from uuid import uuid4
import json

from fastapi.testclient import TestClient
import pytest

from app import db
from app.audit_events import AuditEvent
from app.main import create_app
from app.runtime import runtime_context
from .test_candidate_review_store import proposal
from .test_candidate_review_mutations import approve_intent, meta
from .test_agent_store import raw_rows
from .test_rule_snapshots import rule_storage, release_rows


ADMIN = {"X-Admin-Token": "synthetic-admin"}
ROOT = "/api/feedback/admin/"


@pytest.fixture
def api(rule_storage):
    owner, run, cid = proposal(rule_storage)
    settings = replace(rule_storage.settings, ENABLE_AGENT=False, ADMIN_TOKEN="synthetic-admin", SITE_PASSWORD="synthetic-site")
    app = create_app(settings, model=rule_storage.model, soups=rule_storage.soups, repair_corpus=rule_storage.repair_corpus)
    with TestClient(app, raise_server_exceptions=False) as client:
        yield app, client, owner, run, cid


def candidate_path(cid, action=""):
    return ROOT + "rule-candidates/" + cid + ("/" + action if action else "")


def business_state():
    conn = db._connect()
    try:
        metadata = [tuple(row) for row in conn.execute("SELECT key,value_json,row_version FROM runtime_meta ORDER BY key")]
    finally:
        conn.close()
    return (raw_rows("agent_runs"), raw_rows("rule_candidates"), release_rows(), metadata,
        [row for row in raw_rows("audit_events") if row["event_type"] != "http_attempt"])


def request_body(owner, cid, action):
    detail = owner.detail(cid)
    if action == "approve":
        return approve_intent(detail).model_dump(mode="json")
    if action == "reject":
        return dict(operationKey=str(uuid4()), expectedReviewVersion=detail.reviewVersion, reviewNote="Synthetic rejection")
    if action == "publish":
        return dict(operationKey=str(uuid4()), expectedReviewVersion=detail.reviewVersion,
            expectedProofDigest=detail.proofDigest, expectedRuleVersion=detail.activeRuleVersion,
            expectedPointerVersion=detail.activePointerVersion)
    return dict(operationKey=str(uuid4()), targetRuleVersion="r1:" + "f" * 64,
        expectedRuleVersion=detail.activeRuleVersion, expectedPointerVersion=detail.activePointerVersion,
        reason="Synthetic rollback")


def test_disabled_worker_can_list_and_read_existing_candidates_without_allocating_gateway(api):
    app, client, _, run, cid = api
    before = business_state()
    page = client.get(ROOT + "agent-runs", headers=ADMIN)
    assert page.status_code == 200, page.text
    assert page.json()["runs"][0]["id"] == run.id and page.json()["runs"][0]["candidateId"] == cid
    detail = client.get(candidate_path(cid), headers=ADMIN)
    assert detail.status_code == 200, detail.text
    assert detail.json()["availability"] == "ready" and detail.json()["agentStatus"]["state"] == "awaiting_review"
    assert len(detail.json()["material"]["report"]["caseResults"]) == 7
    assert app.state.runtime.agent_worker is None and app.state.runtime.model_gateway is None
    assert business_state() == before
    assert "leaseToken" not in detail.text and "PRIVATE synthetic claim" not in detail.text


@pytest.mark.parametrize("route", ["list", "detail", "approve", "reject", "publish", "rollback"])
@pytest.mark.parametrize("headers", [{}, {"X-Site-Token": "synthetic-site"}, {"X-Admin-Token": "wrong"}])
def test_all_six_routes_require_independent_admin_authority(api, route, headers):
    _, client, owner, _, cid = api
    before = business_state()
    if route in {"list", "detail"}:
        response = client.get(ROOT + "agent-runs" if route == "list" else candidate_path(cid), headers=headers)
    else:
        response = client.post(ROOT + "rule-releases/rollback" if route == "rollback" else candidate_path(cid, route),
            headers=headers, json=request_body(owner, cid, route))
    assert response.status_code == 401 and response.json()["code"] == "admin_token_required"
    assert business_state() == before


def test_http_approve_publish_rollback_and_historical_replay_are_separate_actions(api):
    app, client, owner, _, cid = api
    approve = request_body(owner, cid, "approve")
    approved = client.post(candidate_path(cid, "approve"), headers=ADMIN, json=approve)
    assert approved.status_code == 200, approved.text
    assert approved.json()["candidateStatus"] == "approved" and approved.json()["reviewVersion"] == 1
    assert len(release_rows()) == 1 and meta("active_baseline")[1] == 0
    publish = request_body(owner, cid, "publish")
    published = client.post(candidate_path(cid, "publish"), headers=ADMIN, json=publish)
    assert published.status_code == 200, published.text
    assert published.json()["candidateStatus"] == "published" and published.json()["reviewVersion"] == 2
    rollback = dict(operationKey=str(uuid4()), targetRuleVersion=publish["expectedRuleVersion"],
        expectedRuleVersion=published.json()["publishedRuleVersion"], expectedPointerVersion=1, reason="Synthetic API rollback")
    reverted = client.post(ROOT + "rule-releases/rollback", headers=ADMIN, json=rollback)
    assert reverted.status_code == 200 and reverted.json()["pointerVersion"] == 2
    before = business_state()
    assert client.post(candidate_path(cid, "approve"), headers=ADMIN, json=approve).json() == approved.json()
    assert client.post(candidate_path(cid, "publish"), headers=ADMIN, json=publish).json() == published.json()
    assert client.post(ROOT + "rule-releases/rollback", headers=ADMIN, json=rollback).json() == reverted.json()
    assert business_state() == before and app.state.runtime.model_gateway is None


@pytest.mark.parametrize("change", [{"expectedReviewVersion": True}, {"expectedReviewVersion": 0.0},
    {"expectedReviewVersion": "0"}, {"answerSupported": 1}, {"contextIndependent": False},
    {"reviewNote": " "}, {"reviewNote": "x" * 1001}, {"changeDraft": {}}, {"authorizer": "PRIVATE"}])
def test_invalid_review_body_does_not_modify_business_state_or_echo_private_input(api, change):
    _, client, owner, _, cid = api
    before = business_state()
    response = client.post(candidate_path(cid, "approve"), headers=ADMIN,
        json={**request_body(owner, cid, "approve"), **change})
    assert response.status_code == 422 and "PRIVATE" not in response.text
    assert business_state() == before


def test_duplicate_nonfinite_and_oversized_bodies_never_execute_review(api):
    _, client, owner, _, cid = api
    body = json.dumps(request_body(owner, cid, "approve"), ensure_ascii=False)
    values = [body[:-1] + ',"answerSupported":true}', body.replace('"expectedReviewVersion": 0', '"expectedReviewVersion": NaN')]
    before = business_state()
    for value in values:
        response = client.post(candidate_path(cid, "approve"), headers={**ADMIN, "Content-Type": "application/json"}, content=value)
        assert response.status_code == 422
    response = client.post(candidate_path(cid, "approve"), headers={**ADMIN, "Content-Type": "application/json"}, content="x" * 32769)
    assert response.status_code == 413 and business_state() == before


def test_rejecting_withdrawn_candidate_is_allowed_but_publication_is_not(api):
    from app.feedback_store import set_model_permission
    from app.feedback_contract import PrivacyReview
    app, client, owner, run, cid = api
    set_model_permission(run.feedbackId, run.manifest.context.sourceFeedbackVersion,
        review=PrivacyReview(safeForModel=False, reviewNote="Synthetic withdraw"))
    detail = client.get(candidate_path(cid), headers=ADMIN)
    assert detail.status_code == 200 and detail.json()["material"] is None
    rejected = client.post(candidate_path(cid, "reject"), headers=ADMIN, json=request_body(owner, cid, "reject"))
    assert rejected.status_code == 200 and rejected.json()["candidateStatus"] == "rejected"
    assert len(release_rows()) == 1 and app.state.runtime.model_gateway is None


def test_index_bad_limit_window_and_cursor_are_controlled_queries(api):
    _, client, _, _, _ = api
    for query in ("?limit=101", "?start=NaN", "?start=0&end=2678401", "?cursor=bad=", "?feedbackId=bad"):
        response = client.get(ROOT + "agent-runs" + query, headers=ADMIN)
        assert response.status_code == 422, response.text


def test_every_new_route_emits_registered_template_not_private_id_or_unmatched(api):
    app, client, owner, _, cid = api
    client.get(ROOT + "agent-runs", headers=ADMIN)
    client.get(candidate_path(cid), headers=ADMIN)
    for action in ("approve", "reject", "publish"):
        client.post(candidate_path(cid, action), headers={})
    client.post(ROOT + "rule-releases/rollback", headers={})
    with runtime_context(app.state.runtime):
        events = [AuditEvent.model_validate_json(row["details_json"]) for row in raw_rows("audit_events") if row["event_type"] == "http_attempt"]
    templates = {event.details.routeTemplate for event in events}
    assert {ROOT + "agent-runs", ROOT + "rule-candidates/{candidate_id}", ROOT + "rule-candidates/{candidate_id}/approve",
        ROOT + "rule-candidates/{candidate_id}/reject", ROOT + "rule-candidates/{candidate_id}/publish", ROOT + "rule-releases/rollback"} <= templates
    assert not any(cid in template for template in templates) and "unmatched" not in templates


def test_unconfigured_admin_is_unavailable_without_business_side_effects(api, monkeypatch):
    app, client, owner, _, cid = api
    before = business_state()
    monkeypatch.setattr(app.state.runtime, "settings", replace(app.state.runtime.settings, ADMIN_TOKEN=""))
    for path in (ROOT + "agent-runs", candidate_path(cid)):
        response = client.get(path, headers=ADMIN)
        assert response.status_code == 503 and response.json()["code"] == "admin_not_configured"
    response = client.post(candidate_path(cid, "approve"), headers=ADMIN, json=request_body(owner, cid, "approve"))
    assert response.status_code == 503 and business_state() == before


def test_schema2_admin_routes_never_initialize_feature_tables(rule_storage, tmp_path):
    from app.config import Settings
    app = create_app(Settings.for_test(tmp_path / "http-schema2", ADMIN_TOKEN="synthetic-admin"),
        model=rule_storage.model, soups=rule_storage.soups)
    with TestClient(app, raise_server_exceptions=False) as client:
        assert client.get(ROOT + "agent-runs", headers=ADMIN).status_code == 503
        assert client.get(candidate_path(str(uuid4())), headers=ADMIN).status_code == 503
        response = client.post(candidate_path(str(uuid4()), "reject"), headers=ADMIN,
            json=dict(operationKey=str(uuid4()), expectedReviewVersion=0, reviewNote="Synthetic reject"))
        assert response.status_code == 503
        assert app.state.runtime.model_gateway is None and app.state.runtime.agent_worker is None
        with runtime_context(app.state.runtime):
            conn = db._connect()
            try:
                assert conn.execute("SELECT name FROM sqlite_master WHERE name='agent_runs'").fetchone() is None
                assert conn.execute("SELECT name FROM sqlite_master WHERE name='rule_candidates'").fetchone() is None
            finally:
                conn.close()


@pytest.mark.parametrize("action,allowed", [("detail", 30), ("reject", 20)])
def test_changing_candidate_id_cannot_bypass_fixed_route_rate_bucket(api, monkeypatch, action, allowed):
    app, client, _, _, _ = api
    monkeypatch.setattr(app.state.runtime, "settings", replace(app.state.runtime.settings, RATE_LIMIT_ENABLED=True))
    before = business_state()
    for _ in range(allowed):
        path = candidate_path(str(uuid4()), "" if action == "detail" else action)
        response = client.get(path, headers=ADMIN) if action == "detail" else client.post(path, headers=ADMIN,
            json=dict(operationKey=str(uuid4()), expectedReviewVersion=0, reviewNote="Synthetic reject"))
        assert response.status_code == 404
    path = candidate_path(str(uuid4()), "" if action == "detail" else action)
    response = client.get(path, headers=ADMIN) if action == "detail" else client.post(path, headers=ADMIN,
        json=dict(operationKey=str(uuid4()), expectedReviewVersion=0, reviewNote="Synthetic reject"))
    assert response.status_code == 429 and int(response.headers["Retry-After"]) > 0
    assert business_state() == before
