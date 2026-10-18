"""Verify adapter configuration and cancellation using HTTPX MockTransport."""
import json
import threading
import time

import httpx
import pytest

from app.config import Settings


@pytest.mark.parametrize("provider", ["unknown", "qwen", "siliconflow", "zhipu"])
def test_unverified_remote_or_unknown_provider_refuses_before_client_creation(tmp_path, monkeypatch, provider):
    from app.model_gateway import CompatibleAdapter, ModelFailure
    created = []
    monkeypatch.setattr(httpx, "Client", lambda **kwargs: created.append(kwargs))
    with pytest.raises(ModelFailure) as error:
        CompatibleAdapter(Settings.for_test(tmp_path, LLM_PROVIDER=provider, ALLOW_REAL_MODEL=True))
    assert error.value.code == "model_policy_unknown"
    assert created == []


def test_verified_policy_is_bound_to_exact_model_and_endpoint(tmp_path):
    from app.model_gateway import CompatibleAdapter, ModelFailure
    settings = Settings.for_test(tmp_path, LLM_PROVIDER="siliconflow", ALLOW_REAL_MODEL=True,
        MODEL_FREE_VERIFIED=True, FREE_MODEL_PROVIDER="siliconflow", FREE_MODEL_NAME="different-model",
        FREE_MODEL_BASE_URL="https://api.siliconflow.cn/v1", SILICONFLOW_API_KEY="synthetic-key")
    with pytest.raises(ModelFailure) as error:
        CompatibleAdapter(settings)
    assert error.value.code == "model_policy_unknown"


def test_dedicated_local_adapter_has_no_hidden_retries_and_closes_its_client(tmp_path):
    from app.model_gateway import CompatibleAdapter
    requests = []
    def respond(request):
        requests.append(request)
        return httpx.Response(200, json={"choices": [{"message": {"content": '{"answer":"是","reasoning":"fixture"}'}}]})
    adapter = CompatibleAdapter(Settings.for_test(tmp_path, LLM_PROVIDER="ollama", ALLOW_REAL_MODEL=True),
                                transport=httpx.MockTransport(respond))
    try:
        answer = adapter.invoke([{"role": "user", "content": "synthetic?"}],
                                deadline=time.monotonic() + 1, cancelled=threading.Event())
        assert '"answer":"是"' in answer
        assert len(requests) == 1
        assert requests[0].url.path == "/v1/chat/completions"
        assert json.loads(requests[0].content)["response_format"] == {"type": "json_object"}
        assert all(0 < timeout <= 1 for timeout in requests[0].extensions["timeout"].values())
    finally:
        adapter.close()
    assert adapter.closed is True


@pytest.mark.parametrize("status,code", [(401, "model_auth"), (403, "model_auth"), (429, "model_quota"), (503, "model_transport_error")])
def test_transport_errors_are_classified_without_provider_body(tmp_path, status, code):
    from app.model_gateway import CompatibleAdapter, ModelFailure
    transport = httpx.MockTransport(lambda _: httpx.Response(status, text="synthetic-secret-key private-bottom"))
    adapter = CompatibleAdapter(Settings.for_test(tmp_path, LLM_PROVIDER="ollama", ALLOW_REAL_MODEL=True), transport=transport)
    try:
        with pytest.raises(ModelFailure) as error:
            adapter.invoke([], deadline=time.monotonic() + 1, cancelled=threading.Event())
        assert error.value.code == code
        assert "secret-key" not in str(error.value)
        assert "private-bottom" not in str(error.value)
    finally:
        adapter.close()


def test_cooperative_cancellation_never_starts_a_new_http_request(tmp_path):
    from app.model_gateway import CompatibleAdapter, ModelFailure
    calls = []
    transport = httpx.MockTransport(lambda request: calls.append(request))
    adapter = CompatibleAdapter(Settings.for_test(tmp_path, LLM_PROVIDER="ollama", ALLOW_REAL_MODEL=True), transport=transport)
    adapter.request_cancel()
    try:
        with pytest.raises(ModelFailure) as error:
            adapter.invoke([], deadline=time.monotonic() + 1, cancelled=threading.Event())
        assert error.value.code == "model_cancelled"
        assert calls == []
    finally:
        adapter.close()
