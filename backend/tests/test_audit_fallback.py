"""Synthetic storage faults; assertions concern persisted rows and bounded loss."""
import asyncio
import json
import sqlite3
from threading import Event, Lock
from uuid import uuid4

import pytest

from app import db
from app.audit_context import AttemptCollector
from app.runtime import get_runtime


def attempt(**changes):
    collector = AttemptCollector(str(uuid4()), wall_clock=lambda: 100.0)
    return collector.finish(status_code=changes.get("status", 200), method="POST",
        route_template="/api/chat", response_started=True, disconnected=False)


def make_store(*, connect=None, limits=(1000, 1048576)):
    from app.audit_store import AuditStore
    db.initialize()
    return AuditStore(get_runtime().settings.DATA_DIR,
        connect=connect or (lambda: db._connect(timeout=0.25)), fallback_limits=limits)


def fail_db():
    raise sqlite3.OperationalError("PRIVATE QUESTION / credential / path")


def read_events():
    conn = db._connect()
    try:
        return [dict(row) for row in conn.execute("SELECT * FROM audit_events")]
    finally:
        conn.close()


def test_attempt_database_success_and_exact_duplicate_is_one_row():
    store = make_store(); item = attempt()
    assert store.record_attempt(item).storage == "db"
    assert store.record_attempt(item).storage == "db"
    rows = read_events()
    assert len(rows) == 1 and rows[0]["id"] == item.eventId
    assert json.loads(rows[0]["details_json"]) == item.model_dump(mode="json")
    assert store.status().complete is True


def test_database_failure_uses_only_validated_safe_fallback(capsys):
    store = make_store(connect=fail_db); item = attempt()
    result = store.record_attempt(item)
    assert result.storage == "fallback" and result.persisted is True
    rows = store.fallback_path.read_text(encoding="utf-8").splitlines()
    assert len(rows) == 1 and json.loads(rows[0])["eventId"] == item.eventId
    status = store.status()
    assert status.fallbackCount == 1 and status.fallbackBytes <= 1048576
    assert status.complete is False and status.dropped == 0
    assert "PRIVATE" not in capsys.readouterr().err


def test_conflicting_same_event_id_is_not_overwritten_and_gap_is_visible():
    store = make_store(); item = attempt()
    assert store.record_attempt(item).storage == "db"
    changed = item.model_copy(update={"createdAt": 101.0})
    assert store.record_attempt(changed).storage == "dropped"
    assert len(read_events()) == 1 and read_events()[0]["created_at"] == 100.0
    assert store.status().permanentGap and store.status().dropped == 1


def test_fallback_exact_duplicates_do_not_fill_capacity():
    store = make_store(connect=fail_db, limits=(1, 1048576)); item = attempt()
    assert store.record_attempt(item).persisted
    assert store.record_attempt(item).persisted
    assert store.status().fallbackCount == 1


@pytest.mark.parametrize("limits", [(1, 1048576), (1000, 1900)])
def test_fallback_capacity_preserves_old_record_and_reports_unpersisted(limits):
    store = make_store(connect=fail_db, limits=limits)
    first = attempt(); assert store.record_attempt(first).storage == "fallback"
    before = store.fallback_path.read_bytes()
    outcomes = [store.record_attempt(attempt()) for _ in range(4)]
    assert any(item.storage == "dropped" and not item.persisted for item in outcomes)
    assert store.fallback_path.read_bytes().startswith(before)
    assert store.status().fallbackCount <= limits[0]
    assert store.status().fallbackBytes <= limits[1]
    assert store.status().permanentGap


def test_file_failure_buffers_bounded_memory_and_safe_hash_only_stderr(monkeypatch, capsys):
    store = make_store(connect=fail_db, limits=(1, 1048576))
    def fail_append(*args):
        raise OSError("SECRET reply / private fact / raw stack")
    monkeypatch.setattr(store, "_append_fallback", fail_append)
    first = attempt(); second = attempt()
    result = store.record_attempt(first)
    assert result.storage == "dropped" and not result.persisted
    assert store.status().memoryCount == 1
    assert not store.record_attempt(second).persisted
    assert store.status().memoryCount == 1 and store.status().dropped == 1
    output = capsys.readouterr().err
    assert "audit_unpersisted" in output and first.eventId not in output
    assert not any(raw in output for raw in ("PRIVATE", "SECRET", "reply", "raw stack"))


