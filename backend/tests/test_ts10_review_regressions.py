"""I1: refuse new blank claims, retain and safely reject historical records."""
import json

import pytest

from app import db
from app.runtime import runtime_context
from .test_feedback_http import ADMIN, SITE, api, body
from .test_feedback_import import imported, legacy, source_file
from .test_feedback_storage import storage


FIELDS = ("soupId", "question", "hostAnswer", "expectedAnswer")


@pytest.mark.parametrize("field", FIELDS)
@pytest.mark.parametrize("blank", [" \t ", "　"])
def test_new_required_blank_fields_are_rejected_before_feedback_write(api, field, blank):
    response = api[1].post("/api/feedback", headers=SITE, json={**body(), field: blank})
    assert response.status_code == 422, response.text
    page = api[1].get("/api/feedback/admin", headers=ADMIN).json()
    assert page["totalInRange"] == 0 and page["feedbacks"] == []
    assert api[0].state.runtime.model.calls == []


def test_meaningful_claim_whitespace_and_optional_empty_reason_remain_original(api):
    response = api[1].post("/api/feedback", headers=SITE,
        json={**body(), "hostAnswer": "  是 \t", "expectedAnswer": " 不知道　", "reason": ""})
    assert response.status_code == 200, response.text
    item = api[1].get("/api/feedback/admin", headers=ADMIN).json()["feedbacks"][0]
    assert item["hostAnswer"] == "  是 \t" and item["expectedAnswer"] == " 不知道　"
    assert item["reason"] == "" and not item["safeForModel"]


@pytest.mark.parametrize("field", FIELDS)
def test_blank_legacy_required_field_reports_bad_physical_row_without_losing_source(storage, tmp_path, field):
    source, digest, raw = source_file(tmp_path, [legacy(**{field: " \t "}), legacy(question="正常的另一条？")])
    report = imported(source, digest)
    assert report.imported == 1 and len(report.badRows) == 1 and report.needsReview
    assert report.badRows[0].lineNumber == 1 and report.badRows[0].code == "feedback_row_invalid"
    assert source.read_bytes() == raw and "PRIVATE" not in report.model_dump_json()


def historical(api, field, *, approved=False):
    response = api[1].post("/api/feedback", headers=SITE, json=body())
    assert response.status_code == 200, response.text
    identity = response.json()["id"]
    if approved:
        reviewed = api[1].post(f"/api/feedback/admin/{identity}/approve", headers=ADMIN,
            json={"expectedRowVersion": 0})
        assert reviewed.status_code == 200 and reviewed.json()["feedback"]["rowVersion"] == 1
    with runtime_context(api[0].state.runtime):
        conn = db._connect()
        try:
            raw = json.loads(conn.execute("SELECT payload_json FROM feedback_items WHERE id=?", (identity,)).fetchone()[0])
            raw[field] = " \t "
            # Owned synthetic snapshot of a record accepted before I1; never
            # mutate real player files or require the fixed API to accept it.
            conn.execute("UPDATE feedback_items SET payload_json=?,soup_id=? WHERE id=?", (json.dumps(raw), raw["soupId"], identity))
            conn.commit()
        finally: conn.close()
    return identity


@pytest.mark.parametrize("field", ["hostAnswer", "expectedAnswer"])
def test_previously_approved_historical_blank_can_be_rejected_without_payload_rewrite(api, field):
    identity = historical(api, field, approved=True)
    rejected = api[1].post(f"/api/feedback/admin/{identity}/reject", headers=ADMIN,
        json={"expectedRowVersion": 1})
    assert rejected.status_code == 200, rejected.text
    row = rejected.json()["feedback"]
    assert row["status"] == "rejected" and row["rowVersion"] == 2 and row[field] == " \t "
    assert not row["safeForModel"] and api[0].state.runtime.model.calls == []


@pytest.mark.parametrize("field", FIELDS)
def test_historical_blank_row_is_readable_but_approval_cannot_legalize_it(api, field):
    identity = historical(api, field)
    normal = api[1].post("/api/feedback", headers=SITE, json={**body(), "question": "正常反馈？"})
    assert normal.status_code == 200
    page = api[1].get("/api/feedback/admin", headers=ADMIN)
    assert page.status_code == 200 and page.json()["totalInRange"] == 2
    assert next(row for row in page.json()["feedbacks"] if row["id"] == identity)[field] == " \t "
    path = f"/api/feedback/admin/{identity}"
    denied = api[1].post(path + "/approve", headers=ADMIN, json={"expectedRowVersion": 0})
    assert denied.status_code == 422 and denied.json()["code"] == "feedback_required_fields_invalid"
    rejected = api[1].post(path + "/reject", headers=ADMIN, json={"expectedRowVersion": 0})
    assert rejected.status_code == 200, rejected.text
    row = rejected.json()["feedback"]
    assert row["status"] == "rejected" and row["rowVersion"] == 1 and row[field] == " \t "
    assert api[0].state.runtime.model.calls == []


@pytest.mark.parametrize("field", FIELDS)
def test_historical_blank_row_cannot_gain_model_permission_but_can_revoke(api, field):
    identity = historical(api, field); path = f"/api/feedback/admin/{identity}/privacy"
    permission = dict(expectedRowVersion=0, safeForModel=True, reviewedForPrivacy=True,
        reviewNote="Synthetic manual check", sanitizedQuestion="谁？", sanitizedHostAnswer="是",
        sanitizedExpectedClaim="不知道", sanitizedReason=None)
    denied = api[1].post(path, headers=ADMIN, json=permission)
    assert denied.status_code == 422 and denied.json()["code"] == "feedback_required_fields_invalid"
    revoked = api[1].post(path, headers=ADMIN,
        json=dict(expectedRowVersion=0, safeForModel=False, reviewNote="Synthetic revoke"))
    assert revoked.status_code == 200 and not revoked.json()["feedback"]["safeForModel"]
    assert revoked.json()["feedback"]["rowVersion"] == 1 and revoked.json()["feedback"][field] == " \t "
    assert api[0].state.runtime.model.calls == []
