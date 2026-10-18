"""Actual synthetic business writes, latest snapshot, restore and idempotent replay.

These are mechanical conservation tests, not real model/human quality evidence.
SQL expectations read actual committed synthetic state, independently of the
snapshot implementation; literal counts also guard against empty equal states.
"""
import sqlite3
import asyncio
from threading import Event, Thread
from uuid import uuid4

import pytest
from fastapi.testclient import TestClient

from app import db, migrations
from app.candidate_review import CandidateReviewStore
from app.candidate_review_contracts import CandidatePublish, CandidateRollback
from app.config import Settings
from app.main import create_app
from app.runtime import runtime_context
from app.schemas import Soup
from app.scripts.recovery_quiescence import require_local_quiescence
from app.scripts.snapshot_recovery import RecoveryError, backup, restore
from app.testing import FakeModel
from .test_candidate_review_mutations import approve_intent
from .test_candidate_review_store import proposal
from .test_recovery_quiescence import WRITERS
from .test_release_recovery import hashes


TABLES = ("sessions", "messages", "creation_requests", "turns", "evaluations", "feedback_items",
          "agent_runs", "agent_steps", "rule_candidates", "puzzle_versions", "rule_releases", "runtime_meta")


def business_rows(path):
    conn = sqlite3.connect(path / "sessions.db")
    conn.row_factory = sqlite3.Row
    try:
        result = {table: [dict(row) for row in conn.execute(f"SELECT * FROM {table} ORDER BY rowid")]
                  for table in TABLES}
        result["business_audit"] = [dict(row) for row in conn.execute(
            "SELECT * FROM audit_events WHERE event_type <> 'http_attempt' ORDER BY rowid")]
        return result
    finally:
        conn.close()


def api_game(client, *, evaluate=False):
    creation = {"soupId": "synthetic", "level": "tianyi", "requestId": str(uuid4())}
    created = client.post("/api/chat", json=creation)
    assert created.status_code == 200, created.text
    ask = {"sessionId": created.json()["sessionId"], "question": "小明是凶手吗？", "requestId": str(uuid4())}
    asked = client.post("/api/chat", json=ask)
    assert asked.status_code == 200, asked.text
    evaluation = None
    if evaluate:
        response = client.post("/api/evaluate", json={"sessionId": created.json()["sessionId"]})
        assert response.status_code == 200, response.text
        evaluation = response.json()
    return creation, created.json(), ask, asked.json(), evaluation


def verify_latest_business_state(path, expected):
    """Test-only conservation oracle, never a product privacy/export endpoint."""
    assert business_rows(path) == expected, "Restored snapshot is not the latest committed business state"


