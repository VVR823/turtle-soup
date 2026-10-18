"""Unknown provider usage must stay unknown, never become fabricated zero."""
import pytest
from pydantic import ValidationError

from app.audit_events import AuditEvent, AttemptDetails, BusinessDetails, ModelCallObservation, TokenUsage


def test_missing_usage_serializes_as_null_not_zero():
    usage = TokenUsage()
    assert usage.model_dump() == {"inputTokens": None, "outputTokens": None, "totalTokens": None}


def test_explicit_zero_is_a_real_observation_not_unknown():
    usage = TokenUsage(inputTokens=0, outputTokens=0, totalTokens=0)
    assert usage.model_dump() == {"inputTokens": 0, "outputTokens": 0, "totalTokens": 0}


@pytest.mark.parametrize("field", ["inputTokens", "outputTokens", "totalTokens"])
@pytest.mark.parametrize("invalid", [-1, True, "1", 1.5, float("nan"), float("inf")])
def test_usage_rejects_invalid_provider_values(field, invalid):
    with pytest.raises(ValidationError):
        TokenUsage.model_validate({field: invalid})


@pytest.mark.parametrize("private", ["question", "reply", "bottom", "reasoning", "apiKey", "metadata"])
def test_usage_cannot_carry_private_or_arbitrary_provider_payload(private):
    with pytest.raises(ValidationError):
        TokenUsage.model_validate({private: "synthetic forbidden field"})


def test_usage_is_frozen_after_validation():
    usage = TokenUsage(inputTokens=12, outputTokens=3, totalTokens=15)
    with pytest.raises(ValidationError):
        usage.inputTokens = 99


def attempt(**changes):
    return AttemptDetails(method="POST", routeTemplate="/api/chat", statusCode=200, durationMs=1.25,
                          trafficClass="test", outcome="success", responseStarted=True, disconnected=False, **changes)


def event(details=None, **changes):
    body = {"eventId": "802939c0-e6de-414f-b8b9-121511a8a025", "eventType": "http_attempt",
            "createdAt": 100.0, "details": details if details is not None else attempt()}
    body.update(changes)
    return AuditEvent.model_validate(body)


def test_unobserved_host_fields_remain_null():
    details = event().details
    for field in ("source", "kind", "charged", "cacheHit", "versions", "reasonCode"):
        assert getattr(details, field) is None
    assert details.usage.totalTokens is None


@pytest.mark.parametrize("changed", [
    {"eventId": "not-a-uuid"}, {"eventId": "802939C0-E6DE-414F-B8B9-121511A8A025"},
    {"schemaVersion": True}, {"schemaVersion": "1"}, {"createdAt": -1.0}, {"createdAt": float("nan")},
    {"createdAt": float("inf")}, {"eventType": "invented"}, {"requestId": "not-a-request-id"},
    {"sessionId": "x" * 201}, {"rawReasoning": "synthetic secret"},
])
def test_event_rejects_unknown_identity_time_schema_and_private_fields(changed):
    with pytest.raises(ValidationError):
        event(**changed)


@pytest.mark.parametrize("changed", [
    {"method": "POST\nprivate"}, {"routeTemplate": "/api/session/private-player"},
    {"routeTemplate": "/api/chat?token=synthetic"}, {"statusCode": 99}, {"statusCode": 600},
    {"statusCode": True}, {"durationMs": -1.0}, {"durationMs": float("inf")},
    {"reasonCode": "model reasoning must not be accepted"}, {"source": "invented"},
    {"charged": "false"}, {"headers": {"Authorization": "synthetic secret"}},
])
def test_attempt_rejects_raw_paths_and_uncontrolled_metadata(changed):
    body = attempt().model_dump(); body.update(changed)
    with pytest.raises(ValidationError):
        AttemptDetails.model_validate(body)


def test_business_and_http_details_cannot_be_interchanged():
    with pytest.raises(ValidationError):
        event(details=BusinessDetails())
    with pytest.raises(ValidationError):
        event(eventType="turn_committed")
    assert event(eventType="turn_committed", details=BusinessDetails(reasonCode="answer")).eventType == "turn_committed"


def test_event_nested_payloads_are_immutable():
    item = event(details=attempt(evidenceIds=("fact:a",)))
    assert item.details.evidenceIds == ("fact:a",)
    with pytest.raises(ValidationError):
        item.details.evidenceIds = ("fact:b",)


def test_evidence_and_model_call_limits_are_actual_boundaries():
    with pytest.raises(ValidationError):
        attempt(evidenceIds=tuple(f"fact:{i}" for i in range(129)))
    with pytest.raises(ValidationError):
        attempt(evidenceIds=("x" * 201,))
    with pytest.raises(ValidationError):
        attempt(modelCalls=tuple(ModelCallObservation(ordinal=1, status="succeeded") for _ in range(3)))
    with pytest.raises(ValidationError):
        ModelCallObservation(ordinal=3, status="succeeded")
    with pytest.raises(ValidationError):
        ModelCallObservation(ordinal=1, status="succeeded", model="https://synthetic-key@provider/path")


def test_total_event_bytes_are_bounded_even_when_each_evidence_id_is_valid():
    with pytest.raises(ValidationError):
        event(details=attempt(evidenceIds=tuple(f"{i:03d}:" + "x" * 190 for i in range(128))))


def test_full_event_json_roundtrip_does_not_restore_private_fields():
    item = event(details=attempt(evidenceIds=("fact:a",), modelCalls=(ModelCallObservation(ordinal=1, status="succeeded"),)))
    restored = AuditEvent.model_validate_json(item.model_dump_json())
    assert restored == item
    assert "question" not in restored.model_dump_json()


@pytest.mark.parametrize("changed", [
    {"usageStatus": "known"},
    {"usageStatus": "unknown", "usage": TokenUsage(totalTokens=5)},
    {"usageStatus": "partial"},
    {"status": "started", "usageStatus": "known", "usage": TokenUsage(inputTokens=2, outputTokens=3, totalTokens=5)},
    {"status": "succeeded", "errorCode": "model_auth"},
    {"status": "failed"},
])
def test_model_observation_rejects_contradictory_status_and_usage(changed):
    body = {"ordinal": 1, "status": "succeeded"}; body.update(changed)
    with pytest.raises(ValidationError):
        ModelCallObservation.model_validate(body)
