"""Permanent native reproductions of the sole TS13 static review findings."""
from contextlib import closing
import sqlite3
from dataclasses import replace
from uuid import uuid4

import pytest

from app import db
from app.runtime import Runtime, runtime_context
from app.schemas import Soup, HostResult, HostVersions
from .test_migrations import puzzle
from .test_agent_store import agent_storage
from .test_feedback_storage import storage, body
from .test_rule_snapshots import rule_storage
from .test_candidate_validation import scope, inspect


@pytest.mark.parametrize("checkpoints", [
    [{"key": "小明是凶手", "answer": True}, {"key": "小明是凶手", "answer": False}],
    [{"key": "小明是凶手", "answer": True}, {"key": "小明不是凶手", "answer": True}],
])
def test_i1_detectable_checkpoint_contradiction_requires_human_and_actual_sources(rule_storage, checkpoints):
    source = scope(Soup(id="synthetic", title="Test", surface="Surface", bottom="小明是凶手。", checkpoints=checkpoints))
    result = inspect(source, operation="add", targetRuleDigest=None)
    assert result.status == "needs_human" and result.reason == "existing_conflict"
    expected = {f.id for f in source[0].factScope if f.sourcePath in {"checkpoints[0]", "checkpoints[1]"}}
    assert set(result.conflictingFactIds) == expected and result.answerSupported is None


@pytest.mark.parametrize("existing_directory", [False, True])
def test_i2_missing_database_refusal_never_creates_storage_or_breaks_later_init(runtime, tmp_path, existing_directory):
    from app.agents.store import AgentStore
    from app.agents.contracts import AgentError
    path = tmp_path / "owned-agent-new" / "data"
    if existing_directory: path.mkdir(parents=True)
    active = Runtime(replace(runtime.settings, DATA_DIR=path), model=runtime.model, soups=[puzzle()])
    with pytest.raises(AgentError): AgentStore(active, authorize_create=lambda context: True).read(str(uuid4()))
    assert not (path / "sessions.db").exists()
    assert path.exists() is existing_directory
    with runtime_context(active):
        db.initialize()
        conn = db._connect()
        try:
            assert conn.execute("SELECT max(version) FROM schema_migrations").fetchone()[0] == 2
        finally: conn.close()


def test_i2_invalid_existing_database_refusal_does_not_change_journal_or_bytes(runtime, tmp_path):
    from app.agents.store import AgentStore
    from app.agents.contracts import AgentError
    path = tmp_path / "owned-invalid-agent"; path.mkdir()
    database = path / "sessions.db"
    with closing(sqlite3.connect(database)) as conn, conn:
        conn.execute("CREATE TABLE unrelated(value TEXT)")
    before = database.read_bytes()
    active = Runtime(replace(runtime.settings, DATA_DIR=path), model=runtime.model, soups=[puzzle()])
    with pytest.raises(AgentError): AgentStore(active, authorize_create=lambda context: True).read(str(uuid4()))
    assert database.read_bytes() == before
    with closing(sqlite3.connect(database)) as conn, conn:
        assert conn.execute("PRAGMA journal_mode").fetchone()[0] == "delete"


@pytest.mark.parametrize("kind,source,error", [("answer", "llm", None), ("answer", "deterministic", None),
    ("system_error", "llm", "model_output_invalid")])
def test_i4_trace_freezes_actual_program_diagnostics_without_raw_reply(agent_storage, kind, source, error):
    from app import baselines
    from app.feedback_store import submit_feedback, review_feedback, set_model_permission
    from app.agents.store import AgentStore
    from app.agents.tool_contracts import trace_result
    from .test_feedback_privacy import permission
    from .test_task_context import TOOLS
    sid = db.create_game_once("synthetic", "xuermu", str(uuid4()))["sessionId"]
    turn = db.reserve_turn(sid, str(uuid4()), "是谁？")
    host = HostResult(kind=kind, answer="是" if kind == "answer" else None, source=source,
        chargeable=kind == "answer", errorCode=error, reply="PRIVATE synthetic detail",
        versions=HostVersions(puzzleVersion=turn.puzzleVersion, ruleVersion=turn.ruleVersion))
    db.finish_turn(turn, host)
    item = submit_feedback(body(turnId=turn.turnId, hostAnswer=host.reply))
    item = review_feedback(item.id, 0, status="approved")
    item = set_model_permission(item.id, item.rowVersion, review=permission())
    store = AgentStore(agent_storage, authorize_create=lambda context: True)
    run = store.create(request_id=str(uuid4()), feedback_id=item.id, expected_feedback_version=item.rowVersion,
        allowed_tools=TOOLS, suite_manifest_digest=None)
    trace = trace_result(run.manifest.context)
    diagnostic = trace.programDiagnostic
    assert diagnostic.kind == kind and diagnostic.source == source and diagnostic.errorCode == error
    assert diagnostic.answer == ("是" if kind == "answer" else None)
    assert diagnostic.engineVersion == "host-v3" and diagnostic.normalizationVersion == "exact-v1"
    assert diagnostic.resultDigest == baselines.digest(host.model_dump(mode="json"))
    assert run.manifest.context.programDiagnostic == diagnostic and "PRIVATE" not in trace.model_dump_json()
    assert not hasattr(diagnostic, "reply") and not hasattr(diagnostic, "reasoning")


def test_i3_new_executor_cannot_sign_new_bytes_while_old_module_is_loaded(agent_storage, monkeypatch):
    from pathlib import Path
    from app.testing import FakeModel
    from app.agents.regression import FixedRegression
    from app.agents.contracts import AgentError
    assert FakeModel().answer == "与此无关"
    original = Path.read_bytes
    def changed(path):
        value = original(path)
        # Real implementation constant changes, not just a new caller object.
        return value.replace(b"Synthetic offline fixture, not evidence of model quality.",
            b"Changed compiled response fixture.") if path.name == "testing.py" else value
    monkeypatch.setattr(Path, "read_bytes", changed)
    with pytest.raises(AgentError) as caught: FixedRegression(agent_storage)
    assert caught.value.code == "agent_source_reload_required"
