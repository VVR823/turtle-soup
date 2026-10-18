"""TS09 sole-review regressions, using guarded synthetic SQLite and HTTP only."""
import asyncio
import gc
import json
import sqlite3
from threading import Event
from uuid import uuid4

import pytest
from fastapi.testclient import TestClient

from app import db, migrations
from app.audit_context import AttemptCollector
from app.audit_store import AuditStore
from app.config import Settings
from app.main import create_app
from app.runtime import get_runtime
from app.testing import FakeModel
from .test_audit_admin import ADMIN, api, seed
from .test_audit_fallback import attempt, make_store, read_events
from .test_migrations import puzzle


def test_late_insert_and_close_failure_keeps_attempt_visible(monkeypatch, capsys):
    store = make_store(); release = Event()
    class FailedConnection:
        def __init__(self):
            self.inner = db._connect(timeout=0.25)
        def execute(self, statement, parameters=()):
            if statement.startswith("INSERT INTO audit_events"):
                raise sqlite3.OperationalError("SYNTHETIC SECRET insert")
            return self.inner.execute(statement, parameters)
        def commit(self):
            self.inner.commit()
        def rollback(self):
            self.inner.rollback()
        def close(self):
            assert release.wait(3)
            self.inner.close()
            raise OSError("SYNTHETIC SECRET close")
    monkeypatch.setattr(store, "connect", FailedConnection)
    async def scenario():
        try:
            assert (await store.save_attempt(attempt(), wait_ms=1)).storage == "pending"
            tasks = list(store._tasks); release.set()
            await asyncio.gather(*tasks, return_exceptions=True)
            await asyncio.sleep(0)
            assert read_events() == []
            assert not store.status().complete
            assert store.status().fallbackCount + store.status().memoryCount + store.status().dropped >= 1
        finally:
            release.set(); await store.close(wait_seconds=1)
    asyncio.run(scenario())
    assert "SYNTHETIC SECRET" not in capsys.readouterr().err


@pytest.mark.parametrize("wait_ms", [1, 500])
def test_terminal_attempt_owner_handles_failure_once_before_or_after_wait(monkeypatch, wait_ms, capsys):
    store = make_store(); release = Event(); item = attempt()
    def failed(_item):
        assert release.wait(3)
        raise OSError("SYNTHETIC SECRET unexpected worker failure")
    monkeypatch.setattr(store, "record_attempt", failed)
    async def scenario():
        try:
            if wait_ms == 500:
                release.set()
            result = await store.save_attempt(item, wait_ms=wait_ms)
            tasks = list(store._tasks); release.set()
            await asyncio.gather(*tasks, return_exceptions=True)
            await asyncio.sleep(0)
            state = store.status()
            assert not state.complete and state.permanentGap
            assert state.memoryCount == 1 and state.dropped == 0 and state.activeIO == 0
            if wait_ms == 500:
                assert result.persisted is False
            marker = json.loads(store._gap_path.read_text())
            assert marker == {"permanentGap": True, "dropped": 0}
        finally:
            release.set(); await store.close(wait_seconds=0)
    asyncio.run(scenario())
    assert "SYNTHETIC SECRET" not in capsys.readouterr().err


def test_shutdown_recovery_failure_is_owned_without_raw_asyncio_log(monkeypatch, caplog):
    store = make_store(); store.note_failure(str(uuid4())); release = Event()
    def failed():
        assert release.wait(3)
        raise OSError("SYNTHETIC SECRET shutdown")
    monkeypatch.setattr(store, "recover_fallback", failed)
    async def scenario():
        try:
            result = await store.close(wait_seconds=0.01)
            assert result["residualJobs"] == 1
            tasks = list(store._tasks); release.set()
            await asyncio.wait(tasks, timeout=1)
            await asyncio.sleep(0)
            del tasks
            gc.collect(); await asyncio.sleep(0)
            assert store.status().activeIO == 0
            assert "SYNTHETIC SECRET" not in caplog.text
            assert "Task exception was never retrieved" not in caplog.text
        finally:
            release.set()
    asyncio.run(scenario())


@pytest.mark.parametrize("marker", [
    {"dropped": 0}, {"permanentGap": "lost", "dropped": 0},
    {"permanentGap": False, "dropped": 2**63},
    {"permanentGap": False, "dropped": 0, "extra": True},
])
def test_malformed_sidecar_is_uncertainty_not_complete_coverage(marker):
    store = make_store()
    store._gap_path.write_text(json.dumps(marker), encoding="utf-8")
    reopened = AuditStore(get_runtime().settings.DATA_DIR, connect=lambda: db._connect(timeout=0.25))
    assert reopened.status().permanentGap and not reopened.status().complete


@pytest.mark.parametrize("raw", [
    '{"permanentGap":true,"permanentGap":false,"dropped":0}',
    '{"permanentGap":false,"dropped":1}',
])
def test_ambiguous_or_nonzero_loss_marker_cannot_report_complete(raw):
    store = make_store(); store._gap_path.write_text(raw, encoding="utf-8")
    reopened = AuditStore(get_runtime().settings.DATA_DIR, connect=lambda: db._connect(timeout=0.25))
    assert not reopened.status().complete and reopened.status().permanentGap


