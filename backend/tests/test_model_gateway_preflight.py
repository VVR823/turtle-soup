"""Public gateway preflight gates; no real provider or runtime data is used."""
from contextlib import contextmanager
from threading import Event
import time
from types import SimpleNamespace

import httpx
import pytest

from app.config import Settings
from app.model_gateway import CompatibleAdapter, InjectedAdapter, ModelFailure, ModelGateway
from .test_model_gateway import ScriptedTransport


@contextmanager
def owned_gateway(factory, **options):
    runner = ModelGateway(adapter_factory=factory, **options)
    try:
        yield runner
    finally:
        assert runner.close(wait_seconds=1)["active"] == 0


@pytest.mark.parametrize("limit", [0, 3, -1, True, 1.0, "1", None])
def test_invalid_capacity_cannot_allocate_a_gateway_or_transport(limit):
    calls = []
    with pytest.raises(ValueError, match="Local call limit"):
        ModelGateway(adapter_factory=lambda: calls.append("factory"), max_active=limit)
    assert calls == []


@pytest.mark.parametrize("attempts", [0, 3, -1, True, 1.0, "1", None])
def test_invalid_attempt_budget_is_rejected_before_admission(attempts):
    calls = []
    with owned_gateway(lambda: calls.append("factory"), clock=lambda: 0) as runner:
        with pytest.raises(ValueError, match="Attempt budget"):
            runner.invoke([], deadline=10, max_attempts=attempts)
        assert runner.snapshot()["active"] == 0
        assert calls == []


@pytest.mark.parametrize("deadline", [0, -1])
def test_already_exhausted_deadline_never_claims_a_slot_or_opens_transport(deadline):
    calls = []
    with owned_gateway(lambda: calls.append("factory"), clock=lambda: 0) as runner:
        with pytest.raises(ModelFailure) as error:
            runner.invoke([], deadline=deadline)
        assert error.value.code == "model_timeout"
        assert runner.snapshot()["active"] == 0
        assert calls == []


def test_already_cancelled_request_never_claims_capacity_or_opens_transport():
    cancelled = Event(); cancelled.set()
    calls = []
    with owned_gateway(lambda: calls.append("factory"), clock=lambda: 0) as runner:
        with pytest.raises(ModelFailure) as error:
            runner.invoke([], deadline=10, cancelled=cancelled)
        assert error.value.code == "model_cancelled"
        assert runner.snapshot()["active"] == 0
        assert calls == []


@pytest.mark.parametrize("gate", ["deadline", "cancel", "budget"])
def test_durable_attempt_gate_refusal_never_dispatches_a_provider_attempt(gate):
    now = [0.0]; cancelled = Event(); attempts = []
    transport = ScriptedTransport(['{"answer":"是","reasoning":"synthetic"}'])

    def before_attempt(ordinal, deadline):
        attempts.append((ordinal, deadline))
        if gate == "deadline": now[0] = deadline
        elif gate == "cancel": cancelled.set()
        else: raise ModelFailure("model_quota")

    with owned_gateway(lambda: transport, clock=lambda: now[0]) as runner:
        with pytest.raises(ModelFailure) as error:
            runner.invoke([], deadline=10, cancelled=cancelled, before_attempt=before_attempt)
        assert error.value.code == {"deadline": "model_timeout", "cancel": "model_cancelled", "budget": "model_quota"}[gate]
    assert attempts == [(1, 10)]
    assert transport.calls == []
    assert transport.closed == 1


def test_factory_failure_releases_capacity_without_exposing_raw_exception_details():
    calls = []

    def factory():
        calls.append("factory")
        raise RuntimeError("SYNTHETIC_PRIVATE_PROVIDER_DETAIL")

    with owned_gateway(factory) as runner:
        with pytest.raises(ModelFailure) as error:
            runner.invoke([], deadline=time.monotonic() + 2)
        assert error.value.code == "model_unavailable"
        assert "PRIVATE" not in str(error.value)
    assert calls == ["factory"]


@pytest.mark.parametrize("source", ["adapter", "caller"])
def test_injected_adapter_honors_both_cancellation_sources_before_model_invoke(source):
    calls = []
    adapter = InjectedAdapter(SimpleNamespace(invoke=lambda messages: calls.append(messages)))
    cancelled = Event()
    if source == "adapter": adapter.request_cancel()
    else: cancelled.set()
    try:
        with pytest.raises(ModelFailure) as error:
            adapter.invoke([], deadline=time.monotonic() + 1, cancelled=cancelled)
        assert error.value.code == "model_cancelled"
        assert calls == []
    finally:
        adapter.close()


def test_negative_shutdown_wait_is_rejected_without_closing_the_available_gateway():
    with owned_gateway(lambda: pytest.fail("No model dispatch expected")) as runner:
        with pytest.raises(ValueError, match="nonnegative"):
            runner.close(wait_seconds=-1)
        assert runner.snapshot()["closed"] is False
        assert runner.snapshot()["active"] == 0


def forbid_http_client(monkeypatch):
    def forbidden(**options):
        pytest.fail("A refused policy/credential must not allocate an HTTP client")
    monkeypatch.setattr(httpx, "Client", forbidden)


def test_disabled_real_model_policy_refuses_before_http_client_creation(tmp_path, monkeypatch):
    forbid_http_client(monkeypatch)
    with pytest.raises(ModelFailure) as error:
        CompatibleAdapter(Settings.for_test(tmp_path))
    assert error.value.code == "model_policy_unknown"


@pytest.mark.parametrize("provider,missing", [("ollama", "model"), ("qwen", "model"), ("qwen", "key"),
    ("siliconflow", "model"), ("siliconflow", "key"), ("zhipu", "model"), ("zhipu", "key")])
def test_missing_model_or_key_refuses_before_client_creation(tmp_path, monkeypatch, provider, missing):
    forbid_http_client(monkeypatch)
    prefix = provider.upper()
    model = "" if missing == "model" else "synthetic-model"
    endpoint = "http://localhost:11434/v1" if provider == "ollama" else f"https://{provider}.invalid/v1"
    options = {"LLM_PROVIDER": provider, "ALLOW_REAL_MODEL": True,
               prefix + "_MODEL": model, prefix + "_BASE_URL": endpoint}
    if provider != "ollama":
        # Synthetic policy preconditions only, never genuine free qualification.
        options.update(MODEL_FREE_VERIFIED=True, FREE_MODEL_PROVIDER=provider,
                       FREE_MODEL_NAME=model, FREE_MODEL_BASE_URL=endpoint)
        options[prefix + "_API_KEY"] = "" if missing == "key" else "synthetic-key"
    with pytest.raises(ModelFailure) as error:
        CompatibleAdapter(Settings.for_test(tmp_path, **options))
    assert error.value.code == "model_auth"


def test_remote_http_refuses_even_if_all_synthetic_policy_bindings_match(tmp_path, monkeypatch):
    forbid_http_client(monkeypatch)
    with pytest.raises(ModelFailure) as error:
        CompatibleAdapter(Settings.for_test(tmp_path, LLM_PROVIDER="qwen", ALLOW_REAL_MODEL=True,
            QWEN_MODEL="synthetic-model", QWEN_API_KEY="synthetic-key", QWEN_BASE_URL="http://qwen.invalid/v1",
            MODEL_FREE_VERIFIED=True, FREE_MODEL_PROVIDER="qwen", FREE_MODEL_NAME="synthetic-model",
            FREE_MODEL_BASE_URL="http://qwen.invalid/v1"))
    assert error.value.code == "model_policy_unknown"
