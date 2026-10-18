"""Call ownership/deadline tests use scripted transports, never cloud models."""
import threading
import time
from concurrent.futures import ThreadPoolExecutor

import pytest


class ScriptedTransport:
    def __init__(self, values, *, before_return=None, broken_close=False):
        self.values = iter(values)
        self.before_return = before_return
        self.broken_close = broken_close
        self.calls = []
        self.closed = 0
        self.cancel_requested = threading.Event()

    def invoke(self, messages, *, deadline, cancelled):
        self.calls.append(deadline)
        value = next(self.values)
        if self.before_return:
            self.before_return()
        if isinstance(value, BaseException):
            raise value
        return value

    def request_cancel(self):
        self.cancel_requested.set()

    def close(self):
        self.closed += 1
        if self.broken_close:
            raise RuntimeError("synthetic-private-provider-key must not leak")


def gateway(transport, **options):
    from app.model_gateway import ModelGateway
    return ModelGateway(adapter_factory=lambda: transport, **options)


def test_valid_json_is_explicitly_validated_and_owner_cleaned():
    transport = ScriptedTransport(['{"answer":"是","reasoning":"synthetic"}'])
    runner = gateway(transport)
    result = runner.invoke([], deadline=time.monotonic() + 1)
    assert result.answer == "是"
    assert transport.closed == 1
    assert runner.snapshot()["active"] == 0
    assert runner.close(wait_seconds=0.1)["active"] == 0


@pytest.mark.parametrize("answer", ["是", "不是", "是也不是", "算是", "与此无关"])
def test_exact_canonical_plain_answer_is_accepted(answer):
    transport = ScriptedTransport([f" \n{answer}\r\n"])
    runner = gateway(transport)
    result = runner.invoke([], deadline=time.monotonic() + 1)
    assert result.answer == answer
    assert result.reasoning == ""
    assert len(transport.calls) == 1
    assert transport.closed == 1
    runner.close(wait_seconds=0.1)


def test_answer_only_json_is_accepted_with_empty_internal_reasoning():
    transport = ScriptedTransport(['{"answer":"是"}'])
    runner = gateway(transport)
    result = runner.invoke([], deadline=time.monotonic() + 1)
    assert result.answer == "是" and result.reasoning == ""
    assert len(transport.calls) == 1
    runner.close(wait_seconds=0.1)


@pytest.mark.parametrize("output", [
    "不知道", "答案：不是", "不是。", '{"answer":"不知道","reasoning":"fixture"}',
    '{"answer":"是","answer":"不是","reasoning":"fixture"}',
    '{"answer":"是","reasoning":"fixture","chargeable":true}',
    '{"answer":true,"reasoning":"fixture"}',
])
def test_malformed_output_never_becomes_an_answer(output):
    from app.model_gateway import ModelFailure
    transport = ScriptedTransport([output, output])
    runner = gateway(transport)
    with pytest.raises(ModelFailure) as error:
        runner.invoke([], deadline=time.monotonic() + 1)
    assert error.value.code == "model_output_invalid"
    assert len(transport.calls) == 2
    assert transport.closed == 1
    runner.close(wait_seconds=0.1)


def test_explicit_retry_keeps_the_original_deadline():
    from app.model_gateway import ModelFailure
    transport = ScriptedTransport([
        ModelFailure("model_transport_error", retryable=True), '{"answer":"不是","reasoning":"fixture"}',
    ])
    runner = gateway(transport)
    deadline = time.monotonic() + 1
    assert runner.invoke([], deadline=deadline).answer == "不是"
    assert transport.calls == [deadline, deadline]
    runner.close(wait_seconds=0.1)


@pytest.mark.parametrize("code", ["model_quota", "model_auth", "model_policy_unknown"])
def test_non_transient_failures_do_not_retry_or_expose_provider_details(code):
    from app.model_gateway import ModelFailure
    transport = ScriptedTransport([ModelFailure(code)])
    runner = gateway(transport)
    with pytest.raises(ModelFailure) as error:
        runner.invoke([], deadline=time.monotonic() + 1)
    assert error.value.code == code
    assert len(transport.calls) == 1
    assert transport.closed == 1
    runner.close(wait_seconds=0.1)