def test_recovery_is_idempotent_and_cleans_only_after_database_commit(monkeypatch):
    store = make_store(connect=fail_db); item = attempt()
    store.record_attempt(item)
    store.connect = lambda: db._connect(timeout=0.25)
    def fail_cleanup(*args):
        raise OSError("private path")
    original = store._replace_fallback
    monkeypatch.setattr(store, "_replace_fallback", fail_cleanup)
    first = store.recover_fallback()
    assert first.recovered == 1 and first.remaining == 1 and first.cleanupFailed
    assert len(read_events()) == 1 and store.fallback_path.exists()
    monkeypatch.setattr(store, "_replace_fallback", original)
    second = store.recover_fallback()
    assert second.recovered == 0 and second.duplicates == 1 and second.remaining == 0
    assert len(read_events()) == 1 and store.status().fallbackCount == 0


def test_failed_database_commit_retains_fallback(monkeypatch):
    store = make_store(connect=fail_db); store.record_attempt(attempt())
    before = store.fallback_path.read_bytes()
    assert store.recover_fallback().remaining == 1
    assert store.fallback_path.read_bytes() == before and read_events() == []


@pytest.mark.parametrize("tail", [b'{"schemaVersion":1', b'not-json\n', b'\xff\n'])
def test_partial_or_malformed_tail_retained_and_gap_survives_restart(tail):
    store = make_store(connect=fail_db); item = attempt(); store.record_attempt(item)
    with store.fallback_path.open("ab") as stream:
        stream.write(tail)
    reopened = make_store()
    report = reopened.recover_fallback()
    assert report.recovered == 1 and report.remaining >= 1
    assert tail in reopened.fallback_path.read_bytes()
    assert reopened.status().permanentGap and not reopened.status().complete
    assert make_store().status().permanentGap


def test_conflicting_fallback_event_retained_after_recovery():
    store = make_store(); item = attempt(); store.record_attempt(item)
    conflicting = item.model_copy(update={"createdAt": 102.0})
    store.connect = fail_db; store.record_attempt(conflicting)
    store.connect = lambda: db._connect(timeout=0.25)
    report = store.recover_fallback()
    assert report.conflicts == 1 and report.remaining == 1
    assert len(read_events()) == 1 and read_events()[0]["created_at"] == 100.0
    assert store.status().permanentGap


def test_oversized_existing_file_is_not_truncated_or_read_as_complete():
    store = make_store(connect=fail_db)
    payload = b"x" * (1048576 + 1)
    store.fallback_path.write_bytes(payload)
    reopened = make_store()
    assert not reopened.status().complete and reopened.status().permanentGap
    assert reopened.recover_fallback().remaining >= 1
    assert reopened.fallback_path.read_bytes() == payload


def test_business_event_cannot_enter_separate_attempt_fallback():
    from app.audit_events import AuditEvent, BusinessDetails
    store = make_store(connect=fail_db)
    item = AuditEvent(eventId=str(uuid4()), eventType="session_created", createdAt=100.0,
        details=BusinessDetails(reasonCode="session_created"))
    with pytest.raises(ValueError):
        store.record_attempt(item)
    assert not store.fallback_path.exists()


def test_audit_connect_timeout_set_before_wal(monkeypatch):
    real = sqlite3.connect; seen = []
    def tracked(*args, **kwargs):
        seen.append(kwargs["timeout"])
        return real(*args, **kwargs)
    db.initialize()
    monkeypatch.setattr(db.sqlite3, "connect", tracked)
    conn = db._connect(timeout=0.25)
    try:
        assert seen == [0.25]
        assert conn.execute("PRAGMA busy_timeout").fetchone()[0] == 250
    finally:
        conn.close()


def test_audit_io_admission_eight_before_executor_and_timeout_holds_job(monkeypatch):
    store = make_store(); release = Event(); lock = Lock(); entered = []
    original = store.record_attempt
    def blocked(item):
        with lock:
            entered.append(item.eventId)
        assert release.wait(3)
        return original(item)
    monkeypatch.setattr(store, "record_attempt", blocked)
    async def scenario():
        first = [await store.save_attempt(attempt(), wait_ms=2) for _ in range(8)]
        assert all(item.storage == "pending" and not item.persisted for item in first)
        assert store.status().activeIO == 8
        ninth = await store.save_attempt(attempt(), wait_ms=2)
        assert ninth.storage == "dropped" and not ninth.persisted
        assert store.status().activeIO == 8 and store.status().memoryCount == 1
        with lock:
            assert len(entered) <= 8
        release.set()
        summary = await store.close(wait_seconds=2)
        assert summary["residualJobs"] == 0
        assert len(read_events()) == 9
    try:
        asyncio.run(scenario())
    finally:
        release.set()


