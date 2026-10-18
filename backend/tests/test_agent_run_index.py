"""Bounded private navigation over actual isolated runs, never approval proof."""
from dataclasses import replace
from importlib import import_module
from uuid import uuid4
import base64
import sqlite3

import pytest

from app import baselines, db
from app.runtime import Runtime
from .test_agent_store import agent_storage, create
from .test_feedback_storage import storage, snapshot
from .test_rule_snapshots import rule_storage
from .test_candidate_review_store import proposal


def review(active):
    return import_module("app.candidate_review").CandidateReviewStore(active)


def runs(active, count, *, stamp=1000000.0):
    owner, item, first = create(active)
    conn = db._connect()
    try:
        row = conn.execute("SELECT * FROM agent_runs WHERE id=?", (first.id,)).fetchone()
        identities = [str(uuid4()) for _ in range(count)]
        # Real persisted queued schema/checkpoint/context; cloning is only a
        # navigation-volume fixture, not a fabricated report or terminal run.
        for identity in identities:
            conn.execute("INSERT INTO agent_runs(id,request_id,feedback_id,state,checkpoint_json,manifest_json,created_at,updated_at) "
                "VALUES(?,?,?,'queued',?,?,?,?)", (identity, str(uuid4()), item.id,
                    row["checkpoint_json"], row["manifest_json"], stamp, stamp))
        conn.commit()
    finally:
        conn.close()
    return item, identities


def test_index_has_minimal_closed_ordered_rows_and_readonly_snapshot(agent_storage, monkeypatch):
    _, ids = runs(agent_storage, 3)
    before = snapshot()
    owner = review(agent_storage)
    def forbidden(*args, **kwargs):
        raise AssertionError("Navigation allocated model, loaded full history or froze private context")
    monkeypatch.setattr(Runtime, "get_model_gateway", forbidden)
    monkeypatch.setattr(db, "initialize", forbidden)
    monkeypatch.setattr(owner.agent_store, "_raw_run", forbidden)
    monkeypatch.setattr(owner.agent_store, "_status", forbidden)
    monkeypatch.setattr("app.task_context._freeze", forbidden)
    result = owner.list_runs(start=999999.0, end=1000001.0)
    assert [row.id for row in result.runs] == sorted(ids, reverse=True)
    assert result.nextCursor is None and snapshot() == before
    assert set(result.model_dump()) == {"schemaVersion", "runs", "nextCursor"}
    for row in result.runs:
        assert set(row.model_dump()) == {"id", "feedbackId", "state", "rowVersion", "createdAt", "deadlineAt",
            "modelAttemptsUsed", "toolAttemptsUsed", "candidateId", "candidateStatus"}
        assert row.state == "queued" and row.rowVersion == 0 and row.createdAt == 1000000.0
        assert row.modelAttemptsUsed == row.toolAttemptsUsed == 0 and row.deadlineAt is None
        assert row.candidateId is None and row.candidateStatus is None
    raw = result.model_dump_json()
    assert all(secret not in raw for secret in ("manifest", "lease", "是谁", "PRIVATE", "report", "context"))


def test_default_7_day_window_50_rows_and_keyset_continuation_do_not_drift(agent_storage, monkeypatch):
    _, ids = runs(agent_storage, 55)
    owner = review(agent_storage)
    monkeypatch.setattr(owner.agent_store, "clock", lambda: 1000100.0)
    first = owner.list_runs()
    assert len(first.runs) == 50 and first.nextCursor is not None
    monkeypatch.setattr(owner.agent_store, "clock", lambda: 2000000.0)
    second = owner.list_runs(cursor=first.nextCursor)
    assert [row.id for row in (*first.runs, *second.runs)] == sorted(ids, reverse=True)
    assert len(second.runs) == 5 and second.nextCursor is None
    assert owner.list_runs().runs == ()


def test_index_100_maximum_bounded_single_join_and_no_full_history(agent_storage, monkeypatch):
    runs(agent_storage, 105)
    real_connect = sqlite3.connect
    statements = []
    def connect(*args, **kwargs):
        conn = real_connect(*args, **kwargs)
        conn.set_trace_callback(statements.append)
        return conn
    monkeypatch.setattr(sqlite3, "connect", connect)
    page = review(agent_storage).list_runs(limit=100, start=999999.0, end=1000001.0)
    assert len(page.runs) == 100 and page.nextCursor is not None
    queries = [sql for sql in statements if sql.lstrip().upper().startswith("SELECT") and "FROM agent_runs" in sql]
    assert len(queries) == 1
    assert "LIMIT 101" in queries[0] and "JOIN rule_candidates" in queries[0]
    assert all(secret not in queries[0] for secret in ("manifest_json", "candidate_json", "regression_json", "lease_token", "SELECT *"))
    assert not any("FROM agent_steps" in sql or "FROM feedback_items" in sql for sql in statements)


@pytest.mark.parametrize("changes", [{"limit": 0}, {"limit": 101}, {"limit": True}, {"limit": 1.0},
    {"start": True}, {"end": float("inf")}, {"start": float("nan")}, {"start": -1},
    {"start": 1000001.0, "end": 1000000.0}, {"start": 0, "end": 31 * 86400 + 1},
    {"feedback_id": "bad"}, {"cursor": "bad="}, {"cursor": "a" * 513}])
