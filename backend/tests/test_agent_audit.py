"""Agent event data never becomes free-form reasoning or publication authority."""
from uuid import uuid4

import pytest
from pydantic import ValidationError


def details(**changes):
    from app.audit_events import AgentBusinessDetails
    body = dict(runId=str(uuid4()), action="queued", state="queued", rowVersion=0,
        payloadDigest="a" * 64, modelAttemptsUsed=0, toolAttemptsUsed=0, trafficClass="test")
    return AgentBusinessDetails(**{**body, **changes})


def test_agent_business_event_binds_exact_action_state_and_owned_run():
    from app.audit_events import AuditEvent
    value = details()
    event = AuditEvent(eventId=str(uuid4()), eventType="agent_run", runId=value.runId, createdAt=100.0, details=value)
    assert event.details.action == "queued"
    for changes in ({"eventType": "agent_step"}, {"eventType": "rule_published"}, {"runId": str(uuid4())}):
        with pytest.raises(ValidationError): AuditEvent.model_validate_json(
            event.model_copy(update=changes).model_dump_json(warnings="error"))


@pytest.mark.parametrize("extra", ["question", "factPayload", "reasoning", "rawOutput", "reviewReceipt", "leaseToken"])
def test_agent_audit_cannot_persist_private_content_or_grant_human_approval(extra):
    with pytest.raises(ValidationError): details(**{extra: "synthetic-private-data"})


@pytest.mark.parametrize("changes", [{"state": "running"}, {"action": "publish"},
    {"modelAttemptsUsed": True}, {"modelAttemptsUsed": 11}, {"toolAttemptsUsed": 9}])
def test_run_event_cannot_misstate_transition_or_exceed_budget(changes):
    with pytest.raises(ValidationError): details(**changes)
