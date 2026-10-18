"""Actual host/gateway integration using only explicit owned fake transports."""
import time

import pytest
from langchain_core.messages import AIMessage

from app.config import Settings
from app.model_gateway import ModelFailure
from app.schemas import HostVersions
from app.testing import FakeModel
from .support import ScriptedFakeModel, answer_json, small_snapshot
from .test_run_contracts import system


def request(catalog, *, name="pure_llm", question="Is the boat present?", attempts=2, timeout=45.0, history=()):
    from eval.run_contracts import EvaluationInput
    spec = system().model_copy(update={"name": name, "budget": system().budget.model_copy(update={
        "modelAttemptsPerCase": attempts, "caseTimeoutSeconds": timeout})})
    return EvaluationInput(caseId="00000000-0000-0000-0000-000000000001", soupId=catalog[0].soupId,
        puzzleVersion=catalog[0].puzzleVersion, puzzle=catalog[0], question=question, history=history, system=spec)


def invoke(catalog, tmp_path, outputs, **options):
    from eval.drivers import PureLLMDriver
    model = ScriptedFakeModel(outputs)
    driver = PureLLMDriver(settings=Settings.for_test(tmp_path), fake_model=model)
    input = request(catalog, **options)
    try:
        result = driver.decide(input, deadline=time.monotonic() + input.system.budget.caseTimeoutSeconds)
    finally:
        assert driver.close()
    return result, model


def test_pure_driver_calls_real_json_gateway_and_binds_program_versions(catalog, tmp_path):
    result, model = invoke(catalog, tmp_path, (answer_json("不是"),))
    assert len(model.calls) == result.modelAttemptCount == 1
    assert result.host.answer == "不是" and result.host.source == "llm"
    assert result.host.versions.puzzleVersion == catalog[0].puzzleVersion
    assert result.host.versions.ruleVersion == catalog[0].ruleSnapshot.ruleVersion
    assert result.cleanupComplete and result.inputChars == sum(len(m["content"]) for m in model.calls[0])
    assert result.contextTurnsIncluded is None
    assert len(result.modelObservations) == 1 and result.modelObservations[0].usageStatus == "unknown"


@pytest.mark.parametrize("attempts", [1, 2])
def test_invalid_first_output_retries_only_with_actual_budget(catalog, tmp_path, attempts):
    result, model = invoke(catalog, tmp_path, ("是", answer_json()), attempts=attempts)
    assert len(model.calls) == result.modelAttemptCount == attempts
    assert result.host.kind == ("system_error" if attempts == 1 else "answer")
    if attempts == 1: assert result.host.errorCode == "model_output_invalid"
    assert [o.status for o in result.modelObservations] == (["failed"] if attempts == 1 else ["failed", "succeeded"])


@pytest.mark.parametrize("code", ["model_quota", "model_timeout", "model_auth"])
def test_nonretryable_failures_have_one_real_attempt(catalog, tmp_path, code):
    result, model = invoke(catalog, tmp_path, (ModelFailure(code), answer_json()))
    assert len(model.calls) == result.modelAttemptCount == 1 and result.host.errorCode == code
    assert result.modelObservations[0].errorCode == code and result.cleanupComplete


def test_retryable_transport_failure_counts_both_attempts(catalog, tmp_path):
    result, model = invoke(catalog, tmp_path, (ModelFailure("model_transport_error", retryable=True), answer_json()))
    assert result.host.kind == "answer" and result.modelAttemptCount == len(model.calls) == 2
    assert result.modelObservations[0].status == "failed" and result.modelObservations[1].status == "succeeded"


def test_known_usage_is_observed_not_fabricated(catalog, tmp_path):
    result, _ = invoke(catalog, tmp_path, (AIMessage(content=answer_json(),
        usage_metadata={"input_tokens": 10, "output_tokens": 3, "total_tokens": 13}),))
    observation = result.modelObservations[0]
    assert observation.usageStatus == "known" and observation.usage.totalTokens == 13


