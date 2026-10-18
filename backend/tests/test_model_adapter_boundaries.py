"""Offline HTTP-boundary guards; synthetic endpoints are never contacted."""
from contextlib import closing
import threading
import time

import httpx
import pytest

from app.config import Settings
from app.model_gateway import CompatibleAdapter, ModelFailure


@pytest.mark.parametrize("url", [
    "http://synthetic:secret@localhost/v1",
    "http://localhost/v1?token=synthetic",
    "http://localhost/v1#synthetic",
    "ftp://localhost/v1",
    "http://outside.invalid/v1",
], ids=["userinfo", "query", "fragment", "scheme", "remote-host"])
def test_unsafe_local_endpoint_is_rejected_before_http_client_exists(tmp_path, monkeypatch, url):
    def forbidden_client(**kwargs):
        pytest.fail("Rejected policy must not allocate any HTTP transport")
    monkeypatch.setattr(httpx, "Client", forbidden_client)
    settings = Settings.for_test(tmp_path, LLM_PROVIDER="ollama", ALLOW_REAL_MODEL=True, OLLAMA_BASE_URL=url)
    with pytest.raises(ModelFailure) as error:
        CompatibleAdapter(settings)
    assert error.value.code == "model_policy_unknown"


@pytest.mark.parametrize("status", [302, 404])
def test_redirect_or_unavailable_response_never_follows_or_exposes_body(tmp_path, status):
    calls = []
    def respond(request):
        calls.append(request)
        return httpx.Response(status, text="synthetic-private-body",
                              headers={"Location": "https://outside.invalid/private"})
    settings = Settings.for_test(tmp_path, LLM_PROVIDER="ollama", ALLOW_REAL_MODEL=True)
    with closing(CompatibleAdapter(settings, transport=httpx.MockTransport(respond))) as adapter:
        with pytest.raises(ModelFailure) as error:
            adapter.invoke([], deadline=time.monotonic() + 5, cancelled=threading.Event())
        assert error.value.code == "model_unavailable"
        assert error.value.retryable is False
        assert "synthetic-private-body" not in str(error.value)
        assert len(calls) == 1
    assert adapter.closed


@pytest.mark.parametrize("content", [None, [{"type": "text", "text": "synthetic-private-body"}]],
                         ids=["null-content", "structured-content"])
def test_non_text_success_is_invalid_output_not_an_answer(tmp_path, content):
    calls = []
    def respond(request):
        calls.append(request)
        return httpx.Response(200, json={"choices": [{"message": {"content": content}}]})
    settings = Settings.for_test(tmp_path, LLM_PROVIDER="ollama", ALLOW_REAL_MODEL=True)
    with closing(CompatibleAdapter(settings, transport=httpx.MockTransport(respond))) as adapter:
        with pytest.raises(ModelFailure) as error:
            adapter.invoke([], deadline=time.monotonic() + 5, cancelled=threading.Event())
        assert error.value.code == "model_output_invalid"
        assert error.value.retryable is True
        assert len(calls) == 1
        assert "synthetic-private-body" not in str(error.value)
    assert adapter.closed


def test_cancelled_during_http_response_discards_late_content(tmp_path):
    cancelled, calls = threading.Event(), []
    def respond(request):
        calls.append(request)
        cancelled.set()
        return httpx.Response(200, json={"choices": [{"message": {"content": "synthetic-late-answer"}}]})
    settings = Settings.for_test(tmp_path, LLM_PROVIDER="ollama", ALLOW_REAL_MODEL=True)
    with closing(CompatibleAdapter(settings, transport=httpx.MockTransport(respond))) as adapter:
        with pytest.raises(ModelFailure) as error:
            adapter.invoke([], deadline=time.monotonic() + 5, cancelled=cancelled)
        assert error.value.code == "model_cancelled"
        assert len(calls) == 1
    assert adapter.closed


def test_expired_deadline_never_dispatches_http_request(tmp_path):
    def forbidden_request(request):
        pytest.fail("An expired call must never dispatch HTTP")
    settings = Settings.for_test(tmp_path, LLM_PROVIDER="ollama", ALLOW_REAL_MODEL=True)
    with closing(CompatibleAdapter(settings, transport=httpx.MockTransport(forbidden_request))) as adapter:
        with pytest.raises(ModelFailure) as error:
            adapter.invoke([], deadline=time.monotonic() - 1, cancelled=threading.Event())
        assert error.value.code == "model_timeout"
    assert adapter.closed
