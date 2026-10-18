"""Known metadata only; real gateway + MockTransport/FakeModel, no cloud."""
import time
from threading import Event

import httpx
import pytest
from langchain_core.messages import AIMessage

from app import audit_events
from app.audit_context import AttemptCollector, attempt_context
from app.config import Settings
from app.model_gateway import CompatibleAdapter, InjectedAdapter, ModelFailure, ModelGateway
from .test_audit_context import ID_A, ID_B, finish

CONTENT = '{"answer":"是","reasoning":"synthetic private reasoning"}'


@pytest.mark.parametrize("metadata,expected,status", [
    (None, (None, None, None), "unknown"),
    ({"prompt_tokens": 12, "completion_tokens": 3, "total_tokens": 15}, (12, 3, 15), "known"),
    ({"prompt_tokens": 12, "completion_tokens": 3}, (12, 3, None), "partial"),
    ({"prompt_tokens": "12", "completion_tokens": 3, "total_tokens": True}, (None, 3, None), "invalid"),
    ({"prompt_tokens": 0, "completion_tokens": 0, "total_tokens": 0}, (0, 0, 0), "known"),
    ({"prompt_tokens": -1, "completion_tokens": float("nan"), "total_tokens": 2**100000}, (None, None, None), "invalid"),
])
def test_provider_usage_normalization_retains_only_observed_strict_counts(metadata, expected, status):
    usage, actual_status = audit_events.normalize_usage(metadata, format="compatible")
    assert (usage.inputTokens, usage.outputTokens, usage.totalTokens) == expected
    assert actual_status == status


def test_compatible_metadata_does_not_change_existing_string_return_contract(tmp_path):
    adapter = CompatibleAdapter(Settings.for_test(tmp_path, LLM_PROVIDER="ollama", ALLOW_REAL_MODEL=True),
        transport=httpx.MockTransport(lambda _: httpx.Response(200, json={"choices": [{"message": {"content": CONTENT}}],
            "usage": {"prompt_tokens": 12, "completion_tokens": 3, "total_tokens": 15}, "model": "provider must not override configured identity"})))
    collector = AttemptCollector(ID_A)
    runner = ModelGateway(adapter_factory=lambda: adapter)
    try:
        with attempt_context(collector):
            result = runner.invoke([], deadline=time.monotonic() + 2)
        assert result.answer == "是" and result.reasoning == ""
        item = finish(collector)
        assert len(item.details.modelCalls) == 1
        call = item.details.modelCalls[0]
        assert call.provider == "ollama" and call.model == adapter.model
        assert call.usage.totalTokens == 15 and call.usageStatus == "known"
        assert call.status == "succeeded" and item.details.usage.totalTokens == 15
        assert "synthetic private reasoning" not in item.model_dump_json()
        assert "provider must not override" not in item.model_dump_json()
    finally:
        runner.close(wait_seconds=1)


@pytest.mark.parametrize("usage", [None, {"prompt_tokens": "wrong", "completion_tokens": 3}, {"total_tokens": -1}])
def test_provider_invalid_or_missing_usage_keeps_a_valid_answer(tmp_path, usage):
    adapter = CompatibleAdapter(Settings.for_test(tmp_path, LLM_PROVIDER="ollama", ALLOW_REAL_MODEL=True),
        transport=httpx.MockTransport(lambda _: httpx.Response(200, json={"choices": [{"message": {"content": CONTENT}}], "usage": usage})))
    collector = AttemptCollector(ID_A); runner = ModelGateway(adapter_factory=lambda: adapter)
    try:
        with attempt_context(collector):
            result = runner.invoke([], deadline=time.monotonic() + 2)
        assert result.answer == "是"
        item = finish(collector); assert len(item.details.modelCalls) == 1
        assert item.details.modelCalls[0].usage.totalTokens is None
        assert item.details.usage.totalTokens is None
    finally:
        runner.close(wait_seconds=1)


def test_injected_ai_message_usage_is_observed_without_response_metadata_secrets():
    class SyntheticModel:
        def invoke(self, _messages):
            return AIMessage(content=CONTENT, usage_metadata={"input_tokens": 12, "output_tokens": 3, "total_tokens": 15},
                             response_metadata={"apiKey": "synthetic secret", "model_name": "not program owned"})
    collector = AttemptCollector(ID_A); runner = ModelGateway(adapter_factory=lambda: InjectedAdapter(SyntheticModel()))
    try:
        with attempt_context(collector):
            assert runner.invoke([], deadline=time.monotonic() + 2).answer == "是"
        item = finish(collector); assert len(item.details.modelCalls) == 1
        assert item.details.usage.totalTokens == 15
        assert item.details.modelCalls[0].provider == "injected" and item.details.modelCalls[0].model is None
        assert "synthetic secret" not in item.model_dump_json() and "not program owned" not in item.model_dump_json()
    finally:
        runner.close(wait_seconds=1)


