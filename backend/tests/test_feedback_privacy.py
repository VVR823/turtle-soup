"""Manual sanitized permission is distinct from approval, no cloud calls."""
import hashlib
import json

import pytest
from pydantic import ValidationError

from app import audit_store, db
from .test_feedback_storage import body, completed_turn, rows, snapshot, storage


def permission(**changes):
    from app.feedback_contract import PrivacyReview
    values = dict(safeForModel=True, reviewedForPrivacy=True, reviewNote="Synthetic manual confirmation",
        sanitizedQuestion="是谁？", sanitizedHostAnswer="是", sanitizedExpectedClaim="不知道", sanitizedReason=None)
    return PrivacyReview(**{**values, **changes})


def approved_linked():
    from app.feedback_store import review_feedback, submit_feedback
    owner = completed_turn()
    submitted = submit_feedback(body(turnId=owner.turnId))
    return review_feedback(submitted.id, 0, status="approved")


@pytest.mark.parametrize("change", [
    {"reviewedForPrivacy": False}, {"reviewedForPrivacy": "true"}, {"reviewNote": ""},
    {"sanitizedQuestion": None}, {"sanitizedHostAnswer": ""}, {"sanitizedExpectedClaim": None},
    {"reviewNote": "x" * 1001}, {"cloudEndpoint": "PRIVATE"},
], ids=["not-reviewed", "coerced-bool", "no-note", "no-question", "no-host", "no-claim", "long-note", "extra-endpoint"])
def test_no_automatic_clearance_or_partial_sanitized_input(change):
    with pytest.raises(ValidationError):
        permission(**change)


def test_sanitized_input_hash_and_original_preserved(storage):
    from app.feedback_store import set_model_permission
    item = approved_linked(); before = rows("feedback_items")[0]["payload_json"]
    result = set_model_permission(item.id, item.rowVersion, review=permission())
    row = rows("feedback_items")[0]; private = json.loads(row["source_json"])["privacy"]
    expected = {"question": "是谁？", "hostAnswer": "是", "expectedClaim": "不知道", "reason": None}
    digest = hashlib.sha256(json.dumps(expected, sort_keys=True, ensure_ascii=False, separators=(",", ":")).encode()).hexdigest()
    assert row["payload_json"] == before and "PRIVATE synthetic claim" in before
    assert private["sanitizedInput"] == expected and private["inputDigest"] == digest
    assert result.rowVersion == 2 and result.safeForModel and result.status == "approved"
    assert rows("audit_events")[-1]["event_type"] == "feedback_privacy"
    assert "PRIVATE" not in rows("audit_events")[-1]["details_json"] and storage.model.calls == []


def test_permission_cas_cannot_overwrite_newer_decision(storage):
    from app.feedback_contract import FeedbackError
    from app.feedback_store import set_model_permission
    item = approved_linked()
    set_model_permission(item.id, item.rowVersion, review=permission())
    before = snapshot()
    with pytest.raises(FeedbackError) as caught:
        set_model_permission(item.id, item.rowVersion, review=permission())
    assert caught.value.code == "feedback_version_conflict" and snapshot() == before


def test_permission_audit_refusal_rolls_back_original_and_permission(storage, monkeypatch):
    from app.feedback_store import set_model_permission
    item = approved_linked(); before = snapshot()
    def denied(*_args):
        raise audit_store.AuditPersistenceError("Synthetic audit refusal")
    monkeypatch.setattr(audit_store, "insert_business_event", denied)
    with pytest.raises(audit_store.AuditPersistenceError):
        set_model_permission(item.id, item.rowVersion, review=permission())
    assert snapshot() == before and rows("feedback_items")[0]["safe_for_model"] == 0


def test_explicit_revoke_increases_version_preserves_original_and_no_model(storage):
    from app.feedback_contract import PrivacyReview
    from app.feedback_store import set_model_permission
    item = approved_linked()
    granted = set_model_permission(item.id, item.rowVersion, review=permission())
    original = rows("feedback_items")[0]["payload_json"]
    revoked = set_model_permission(item.id, granted.rowVersion,
        review=PrivacyReview(safeForModel=False, reviewNote="Revoke synthetic permission"))
    assert revoked.rowVersion == 3 and revoked.safeForModel is False
    assert rows("feedback_items")[0]["payload_json"] == original and storage.model.calls == []