def test_latest_api_agent_publication_data_survives_restore_and_rule_rollback(tmp_path):
    source = tmp_path / "business-source"
    source.mkdir()
    soup = Soup(id="synthetic", title="Test", surface="Surface", bottom="小明是凶手。",
                confusionPoints=[{"q": "小明是凶手吗？", "a": "不是"}])
    conn = sqlite3.connect(source / "sessions.db")
    try:
        migrations.migrate(conn, [soup], target_version=4)
    finally:
        conn.close()
    settings = Settings.for_test(source, ADMIN_TOKEN="synthetic-admin")
    model = FakeModel()
    first_app = create_app(settings, model=model, soups=[soup])
    with TestClient(first_app) as client:
        original = api_game(client)
    require_local_quiescence(first_app.state.runtime, WRITERS)
    backup(str(source), str(tmp_path / "before-release"), str(tmp_path / "before-report.json"))
    old_artifact_hashes = hashes(tmp_path / "before-release")

    new_app = create_app(settings, model=model, soups=[soup])
    with TestClient(new_app) as client:
        new_game = api_game(client, evaluate=True)
        with runtime_context(new_app.state.runtime):
            review, run, candidate = proposal(new_app.state.runtime)
            approval = approve_intent(review.detail(candidate))
            review.approve(candidate, approval)
            detail = review.detail(candidate)
            publish_intent = CandidatePublish(operationKey=str(uuid4()), expectedReviewVersion=detail.reviewVersion,
                expectedProofDigest=detail.proofDigest, expectedRuleVersion=detail.activeRuleVersion,
                expectedPointerVersion=detail.activePointerVersion)
            published = review.publish(candidate, publish_intent)
        published_game = api_game(client)
        assert original[3]["reply"] == new_game[3]["reply"] == "不是"
        assert published_game[3]["reply"] == "是"
        corpus = new_app.state.runtime.repair_corpus
    active = new_app.state.runtime
    require_local_quiescence(active, WRITERS)
    assert active.audit_shutdown["residualJobs"] == 0
    assert active.audit_shutdown["unpersistedCount"] == 0
    assert active.model_shutdown["active"] == 0
    basis = business_rows(source)
    # Existing proposal.prepared -> approved_linked -> completed_turn creates
    # one additional actual linked session/turn through business methods.
    assert len(basis["sessions"]) == 4
    assert len(basis["turns"]) == 4 and len(basis["messages"]) == 8
    assert len(basis["evaluations"]) == 1 and len(basis["feedback_items"]) == 1
    assert len(basis["agent_runs"]) == len(basis["rule_candidates"]) == 1
    assert len(basis["agent_steps"]) > 0 and len(basis["rule_releases"]) == 2
    linked_turn, = [row for row in basis["turns"] if row["id"] == run.manifest.context.turnId]
    assert {row["id"] for row in basis["sessions"]} == {
        *(game[1]["sessionId"] for game in (original, new_game, published_game)), linked_turn["session_id"]}
    assert basis["agent_runs"][0]["id"] == run.id
    assert basis["rule_candidates"][0]["id"] == candidate
    source_hashes = hashes(source)
    latest = tmp_path / "latest-release"
    backup(str(source), str(latest), str(tmp_path / "latest-report.json"))
    restored = tmp_path / "restored-latest"
    restore(str(latest), str(restored), str(tmp_path / "restore-report.json"))
    assert hashes(source) == source_hashes
    assert hashes(tmp_path / "before-release") == old_artifact_hashes
    verify_latest_business_state(restored, basis)

    # A valid old artifact can still be the WRONG recovery choice. Independent
    # business facts, not SQLite integrity alone, must catch the lost new IDs.
    obsolete = tmp_path / "restored-obsolete"
    restore(str(tmp_path / "before-release"), str(obsolete), str(tmp_path / "obsolete-report.json"))
    with pytest.raises(AssertionError, match="not the latest"):
        verify_latest_business_state(obsolete, basis)
    assert len(business_rows(obsolete)["sessions"]) == 1

    resumed = create_app(Settings.for_test(restored, ADMIN_TOKEN="synthetic-admin"), model=FakeModel(),
                         soups=[soup], repair_corpus=corpus)
    with TestClient(resumed) as client:
        for creation, created, ask, asked, evaluation in (original, new_game, published_game):
            assert client.get("/api/session/" + created["sessionId"]).status_code == 200
            assert client.post("/api/chat", json=creation).json() == created
            assert client.post("/api/chat", json=ask).json() == asked
            if evaluation is not None:
                assert client.post("/api/evaluate", json={"sessionId": created["sessionId"]}).json() == evaluation
        with runtime_context(resumed.state.runtime):
            review = CandidateReviewStore(resumed.state.runtime)
            assert review.approve(candidate, approval).action == "approved"
            assert review.publish(candidate, publish_intent) == published
        verify_latest_business_state(restored, basis)
        rollback_intent = CandidateRollback(operationKey=str(uuid4()), targetRuleVersion=publish_intent.expectedRuleVersion,
            expectedRuleVersion=published.publishedRuleVersion, expectedPointerVersion=1, reason="Synthetic recovery rollback")
        with runtime_context(resumed.state.runtime):
            rolled_back = review.rollback(rollback_intent)
            assert rolled_back.ruleVersion == publish_intent.expectedRuleVersion
            assert rolled_back.pointerVersion == 2
        reverted = business_rows(restored)
        # Rollback only changes version pointers/receipts and adds its own audit;
        # all actual game, feedback, task and immutable rule records survive.
        for table in TABLES:
            if table != "runtime_meta":
                assert reverted[table] == basis[table]
        with runtime_context(resumed.state.runtime):
            assert review.rollback(rollback_intent) == rolled_back
            assert review.publish(candidate, publish_intent) == published
        verify_latest_business_state(restored, reverted)
    require_local_quiescence(resumed.state.runtime, WRITERS)
    assert hashes(source) == source_hashes
    assert hashes(tmp_path / "before-release") == old_artifact_hashes


