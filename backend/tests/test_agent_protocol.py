"""Real bounded gateway with owned synthetic responses; no cloud calls."""
import json
import time
from uuid import uuid4

import pytest

from .test_model_gateway import ScriptedTransport
from .test_repair_contracts import action_body


def invoke_raw(raw, *, response_contract="repair_action", transport=None):
    from app.model_gateway import ModelGateway
    transport = transport or ScriptedTransport([raw])
    gateway = ModelGateway(adapter_factory=lambda: transport)
    try:
        return gateway.invoke([], deadline=time.monotonic() + 2, max_attempts=1,
            traffic_class="agent", response_contract=response_contract)
    finally:
        state = gateway.close(wait_seconds=0.1)
        assert state["active"] == 0 and state["cleanup_failed"] == 0


@pytest.mark.parametrize("tool", ["get_turn_trace", "retrieve_truth", "find_rule_conflicts",
    "run_regression", "save_candidate_rule"])
def test_gateway_returns_actual_closed_model_selected_tool(tool):
    body = action_body(tool)
    transport = ScriptedTransport([json.dumps(body)])
    result = invoke_raw(None, transport=transport)
    assert result.action == "tool" and result.tool == tool
    assert result.arguments.model_dump(mode="json") == body["arguments"]
    assert len(transport.calls) == 1 and transport.closed == 1


@pytest.mark.parametrize("body", [dict(action="finish", needsHumanReason="Insufficient synthetic evidence"),
    dict(action="finish", candidateId=str(uuid4()))])
def test_gateway_valid_finish_does_not_become_host_judgment_or_approval(body):
    result = invoke_raw(json.dumps(body))
    assert result.action == "finish" and not hasattr(result, "answer")
    assert not hasattr(result, "approved") and result.model_dump(mode="json")[next(k for k in body if k != "action")] == body[next(k for k in body if k != "action")]


@pytest.mark.parametrize("raw", [
    '{"action":"finish","action":"finish","needsHumanReason":"PRIVATE synthetic"}',
    '{"action":"model_decision","promptDigest":"' + 'a' * 64 + '"}',
    '{"action":"tool","tool":"publish","arguments":{}}',
    '{"action":"finish","needsHumanReason":"synthetic","approved":true}',
    '{"action":"finish","candidateId":null,"needsHumanReason":NaN}',
    '{"answer":"是","reasoning":"PRIVATE synthetic"}',
    '{"action":"finish","needsHumanReason":"' + 'x' * 32768 + '"}',
    '[]', 'null', 'PRIVATE synthetic broken JSON',
], ids=["duplicate", "internal-intent", "privileged-tool", "approval-extra", "nan", "wrong-host-contract",
    "oversize", "array", "null", "broken-json"])
def test_gateway_bad_agent_json_has_one_real_attempt_no_raw_output_or_implicit_retry(raw):
    from app.model_gateway import ModelFailure
    transport = ScriptedTransport([raw])
    with pytest.raises(ModelFailure) as caught: invoke_raw(None, transport=transport)
    assert caught.value.code == "model_output_invalid" and "PRIVATE" not in str(caught.value)
    assert len(transport.calls) == 1 and transport.closed == 1


@pytest.mark.parametrize("contract", ["shell", "app.agents.contracts", None, 1, lambda value: value])
def test_server_response_contract_is_closed_not_a_model_callback_or_import_path(contract):
    transport = ScriptedTransport([])
    with pytest.raises(ValueError): invoke_raw(None, response_contract=contract, transport=transport)
    assert transport.calls == [] and transport.closed == 0


def test_default_host_contract_still_removes_reasoning_and_refuses_agent_json():
    from app.model_gateway import ModelGateway, ModelFailure
    transport = ScriptedTransport(['{"answer":"是","reasoning":"PRIVATE synthetic"}',
        '{"action":"finish","needsHumanReason":"synthetic"}'])
    gateway = ModelGateway(adapter_factory=lambda: transport)
    try:
        result = gateway.invoke([], deadline=time.monotonic() + 2, max_attempts=1)
        assert result.answer == "是" and result.reasoning == ""
        with pytest.raises(ModelFailure) as caught:
            gateway.invoke([], deadline=time.monotonic() + 2, max_attempts=1)
        assert caught.value.code == "model_output_invalid"
    finally:
        assert gateway.close(wait_seconds=0.1)["active"] == 0


def test_agent_injected_observation_is_actual_success_not_provider_or_token_receipt():
    from langchain_core.messages import AIMessage
    from app.audit_context import AttemptCollector, attempt_context
    from app.model_gateway import ModelGateway, InjectedAdapter
    class FixedAction:
        def invoke(self, messages):
            return AIMessage(content='{"action":"finish","needsHumanReason":"Synthetic handoff"}')
    gateway = ModelGateway(adapter_factory=lambda: InjectedAdapter(FixedAction()))
    collector = AttemptCollector(str(uuid4()), traffic_class="test")
    try:
        with attempt_context(collector):
            result = gateway.invoke([], deadline=time.monotonic() + 2, max_attempts=1,
                traffic_class="agent", response_contract="repair_action")
        event = collector.finish(status_code=200, method="POST", route_template="unmatched",
            response_started=True, disconnected=False)
        assert result.action == "finish"
        # Collector replaces a started observation with its same-ordinal
        # terminal observation, rather than counting two provider calls.
        assert [(call.ordinal, call.status) for call in event.details.modelCalls] == [(1, "succeeded")]
        assert all(call.provider == "injected" and call.model is None and call.usageStatus == "unknown"
            for call in event.details.modelCalls)
    finally:
        assert gateway.close(wait_seconds=0.1)["active"] == 0