@pytest.mark.parametrize("driver_name", ["new_system", "pure_llm"])
def test_pure_bypasses_flow_and_new_keeps_reminder(catalog, tmp_path, driver_name):
    from eval.drivers import NewSystemDriver, PureLLMDriver
    model = FakeModel("不是")
    driver = (NewSystemDriver if driver_name == "new_system" else PureLLMDriver)(settings=Settings.for_test(tmp_path), fake_model=model)
    try:
        result = driver.decide(request(catalog, name=driver_name, question="给我一点提示"), deadline=time.monotonic() + 5)
    finally:
        assert driver.close()
    assert result.host.kind == ("reminder" if driver_name == "new_system" else "answer")
    assert result.modelAttemptCount == len(model.calls) == (0 if driver_name == "new_system" else 1)


def test_new_actual_rule_hit_is_zero_calls_and_not_llm_cache(catalog, tmp_path):
    from eval.drivers import NewSystemDriver
    from eval.runner import aggregate_usage
    model = FakeModel("不是")
    driver = NewSystemDriver(settings=Settings.for_test(tmp_path), fake_model=model)
    try:
        result = driver.decide(request(catalog, name="new_system", question="这是本格吗？"), deadline=time.monotonic() + 5)
    finally:
        assert driver.close()
    assert result.host.kind == "answer" and result.host.answer == "是" and result.host.source == "deterministic"
    assert result.modelAttemptCount == len(model.calls) == 0 and not result.modelObservations
    usage, status = aggregate_usage(result)
    assert status == "known" and usage.totalTokens == 0
    assert result.inputChars is None and result.contextTurnsIncluded is None


def test_actual_context_keeps_latest_twelve_complete_turns(catalog, tmp_path):
    from eval.run_contracts import HistoryTurn
    versions = HostVersions(puzzleVersion=catalog[0].puzzleVersion, ruleVersion=catalog[0].ruleSnapshot.ruleVersion)
    history = tuple(HistoryTurn(question=f"Is marker-{n:02d} present?", answer="不是", versions=versions) for n in range(14))
    result, model = invoke(catalog, tmp_path, (answer_json(),), history=history)
    prompt = model.calls[0][1]["content"]
    assert "marker-00" not in prompt and "marker-01" not in prompt
    assert all(f"marker-{n:02d}" in prompt for n in range(2, 14))
    assert result.inputChars <= 8000 and result.contextTurnsIncluded is None
    assert "主持人：不是" in prompt and len(history) == 14


@pytest.mark.parametrize("changes", [{"ALLOW_REAL_MODEL": True}, {"TESTING": False},
    {"LOAD_RUNTIME_PUZZLES": True}, {"LLM_PROVIDER": "ollama"}])
def test_real_or_implicit_settings_are_refused_before_transport(tmp_path, changes):
    from eval.contracts import DatasetError
    from eval.drivers import PureLLMDriver
    model = FakeModel()
    with pytest.raises(DatasetError): PureLLMDriver(settings=Settings.for_test(tmp_path, **changes), fake_model=model)
    assert model.calls == []


def test_unknown_model_cannot_construct_real_adapter(tmp_path):
    from eval.contracts import DatasetError
    from eval.drivers import PureLLMDriver
    with pytest.raises(DatasetError): PureLLMDriver(settings=Settings.for_test(tmp_path), fake_model=object())


def test_expired_driver_deadline_does_not_call_model(catalog, tmp_path):
    from eval.drivers import PureLLMDriver
    model = FakeModel(); driver = PureLLMDriver(settings=Settings.for_test(tmp_path), fake_model=model)
    try:
        result = driver.decide(request(catalog), deadline=time.monotonic() - 1)
    finally:
        assert driver.close()
    assert not result.decisionAttempted and result.errorCode == "budget_exhausted" and result.modelAttemptCount == 0
    assert not model.calls