def test_opaque_file_does_not_strand_admission_overflow_ram(monkeypatch):
    db.initialize(); path = get_runtime().settings.DATA_DIR / "audit-fallback.jsonl"
    path.write_bytes(b"x" * 4097)
    store = AuditStore(get_runtime().settings.DATA_DIR, connect=lambda: db._connect(timeout=0.25),
        fallback_limits=(1, 4096))
    release = Event(); original = store.record_attempt
    def blocked(item):
        assert release.wait(3)
        return original(item)
    monkeypatch.setattr(store, "record_attempt", blocked)
    async def scenario():
        try:
            for _ in range(8):
                assert (await store.save_attempt(attempt(), wait_ms=1)).storage == "pending"
            ninth = attempt()
            assert not (await store.save_attempt(ninth, wait_ms=1)).persisted
            assert store.status().activeIO == 8 and store.status().memoryCount == 1
            tasks = list(store._tasks); release.set(); await asyncio.gather(*tasks)
            report = store.recover_fallback()
            assert store.status().memoryCount == 0 and report.remaining == 1
            assert len(read_events()) == 9 and any(row["id"] == ninth.eventId for row in read_events())
            assert path.read_bytes() == b"x" * 4097
            assert store.status().permanentGap and not store.status().complete
        finally:
            release.set(); await store.close(wait_seconds=1)
    asyncio.run(scenario())


def test_default_cursor_keeps_first_window_when_clock_advances(api, monkeypatch):
    from app.routers import audit
    now = 1000000.0
    seed(api, 3, stamp=now - 7 * 86400 + 0.5)
    monkeypatch.setattr(audit.time, "time", lambda: now)
    first = api[1].get("/api/audit/admin", headers=ADMIN, params={"limit": 1})
    assert first.status_code == 200 and first.json()["nextCursor"]
    monkeypatch.setattr(audit.time, "time", lambda: now + 1)
    second = api[1].get("/api/audit/admin", headers=ADMIN,
        params={"limit": 2, "cursor": first.json()["nextCursor"]})
    assert second.status_code == 200 and len(second.json()["events"]) == 2
    assert second.json()["nextCursor"] is None


@pytest.mark.parametrize("change", [{"start": 99.5}, {"end": 101.5}, {"eventType": "session_created"}])
def test_cursor_refuses_changed_window_or_filter(api, change):
    seed(api, 3, stamp=100.0)
    params = {"limit": 1, "start": 99, "end": 101, "eventType": "http_attempt"}
    first = api[1].get("/api/audit/admin", headers=ADMIN, params=params)
    assert first.status_code == 200
    params.update(cursor=first.json()["nextCursor"], **change)
    changed = api[1].get("/api/audit/admin", headers=ADMIN, params=params)
    assert changed.status_code == 422 and changed.json()["code"] == "audit_query_invalid"


def test_changed_check_literal_case_refused_even_with_valid_002_ledger():
    db.initialize(); conn = db._connect()
    try:
        conn.execute("DROP TABLE feedback_items")
        conn.execute(migrations.AUDIT_SQL[0].replace("'pending','approved','rejected'", "'PENDING','APPROVED','REJECTED'"))
        conn.execute(migrations.AUDIT_SQL[3]); conn.commit()
        with pytest.raises(sqlite3.IntegrityError):
            conn.execute("INSERT INTO feedback_items(id,soup_id,payload_json,source_json,status,created_at) "
                "VALUES('synthetic','synthetic','{}','{}','pending',1)")
        conn.rollback()
        with pytest.raises(migrations.MigrationError):
            migrations.verify_schema(conn, required_version=2)
    finally:
        conn.close()


def test_valid_long_legacy_identity_restores_without_truncating_audit_id(tmp_path):
    data = tmp_path / "legacy-id"; data.mkdir(); identity = "legacy-" + "x" * 194
    conn = sqlite3.connect(data / "sessions.db")
    try:
        report = migrations.migrate(conn, [puzzle()], target_version=2, legacy_records=[{
            "id": identity, "soupId": puzzle().id, "questionsAsked": 0, "createdAt": 100.0,
            "questionLimit": 3, "messages": []}])
        assert report["incompatibleSessions"] == 0 and report["importedSessions"] == 1
    finally:
        conn.close()
    app = create_app(Settings.for_test(data), model=FakeModel(), soups=[puzzle()])
    with TestClient(app, raise_server_exceptions=False) as client:
        response = client.get("/api/session/" + identity)
        assert response.status_code == 200 and response.json()["sessionId"] == identity
        conn = sqlite3.connect(data / "sessions.db")
        try:
            rows = conn.execute("SELECT session_id,details_json FROM audit_events WHERE event_type='http_attempt'").fetchall()
            assert len(rows) == 1 and rows[0][0] is None
            assert json.loads(rows[0][1])["details"]["metadataTruncated"] is True
        finally:
            conn.close()


def test_invalid_optional_association_omits_id_and_flags_gap_without_replacing_valid_ids():
    collector = AttemptCollector(str(uuid4()))
    assert collector.bind_ids(session_id="valid")
    assert collector.bind_ids(turn_id="x" * 201) is False
    item = collector.finish(status_code=200, method="GET", route_template="/health",
        response_started=True, disconnected=False)
    assert item.sessionId == "valid" and item.turnId is None and item.details.metadataTruncated