def test_deadline_exhausted_before_retry_has_no_new_attempt():
    from app.model_gateway import ModelFailure
    release = threading.Event()
    transport = ScriptedTransport([ModelFailure("model_transport_error", retryable=True)],
                                  before_return=lambda: release.wait(1))
    runner = gateway(transport)
    try:
        with pytest.raises(ModelFailure) as error:
            runner.invoke([], deadline=time.monotonic() + 0.05)
        assert error.value.code == "model_timeout"
        assert transport.cancel_requested.is_set()
    finally:
        release.set()
        runner.close(wait_seconds=1)
    assert len(transport.calls) == 1


def test_timed_out_running_owners_keep_slots_and_late_results_are_discarded():
    from app.model_gateway import ModelFailure, ModelGateway
    entered = [threading.Event(), threading.Event()]
    release = threading.Event()
    transports = [ScriptedTransport(['{"answer":"是","reasoning":"fixture"}'],
                                   before_return=lambda e=e: (e.set(), release.wait(2))) for e in entered]
    created = iter(transports)
    runner = ModelGateway(adapter_factory=lambda: next(created), max_active=2)
    def ask():
        try:
            runner.invoke([], deadline=time.monotonic() + 0.15)
        except ModelFailure as error:
            return error.code
        pytest.fail("Timed-out late answer must not be returned")
    try:
        with ThreadPoolExecutor(max_workers=2) as pool:
            calls = [pool.submit(ask) for _ in range(2)]
            assert all(event.wait(1) for event in entered)
            assert [call.result(timeout=1) for call in calls] == ["model_timeout", "model_timeout"]
        assert runner.snapshot()["active"] == 2
        assert runner.snapshot()["timed_out_but_running"] == 2
        assert all(transport.cancel_requested.is_set() for transport in transports)
        with pytest.raises(ModelFailure) as error:
            runner.invoke([], deadline=time.monotonic() + 0.1)
        assert error.value.code == "model_busy"
        assert sum(len(t.calls) for t in transports) == 2
    finally:
        release.set()
        closed = runner.close(wait_seconds=1)
    assert closed["active"] == 0
    assert [t.closed for t in transports] == [1, 1]


def test_cleanup_failure_is_safe_and_conservatively_retains_owner_slot():
    from app.model_gateway import ModelFailure
    transport = ScriptedTransport(['{"answer":"是","reasoning":"fixture"}'], broken_close=True)
    runner = gateway(transport, max_active=1)
    with pytest.raises(ModelFailure) as error:
        runner.invoke([], deadline=time.monotonic() + 1)
    assert error.value.code == "model_cleanup_failed"
    assert "private-provider" not in str(error.value)
    assert runner.snapshot()["active"] == 1
    assert runner.snapshot()["cleanup_failed"] == 1
    with pytest.raises(ModelFailure) as error:
        runner.invoke([], deadline=time.monotonic() + 0.1)
    assert error.value.code == "model_busy"
    assert runner.close(wait_seconds=0.01)["cleanup_failed"] == 1


def test_shutdown_requests_cancellation_and_does_not_claim_blocked_owner_exited():
    from app.model_gateway import ModelFailure
    entered, release = threading.Event(), threading.Event()
    transport = ScriptedTransport(['{"answer":"是","reasoning":"fixture"}'],
                                  before_return=lambda: (entered.set(), release.wait(2)))
    runner = gateway(transport)
    with ThreadPoolExecutor(max_workers=1) as pool:
        call = pool.submit(runner.invoke, [], deadline=time.monotonic() + 1)
        try:
            assert entered.wait(1)
            started = time.monotonic()
            state = runner.close(wait_seconds=0.02)
            assert time.monotonic() - started < 0.5
            assert state["active"] == 1 and state["closed"] is True
            assert transport.cancel_requested.is_set()
        finally:
            release.set()
        with pytest.raises(ModelFailure):
            call.result(timeout=1)
    assert runner.close(wait_seconds=1)["active"] == 0