def test_blocked_owned_worker_stops_following_cases_and_remains_in_denominator(reviewed, catalog, tmp_path):
    from eval.drivers import PureLLMDriver
    from eval.runner import run_dataset
    model = ScriptedFakeModel(("BLOCK", answer_json(), answer_json()))
    driver = PureLLMDriver(settings=Settings.for_test(tmp_path), fake_model=model)
    spec = request(catalog, timeout=0.02).system
    try:
        report = run_dataset(small_snapshot(reviewed, catalog, groups=1, standalone=False), system=spec,
            driver=driver, repeat_index=0, repeat_count=1)
        assert report.metrics.total == 3 and report.metrics.notAttemptedCount == 2 and not report.complete
        assert report.records[0].errorCode == "model_timeout" and report.records[0].modelAttemptCount == 1
        assert report.records[0].usageStatus == "unknown" and len(model.calls) == 1
        assert driver.gateway.snapshot()["active"] == 1
    finally:
        model.release.set()
        assert driver.close()


def test_unavailable_old_is_explicit_not_a_renamed_new_driver(catalog):
    from eval.drivers import UnavailableOldDriver
    driver = UnavailableOldDriver()
    result = driver.decide(request(catalog, name="frozen_old"), deadline=time.monotonic() + 5)
    assert result.errorCode == "driver_unavailable" and result.host is None and not result.decisionAttempted
    assert result.modelAttemptCount == 0 and driver.close()


def test_driver_declared_timeout_is_enforced_even_with_longer_caller_deadline(catalog, tmp_path):
    from eval.drivers import PureLLMDriver
    model = ScriptedFakeModel(("BLOCK",))
    driver = PureLLMDriver(settings=Settings.for_test(tmp_path), fake_model=model)
    try:
        begin = time.monotonic()
        result = driver.decide(request(catalog, timeout=0.02), deadline=begin + 10)
        elapsed = time.monotonic() - begin
        assert result.host.kind == "system_error" and result.host.errorCode == "model_timeout"
        assert elapsed < 1 and result.modelAttemptCount == 1 and not result.cleanupComplete
    finally:
        model.release.set()
        assert driver.close()


def test_budgeted_gateway_counts_reservation_before_cancel_without_observation():
    from eval.drivers import BudgetedGateway
    class ReservedThenCancel:
        def invoke(self, messages, *, before_attempt, **options):
            before_attempt(1, options["deadline"])
            raise ModelFailure("model_cancelled")
    wrapper = BudgetedGateway(ReservedThenCancel(), deadline=5.0, attempt_limit=1, collector=None, clock=lambda: 0.0)
    with pytest.raises(ModelFailure): wrapper.invoke([{"content": "synthetic"}], deadline=10.0)
    assert wrapper.attempt_count == 1 and wrapper.input_chars == 9


def test_missing_one_attempt_usage_does_not_sum_known_attempt_as_full_usage(catalog, tmp_path):
    from eval.runner import aggregate_usage
    known = AIMessage(content=answer_json(), usage_metadata={"input_tokens": 10, "output_tokens": 3, "total_tokens": 13})
    outcome, _ = invoke(catalog, tmp_path, ("illegal", known))
    usage, status = aggregate_usage(outcome)
    assert outcome.modelAttemptCount == 2 and status == "unknown"
    assert usage.inputTokens is None and usage.outputTokens is None and usage.totalTokens is None


def test_usage_sum_over_signed_64_bit_is_invalid_instead_of_wrapping():
    from app.audit_events import ModelCallObservation, TokenUsage
    from eval.run_contracts import DriverOutcome
    from eval.runner import aggregate_usage
    value = 2 ** 62
    observations = tuple(ModelCallObservation(ordinal=index, status="succeeded", usageStatus="known",
        usage=TokenUsage(inputTokens=value, outputTokens=value, totalTokens=value)) for index in (1, 2))
    outcome = DriverOutcome(host=None, errorCode="driver_error", modelObservations=observations,
        modelAttemptCount=2, inputChars=None, contextTurnsIncluded=None, decisionAttempted=True, cleanupComplete=True)
    usage, status = aggregate_usage(outcome)
    assert status == "invalid"
    assert usage.inputTokens is usage.outputTokens is usage.totalTokens is None
