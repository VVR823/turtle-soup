"""Only administrator intent/version fields, never execution authority."""
from ..audit_events import CanonicalId
from ..feedback_contract import RowVersion
from .contracts import StrictAgentModel


class AgentStart(StrictAgentModel):
    feedbackId: CanonicalId
    requestId: CanonicalId
    expectedFeedbackVersion: RowVersion


class AgentCancel(StrictAgentModel):
    expectedRowVersion: RowVersion
