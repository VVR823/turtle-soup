"""Strict private feedback/CAS contracts, no providers or production files."""
from uuid import uuid4

import pytest
from pydantic import ValidationError

from app.schemas import FeedbackSubmit


@pytest.mark.parametrize("value", [True, -1, "0", 1.0, 2**63])
def test_review_requires_real_bounded_integer_version(value):
    from app.feedback_contract import FeedbackReview
    with pytest.raises(ValidationError):
        FeedbackReview(expectedRowVersion=value)


def test_review_zero_is_valid_but_extra_approval_authority_is_not():
    from app.feedback_contract import FeedbackReview
    assert FeedbackReview(expectedRowVersion=0).expectedRowVersion == 0
    with pytest.raises(ValidationError):
        FeedbackReview(expectedRowVersion=0, safeForModel=True)


def test_privacy_record_requires_utc_time_and_a_complete_digest_pair():
    from app.feedback_contract import PrivacyRecord
    base = dict(schemaVersion=1, reviewedForPrivacy=False, reviewNote="Synthetic review",
        reviewedAt="2026-10-09T00:00:00Z", rowVersion=0, sanitizedInput=None, inputDigest=None)
    with pytest.raises(ValidationError, match="timestamp"):
        PrivacyRecord(**{**base, "reviewedAt": "2026-10-09T00:00:00"})
    with pytest.raises(ValidationError, match="Incomplete sanitized record"):
        PrivacyRecord(**{**base, "inputDigest": "a" * 64})


def test_private_view_is_frozen_and_claim_is_not_normalized_to_truth():
    from app.feedback_contract import FeedbackView
    view = FeedbackView(id=str(uuid4()), ts="2026-10-08T00:00:00Z", soupId="synthetic",
        question="是谁？", hostAnswer="是", expectedAnswer="不知道", rowVersion=0,
        safeForModel=False, sourceState="unverified")
    assert view.expectedAnswer == "不知道" and view.status == "pending" and view.mergedAnswer is None
    with pytest.raises(ValidationError):
        view.status = "approved"
    with pytest.raises(ValidationError):
        FeedbackView.model_validate({**view.model_dump(), "agentPermission": True})


def test_optional_turn_id_keeps_old_form_and_rejects_invalid_identity():
    body = dict(soupId="synthetic", question="是谁？", hostAnswer="是", expectedAnswer="不是")
    assert FeedbackSubmit(**body).turnId is None
    assert FeedbackSubmit(**body, turnId=str(uuid4())).turnId is not None
    for value in ("", "unknown", 123, "x" * 201):
        with pytest.raises(ValidationError):
            FeedbackSubmit(**body, turnId=value)


@pytest.mark.parametrize("field", ["status", "rowVersion", "safeForModel", "sourceState"])
def test_player_cannot_supply_review_or_permission_fields(field):
    with pytest.raises(ValidationError):
        FeedbackSubmit(soupId="synthetic", question="是谁？", hostAnswer="是", expectedAnswer="不知道",
            **{field: "approved"})


def feedback_details(**changes):
    from app.audit_events import FeedbackBusinessDetails
    values = dict(feedbackId=str(uuid4()), soupId="synthetic", rowVersion=0,
        action="submitted", payloadDigest="a" * 64, sourceState="unverified", trafficClass="synthetic")
    return FeedbackBusinessDetails(**{**values, **changes})


def test_feedback_audit_has_no_raw_input_or_host_charge_authority():
    details = feedback_details()
    assert "question" not in details.model_dump() and "charged" not in details.model_dump()
    for field in ("question", "expectedAnswer", "reasoning", "charged", "path"):
        with pytest.raises(ValidationError):
            feedback_details(**{field: "PRIVATE synthetic"})


@pytest.mark.parametrize("kind", ["feedback_submitted", "feedback_reviewed", "feedback_privacy", "feedback_imported"])
def test_registered_feedback_event_requires_exact_details_type(kind):
    from app.audit_events import AuditEvent, BusinessDetails
    action = {"feedback_submitted": "submitted", "feedback_reviewed": "approved",
        "feedback_privacy": "privacy_granted", "feedback_imported": "imported"}[kind]
    header = dict(eventId=str(uuid4()), eventType=kind, createdAt=100.0)
    event = AuditEvent(**header, details=feedback_details(action=action))
    assert event.eventType == kind and len(event.model_dump_json().encode()) <= 16384
    assert AuditEvent.model_validate_json(event.model_dump_json()) == event
    with pytest.raises(ValidationError):
        AuditEvent(**header, details=BusinessDetails(reasonCode="answer"))
    with pytest.raises(ValidationError):
        AuditEvent(**{**header, "eventType": "turn_committed"}, details=feedback_details(action=action))


def test_feedback_event_action_cannot_be_mislabeled_as_submitted():
    from app.audit_events import AuditEvent
    with pytest.raises(ValidationError):
        AuditEvent(eventId=str(uuid4()), eventType="feedback_submitted", createdAt=100.0,
            details=feedback_details(action="approved"))