def test_io_busy_buffer_is_bounded_and_unpersisted(monkeypatch):
    store = make_store(limits=(1, 1048576)); release = Event()
    original = store.record_attempt
    def blocked(item):
        assert release.wait(3)
        return original(item)
    monkeypatch.setattr(store, "record_attempt", blocked)
    async def scenario():
        for _ in range(8):
            await store.save_attempt(attempt(), wait_ms=1)
        for _ in range(4):
            result = await store.save_attempt(attempt(), wait_ms=1)
            assert result.storage == "dropped" and not result.persisted
        status = store.status()
        assert status.memoryCount == 1 and status.memoryBytes <= 1048576 and status.dropped == 3
        assert not status.complete
        release.set(); await store.close(wait_seconds=2)
        assert len(read_events()) == 9
        assert store.status().permanentGap
    try:
        asyncio.run(scenario())
    finally:
        release.set()


def test_audit_close_reports_actual_residual_not_fake_cancellation(monkeypatch):
    store = make_store(); release = Event(); original = store.record_attempt
    def blocked(item):
        assert release.wait(3)
        return original(item)
    monkeypatch.setattr(store, "record_attempt", blocked)
    async def scenario():
        await store.save_attempt(attempt(), wait_ms=1)
        summary = await store.close(wait_seconds=0.01)
        assert summary["residualJobs"] == 1 and store.status().activeIO == 1
        assert not (await store.save_attempt(attempt(), wait_ms=1)).persisted
        release.set()
        for _ in range(100):
            if store.status().activeIO == 0:
                break
            await asyncio.sleep(0.005)
        assert store.status().activeIO == 0 and len(read_events()) == 1
    try:
        asyncio.run(scenario())
    finally:
        release.set()


def test_unknown_coverage_is_not_claimed_complete():
    store = make_store(connect=fail_db)
    assert store.status().coverageStart is None and store.status().complete is False


def test_partial_native_append_prevents_joining_another_record(monkeypatch):
    store = make_store(connect=fail_db)
    original = store._append_fallback
    def partial(line):
        with store.fallback_path.open("ab") as stream:
            stream.write(line[:20])
        raise OSError("private write detail")
    monkeypatch.setattr(store, "_append_fallback", partial)
    assert not store.record_attempt(attempt()).persisted
    before = store.fallback_path.read_bytes()
    monkeypatch.setattr(store, "_append_fallback", original)
    assert not store.record_attempt(attempt()).persisted
    assert store.fallback_path.read_bytes() == before
    assert store.status().permanentGap


def test_failed_actual_commit_keeps_original_fallback():
    store = make_store(connect=fail_db); item = attempt(); store.record_attempt(item)
    class FailingCommit:
        def __init__(self):
            self.conn = db._connect(timeout=0.25)
        def execute(self, *args):
            return self.conn.execute(*args)
        def commit(self):
            raise sqlite3.OperationalError("private commit detail")
        def rollback(self):
            self.conn.rollback()
        def close(self):
            self.conn.close()
    store.connect = FailingCommit
    before = store.fallback_path.read_bytes()
    report = store.recover_fallback()
    assert report.remaining == 1 and report.recovered == 0
    assert read_events() == [] and store.fallback_path.read_bytes() == before


def test_recovery_database_outage_does_not_try_one_thousand_connections():
    store = make_store(connect=fail_db)
    for _ in range(8):
        store.record_attempt(attempt())
    calls = []
    def unavailable():
        calls.append(1)
        return fail_db()
    store.connect = unavailable
    report = store.recover_fallback()
    assert report.remaining == 8 and report.recovered == 0
    assert len(calls) == 1


def test_cancelled_http_wait_does_not_release_live_worker(monkeypatch):
    store = make_store(); release = Event(); entered = Event(); original = store.record_attempt
    def blocked(item):
        entered.set(); assert release.wait(3)
        return original(item)
    monkeypatch.setattr(store, "record_attempt", blocked)
    async def scenario():
        wait = asyncio.create_task(store.save_attempt(attempt()))
        while not entered.is_set():
            await asyncio.sleep(0.002)
        wait.cancel()
        with pytest.raises(asyncio.CancelledError):
            await wait
        assert store.status().activeIO == 1
        release.set(); await store.close(wait_seconds=2)
        assert len(read_events()) == 1 and store.status().activeIO == 0
    try:
        asyncio.run(scenario())
    finally:
        release.set()