def test_invalid_index_queries_are_controlled_before_io(agent_storage, monkeypatch, changes):
    owner = review(agent_storage)
    def forbidden(*args, **kwargs):
        raise AssertionError("Invalid query touched database")
    monkeypatch.setattr(sqlite3, "connect", forbidden)
    with pytest.raises(import_module("app.candidate_review_contracts").CandidateReviewError) as error:
        owner.list_runs(**changes)
    assert error.value.status == 422


@pytest.mark.parametrize("changed", ["feedback", "start", "end", "limit"])
def test_cursor_cannot_be_reused_under_changed_fixed_scope(agent_storage, changed):
    item, _ = runs(agent_storage, 3)
    owner = review(agent_storage)
    params = dict(limit=1, start=999999.0, end=1000001.0, feedback_id=item.id)
    first = owner.list_runs(**params)
    assert first.nextCursor is not None
    params.update({"feedback_id": str(uuid4())} if changed == "feedback" else {changed: {"start": 999998.0,
        "end": 1000002.0, "limit": 2}[changed]})
    with pytest.raises(import_module("app.candidate_review_contracts").CandidateReviewError) as error:
        owner.list_runs(cursor=first.nextCursor, **params)
    assert error.value.status == 422


def test_time_filter_is_inclusive_and_feedback_filter_has_no_foreign_rows(agent_storage):
    item, ids = runs(agent_storage, 3)
    owner = review(agent_storage)
    assert {row.id for row in owner.list_runs(start=1000000.0, end=1000000.0, feedback_id=item.id).runs} == set(ids)
    assert owner.list_runs(start=1000000.0, end=1000000.0, feedback_id=str(uuid4())).runs == ()
    assert owner.list_runs(start=0, end=31 * 86400).nextCursor is None


def test_candidate_workflow_status_is_separate_from_original_agent_outcome(rule_storage):
    from .test_candidate_review_mutations import approve_intent
    owner, run, cid = proposal(rule_storage)
    owner.approve(cid, approve_intent(owner.detail(cid)))
    before = snapshot()
    row, = owner.list_runs(feedback_id=run.feedbackId).runs
    assert row.id == run.id and row.state == "awaiting_review" and row.candidateId == cid
    assert row.candidateStatus == "approved" and row.deadlineAt == run.checkpoint.deadlineAt
    assert row.rowVersion == run.rowVersion
    assert row.modelAttemptsUsed == run.checkpoint.modelAttemptsUsed
    assert row.toolAttemptsUsed == run.checkpoint.toolAttemptsUsed
    assert snapshot() == before


@pytest.mark.parametrize("change", ["checkpoint", "checkpoint_budget"])
def test_corrupt_selected_row_is_not_silently_dropped_or_zeroed(agent_storage, change):
    _, ids = runs(agent_storage, 1)
    conn = db._connect()
    try:
        conn.execute("UPDATE agent_runs SET checkpoint_json=? WHERE id=?",
            ("{}" if change == "checkpoint" else '{"modelAttemptsUsed":11}', ids[0]))
        conn.commit()
    finally:
        conn.close()
    with pytest.raises(import_module("app.candidate_review_contracts").CandidateReviewError) as error:
        review(agent_storage).list_runs(start=999999.0, end=1000001.0)
    assert error.value.status == 503


def test_existing_only_index_never_initializes_missing_or_schema2_database(storage, tmp_path):
    contracts = import_module("app.candidate_review_contracts")
    before = snapshot()
    with pytest.raises(contracts.CandidateReviewError) as error:
        review(storage).list_runs()
    assert error.value.status == 503 and snapshot() == before
    foreign = Runtime(replace(storage.settings, DATA_DIR=tmp_path / "missing-index"), model=storage.model)
    with pytest.raises(contracts.CandidateReviewError) as error:
        review(foreign).list_runs()
    assert error.value.status == 503 and not foreign.settings.DATA_DIR.exists()


@pytest.mark.parametrize("change", [{"scope": "feedback-v1"}, {"schemaVersion": True}, {"limit": 1.0},
    {"createdAt": True}, {"createdAt": 2000000.0}, {"id": "BAD"}, {"extraAuthority": True}])
def test_malformed_or_foreign_cursor_is_not_navigation_authority(agent_storage, change):
    runs(agent_storage, 3)
    owner = review(agent_storage)
    page = owner.list_runs(limit=1, start=999999.0, end=1000001.0)
    fields = baselines.strict_json(base64.urlsafe_b64decode(page.nextCursor + "=" * (-len(page.nextCursor) % 4)).decode())
    fields.update(change)
    cursor = base64.urlsafe_b64encode(baselines.canonical_json(fields).encode()).decode().rstrip("=")
    with pytest.raises(import_module("app.candidate_review_contracts").CandidateReviewError) as error:
        owner.list_runs(limit=1, cursor=cursor)
    assert error.value.status == 422


@pytest.mark.parametrize("change", [{"schemaVersion": True}, {"schemaVersion": 1.0}, {"extraAuthority": True}])
def test_closed_page_cannot_coerce_schema_or_accept_authority(agent_storage, change):
    from app.agents.contracts import checked_model, AgentError
    contracts = import_module("app.candidate_review_contracts")
    body = {**dict(schemaVersion=1, runs=[], nextCursor=None), **change}
    with pytest.raises(AgentError):
        checked_model(contracts.AgentRunPage, body)
