"""Trace labels derive from the host contract, not decoration in the reply."""
import json
from dataclasses import replace

import pytest

from app import trace_logger
from app.schemas import HostResult
from app.audit_context import AttemptCollector, attempt_context


@pytest.mark.parametrize("result,category", [
    (HostResult(kind="answer", answer="是", chargeable=True, source="llm", reply="🤖 display only"), "LLM兜底"),
    (HostResult(kind="reminder", chargeable=False, source="flow", reply="plain reminder"), "非是否类/提醒"),
    (HostResult(kind="system_error", chargeable=False, source="llm", errorCode="model_timeout", reply="plain error"), "模型异常"),
])
def test_trace_retains_explicit_kind_source_charge_and_safe_error(runtime, result, category):
    runtime.settings = replace(runtime.settings, ENABLE_TRACE=True)
    trace_logger.record("synthetic", "synthetic-soup", "synthetic question?", result)
    paths = list((runtime.settings.DATA_DIR / "traces").glob("*.jsonl"))
    assert len(paths) == 1
    row = json.loads(paths[0].read_text(encoding="utf-8"))
    assert row["kind"] == result.kind
    assert row["source"] == result.source
    assert row["chargeable"] == result.chargeable
    assert row["errorCode"] == result.errorCode
    assert row["category"] == category
    assert row["versions"]["engineVersion"] == result.versions.engineVersion
    assert "reasoning" not in row


def test_enabled_trace_failure_is_visible_without_secret_stderr_or_player_failure(runtime, monkeypatch, capsys):
    runtime.settings = replace(runtime.settings, ENABLE_TRACE=True)
    def denied(*args, **kwargs):
        raise OSError("SECRET question reply credential path")
    monkeypatch.setattr(trace_logger, "open", denied, raising=False)
    collector = AttemptCollector("7194c176-b282-48c1-b82a-ccaf930eebc2")
    host = HostResult(kind="reminder", chargeable=False, source="flow", reply="PRIVATE REPLY")
    with attempt_context(collector):
        trace_logger.record("private-session", "synthetic", "PRIVATE QUESTION", host)
    output = capsys.readouterr().err
    assert "diagnostic_trace_failed" in output
    assert not any(value in output for value in ("SECRET", "private-session", "PRIVATE", "credential", "path"))
    item = collector.finish(status_code=200, method="POST", route_template="/api/chat",
        response_started=True, disconnected=False)
    assert item.details.metadataTruncated and item.details.statusCode == 200