def test_async_recovery_uses_same_actual_io_admission(monkeypatch):
    store = make_store(); release = Event(); original_recover = store.recover_fallback
    original_record = store.record_attempt
    def slow_recover():
        assert release.wait(3)
        return original_recover()
    def slow_record(item):
        assert release.wait(3)
        return original_record(item)
    monkeypatch.setattr(store, "recover_fallback", slow_recover)
    monkeypatch.setattr(store, "record_attempt", slow_record)
    async def scenario():
        assert await store.recover(wait_ms=1) is None
        for _ in range(7):
            assert (await store.save_attempt(attempt(), wait_ms=1)).storage == "pending"
        assert store.status().activeIO == 8
        assert not (await store.save_attempt(attempt(), wait_ms=1)).persisted
        assert store.status().memoryCount == 1
        release.set(); await store.close(wait_seconds=2)
        assert len(read_events()) == 8 and store.status().activeIO == 0
    try:
        asyncio.run(scenario())
    finally:
        release.set()


def test_default_fallback_stops_at_one_thousand_without_overwriting():
    store = make_store(connect=fail_db)
    for _ in range(1000):
        assert store.record_attempt(attempt()).storage == "fallback"
    before = store.fallback_path.read_bytes()
    assert not store.record_attempt(attempt()).persisted
    assert store.status().fallbackCount == 1000
    assert store.fallback_path.read_bytes() == before and len(before) <= 1048576


def test_default_one_mib_bound_is_enforced_before_append():
    from app.audit_events import BusinessDetails
    store = make_store(connect=fail_db)
    def large():
        collector = AttemptCollector(str(uuid4()))
        collector.observe_metadata(BusinessDetails(evidenceIds=tuple("x" * 190 + str(i) for i in range(128)),
            evidenceCount=128))
        return collector.finish(status_code=200, method="POST", route_template="/api/chat",
            response_started=True, disconnected=False)
    for _ in range(100):
        result = store.record_attempt(large())
        if not result.persisted:
            break
    assert not result.persisted
    before = store.fallback_path.read_bytes()
    assert len(before) <= 1048576 and store.status().fallbackCount < 1000
    assert not store.record_attempt(large()).persisted
    assert store.fallback_path.read_bytes() == before


def test_failed_wal_setup_closes_owned_sqlite_connection(monkeypatch):
    db.initialize(); connections = []; real = sqlite3.connect
    class FailWAL(sqlite3.Connection):
        def execute(self, sql, *args):
            if sql == "PRAGMA journal_mode=WAL":
                raise sqlite3.OperationalError("Synthetic WAL setup failure")
            return super().execute(sql, *args)
    def connect(*args, **kwargs):
        conn = real(*args, **kwargs, factory=FailWAL)
        connections.append(conn)
        return conn
    monkeypatch.setattr(db.sqlite3, "connect", connect)
    with pytest.raises(sqlite3.OperationalError):
        db._connect(timeout=0.25)
    with pytest.raises(sqlite3.ProgrammingError, match="closed"):
        connections[0].execute("SELECT 1")


def test_emergency_gap_marker_survives_clean_shutdown():
    store = make_store(); store.note_failure(str(uuid4()))
    assert store.status().permanentGap and store.status().dropped == 1
    assert asyncio.run(store.close(wait_seconds=2))["residualJobs"] == 0
    reopened = make_store()
    assert reopened.status().permanentGap and reopened.status().dropped == 1


def test_gap_is_also_persisted_in_runtime_meta_when_sidecar_write_fails(monkeypatch):
    from pathlib import Path
    store = make_store(); real = Path.open
    def denied(path, *args, **kwargs):
        if path.name.startswith("audit-gap-"):
            raise OSError("Synthetic sidecar failure")
        return real(path, *args, **kwargs)
    monkeypatch.setattr(Path, "open", denied)
    store.note_failure(str(uuid4()))
    asyncio.run(store.close(wait_seconds=2))
    conn = db._connect()
    try:
        saved = conn.execute("SELECT value_json FROM runtime_meta WHERE key='audit_gap'").fetchone()
        assert saved is not None
        assert json.loads(saved[0]) == {"permanentGap": True, "dropped": 1}
    finally:
        conn.close()
    reopened = make_store()
    assert reopened.status().permanentGap and reopened.status().dropped == 1