@pytest.mark.parametrize("version", [1, 2, 3, 4])
def test_restored_schema_matrix_uses_actual_current_startup_and_business_replay(tmp_path, version):
    source = tmp_path / "matrix-source"
    source.mkdir()
    soup = Soup(id="synthetic", title="Test", surface="Surface", bottom="Synthetic fact",
                confusionPoints=[{"q": "小明是凶手吗？", "a": "不是"}])
    conn = sqlite3.connect(source / "sessions.db")
    try:
        migrations.migrate(conn, [soup], target_version=version)
    finally:
        conn.close()
    original = None
    if version >= 2:
        source_app = create_app(Settings.for_test(source), model=FakeModel(), soups=[soup])
        with TestClient(source_app) as client:
            original = api_game(client)
            original_history = client.get("/api/session/" + original[1]["sessionId"]).json()
        require_local_quiescence(source_app.state.runtime, WRITERS)
    before = hashes(source)
    backup(str(source), str(tmp_path / "matrix-artifact"), str(tmp_path / "backup-report.json"))
    restored = tmp_path / "matrix-restored"
    restore(str(tmp_path / "matrix-artifact"), str(restored), str(tmp_path / "restore-report.json"))
    restored_before = hashes(restored)
    app = create_app(Settings.for_test(restored), model=FakeModel(), soups=[soup])
    if version == 1:
        with pytest.raises(migrations.MigrationRequired):
            with TestClient(app):
                pytest.fail("Current default requires002; schema001 cannot open for writing")
        assert hashes(restored) == restored_before
        assert app.state.runtime.closed
        assert app.state.runtime.model_gateway is None and app.state.runtime.agent_worker is None
    else:
        with TestClient(app) as client:
            assert client.get("/api/session/" + original[1]["sessionId"]).json() == original_history
            new = api_game(client)
            assert new[1]["sessionId"] != original[1]["sessionId"]
            assert client.post("/api/chat", json=original[0]).json() == original[1]
            assert client.post("/api/chat", json=original[2]).json() == original[3]
        require_local_quiescence(app.state.runtime, WRITERS)
        conn = sqlite3.connect(restored / "sessions.db")
        try:
            assert conn.execute("SELECT count(*) FROM schema_migrations").fetchone()[0] == version
            assert conn.execute("SELECT count(*) FROM sessions").fetchone()[0] == 2
            assert conn.execute("SELECT count(*) FROM turns").fetchone()[0] == 2
            assert conn.execute("SELECT count(*) FROM messages").fetchone()[0] == 4
            assert [row[0] for row in conn.execute("SELECT questions_asked FROM sessions")] == [1, 1]
        finally:
            conn.close()
    assert hashes(source) == before


def test_controlled_legacy_cron_and_timer_callbacks_stop_before_local_backup(tmp_path, runtime):
    from app.scripts import merge_verified_qa as legacy
    source = tmp_path / "timers-source"
    runtime.settings = Settings.for_test(source)
    runtime.soups = [Soup(id="synthetic", title="Test", surface="Surface", bottom="Synthetic fact")]
    db.initialize()
    before = hashes(source)
    stop = Event()
    called = {"cron": Event(), "timer": Event()}
    outcomes = []

    def callback(kind):
        with runtime_context(runtime):
            while not stop.is_set():
                try:
                    if kind == "cron":
                        legacy.run_merge(str(source / "feedback.jsonl"), str(source / "verified_qa_pairs.jsonl"),
                                         restart_backend=True)
                    else:
                        legacy.cleanup_old_sessions()
                    outcomes.append("unexpected_writer_return")
                except legacy.LegacyWriterDisabled:
                    outcomes.append("legacy_writer_disabled")
                finally:
                    called[kind].set()
                stop.wait(0.05)

    threads = [Thread(target=callback, args=(kind,), daemon=True) for kind in ("cron", "timer")]
    try:
        for thread in threads:
            thread.start()
        assert all(event.wait(2) for event in called.values())
        asyncio.run(runtime.aclose())
        with pytest.raises(RecoveryError):
            require_local_quiescence(runtime, {**WRITERS, "cron": "active", "timer": "active"})
    finally:
        stop.set()
        for thread in threads:
            thread.join(timeout=2)
        assert all(not thread.is_alive() for thread in threads)
    assert len(outcomes) >= 2 and set(outcomes) == {"legacy_writer_disabled"}
    assert hashes(source) == before
    assert require_local_quiescence(runtime, WRITERS)["quiescenceVerified"] is False
    backup(str(source), str(tmp_path / "timers-artifact"), str(tmp_path / "timers-report.json"))
    assert hashes(source) == before
