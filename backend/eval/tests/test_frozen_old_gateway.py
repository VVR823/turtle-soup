"""The raw contract is an offline fake baseline, never an online relaxation."""
import time
import pytest
import httpx
from app.config import Settings
from app.model_gateway import CompatibleAdapter, InjectedAdapter, ModelFailure, ModelGateway
from app.testing import FakeModel
from .support import ScriptedFakeModel


def test_legacy_raw_refuses_nonfake_injection_before_dispatch():
    from langchain_core.messages import AIMessage
    class NonFake:
        calls = 0
        def invoke(self, messages):
            self.calls += 1
            return AIMessage(content='{"reasoning":"synthetic","answer":"是"}')
    model = NonFake()
    gateway = ModelGateway(adapter_factory=lambda: InjectedAdapter(model),max_active=1)
    try:
        with pytest.raises(ModelFailure,match="model_policy_unknown"):
            gateway.invoke([{"role":"user","content":"synthetic"}],deadline=time.monotonic()+3,
                max_attempts=1,response_contract="legacy_raw")
        assert model.calls == 0
    finally:
        assert gateway.close()["active"] == 0


def test_legacy_raw_fake_keeps_text_for_the_actual_old_parser():
    # A new strict decode would conceal the old parser/normalization defects.
    model = ScriptedFakeModel(("not-json-synthetic",))
    gateway = ModelGateway(adapter_factory=lambda: InjectedAdapter(model), max_active=1)
    try:
        result = gateway.invoke([{"role":"user","content":"synthetic"}], deadline=time.monotonic()+3,
            max_attempts=1, response_contract="legacy_raw")
        assert result == "not-json-synthetic" and len(model.calls) == 1
    finally:
        assert gateway.close()["active"] == 0


def test_default_gateway_remains_strict_for_the_same_text():
    model = ScriptedFakeModel(("not-json-synthetic",))
    gateway = ModelGateway(adapter_factory=lambda: InjectedAdapter(model), max_active=1)
    try:
        with pytest.raises(ModelFailure, match="model_output_invalid"):
            gateway.invoke([{"role":"user","content":"synthetic"}],deadline=time.monotonic()+3,max_attempts=1)
        assert len(model.calls) == 1
    finally:
        assert gateway.close()["active"] == 0


def test_legacy_raw_refuses_compatible_adapter_before_transport(tmp_path):
    requests = []
    transport = httpx.MockTransport(lambda request: requests.append(request) or httpx.Response(200,json={}))
    settings = Settings.for_test(tmp_path, ALLOW_REAL_MODEL=True, LLM_PROVIDER="ollama")
    gateway = ModelGateway(adapter_factory=lambda: CompatibleAdapter(settings,transport=transport),max_active=1)
    try:
        with pytest.raises(ModelFailure,match="model_policy_unknown"):
            gateway.invoke([{"role":"user","content":"synthetic"}],deadline=time.monotonic()+3,
                max_attempts=1,response_contract="legacy_raw")
        assert not requests
    finally:
        assert gateway.close()["active"] == 0


@pytest.mark.parametrize("output", ["X"*16001, None, 123], ids=["oversize", "null", "number"])
def test_legacy_raw_rejects_unbounded_or_nonstrings(output):
    class BadFake(FakeModel):
        def _respond(self, messages):
            return output
    gateway = ModelGateway(adapter_factory=lambda: InjectedAdapter(BadFake()),max_active=1)
    try:
        with pytest.raises(ModelFailure,match="model_output_invalid"):
            gateway.invoke([{"role":"user","content":"synthetic"}],deadline=time.monotonic()+3,
                max_attempts=1,response_contract="legacy_raw")
    finally:
        assert gateway.close()["active"] == 0