def test_retry_resets_adapter_usage_and_records_two_actual_attempts_with_unknown_total(tmp_path):
    responses = iter([
        httpx.Response(200, json={"choices": [{"message": {"content": "invalid HostJudgment"}}], "usage": {"prompt_tokens": 12, "completion_tokens": 3, "total_tokens": 15}}),
        httpx.Response(200, json={"choices": [{"message": {"content": CONTENT}}]}),
    ])
    adapter = CompatibleAdapter(Settings.for_test(tmp_path, LLM_PROVIDER="ollama", ALLOW_REAL_MODEL=True), transport=httpx.MockTransport(lambda _: next(responses)))
    collector = AttemptCollector(ID_A); runner = ModelGateway(adapter_factory=lambda: adapter)
    try:
        with attempt_context(collector):
            assert runner.invoke([], deadline=time.monotonic() + 2).answer == "是"
        item = finish(collector); assert len(item.details.modelCalls) == 2
        assert [call.ordinal for call in item.details.modelCalls] == [1, 2]
        assert [call.status for call in item.details.modelCalls] == ["failed", "succeeded"]
        assert item.details.modelCalls[0].errorCode == "model_output_invalid"
        assert item.details.modelCalls[0].usage.totalTokens == 15
        assert item.details.modelCalls[1].usage.totalTokens is None and item.details.usage.totalTokens is None
    finally:
        runner.close(wait_seconds=1)


def test_budget_refusal_before_provider_attempt_does_not_fabricate_model_calls():
    from app.testing import FakeModel
    model = FakeModel(); collector = AttemptCollector(ID_A)
    runner = ModelGateway(adapter_factory=lambda: InjectedAdapter(model))
    def deny(_ordinal, _deadline):
        raise ModelFailure("model_busy")
    try:
        with attempt_context(collector), pytest.raises(ModelFailure):
            runner.invoke([], deadline=time.monotonic() + 2, before_attempt=deny)
        assert finish(collector).details.modelCalls == () and model.calls == []
    finally:
        runner.close(wait_seconds=1)


def test_broken_metadata_hook_never_turns_a_legal_answer_into_a_game_failure():
    from app.testing import FakeModel
    class BrokenObserver(AttemptCollector):
        def observe_model(self, _call):
            raise ValueError("synthetic private exception text")
    collector = BrokenObserver(ID_A); runner = ModelGateway(adapter_factory=lambda: InjectedAdapter(FakeModel("是")))
    try:
        with attempt_context(collector):
            assert runner.invoke([], deadline=time.monotonic() + 2).answer == "是"
        item = finish(collector)
        assert item.details.metadataTruncated is True
        assert "synthetic private exception" not in item.model_dump_json()
    finally:
        runner.close(wait_seconds=1)


def test_timeout_seals_started_call_and_late_usage_cannot_mutate_it_or_next_request():
    entered, release = Event(), Event()
    class SlowModel:
        def invoke(self, _messages):
            entered.set(); assert release.wait(2)
            return AIMessage(content=CONTENT, usage_metadata={"input_tokens": 12, "output_tokens": 3, "total_tokens": 15})
    collector = AttemptCollector(ID_A); next_collector = AttemptCollector(ID_B)
    runner = ModelGateway(adapter_factory=lambda: InjectedAdapter(SlowModel()))
    try:
        with attempt_context(collector), pytest.raises(ModelFailure) as caught:
            runner.invoke([], deadline=time.monotonic() + 0.1)
        assert caught.value.code == "model_timeout" and entered.is_set()
        old = finish(collector, status_code=None, response_started=False, disconnected=True)
        assert len(old.details.modelCalls) == 1 and old.details.modelCalls[0].status == "started"
        before = old.model_dump_json()
        with attempt_context(next_collector):
            release.set(); assert runner.close(wait_seconds=1)["active"] == 0
        assert old.model_dump_json() == before and finish(next_collector).details.modelCalls == ()
    finally:
        release.set(); runner.close(wait_seconds=1)
