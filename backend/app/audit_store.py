"""Private bounded attempt storage; business inserts borrow the caller's transaction.

Memory is explicitly UNPERSISTED. Native I/O cannot be forcibly cancelled;
timeouts bound the caller's wait, not the lifetime of an admitted worker.
"""
import asyncio
import hashlib
import os
import sys
import time
from dataclasses import dataclass
from pathlib import Path
from threading import RLock
from uuid import uuid4

from .audit_events import AUDIT_EVENT_TYPES, AuditEvent, MAX_EVENT_BYTES
from .baselines import canonical_json, strict_json
from .migrations import CHECKSUM_002

_PENDING, _BUSY = object(), object()


class AuditPersistenceError(RuntimeError):
    pass


class AuditConflict(AuditPersistenceError):
    pass


@dataclass(frozen=True)
class AuditWriteResult:
    storage: str
    eventId: str
    persisted: bool


@dataclass(frozen=True)
class RecoveryReport:
    recovered: int = 0
    duplicates: int = 0
    conflicts: int = 0
    remaining: int = 0
    cleanupFailed: bool = False


@dataclass(frozen=True)
class AuditStatus:
    complete: bool
    permanentGap: bool
    dropped: int
    fallbackCount: int
    fallbackBytes: int
    memoryCount: int
    memoryBytes: int
    activeIO: int
    coverageStart: dict | None


def _payload(event):
    if not isinstance(event, AuditEvent):
        raise ValueError("Validated audit event required")
    # Revalidate even frozen objects: model_copy can bypass Pydantic validators.
    raw = canonical_json(event.model_dump(mode="json"))
    checked = AuditEvent.model_validate_json(raw)
    if len(raw.encode("utf-8")) > MAX_EVENT_BYTES:
        raise ValueError("Audit byte budget exceeded")
    return checked, raw


def _insert(conn, event, raw):
    old = conn.execute("SELECT id,request_id,session_id,turn_id,run_id,event_type,details_json,created_at "
        "FROM audit_events WHERE id=?", (event.eventId,)).fetchone()
    values = (event.eventId, event.requestId, event.sessionId, event.turnId, event.runId,
        event.eventType, raw, event.createdAt)
    if old is not None:
        if tuple(old) != values:
            raise AuditConflict("Audit identity conflicts with persisted payload")
        return False
    conn.execute("INSERT INTO audit_events(id,request_id,session_id,turn_id,run_id,event_type,details_json,created_at) "
        "VALUES(?,?,?,?,?,?,?,?)", values)
    return True


def insert_business_event(conn, event):
    checked, raw = _payload(event)
    if checked.eventType == "http_attempt" or not conn.in_transaction:
        raise AuditPersistenceError("Business audit requires its existing transaction")
    try:
        row = conn.execute("SELECT checksum FROM schema_migrations WHERE version=2").fetchone()
        if row is None or row[0] != CHECKSUM_002:
            raise AuditPersistenceError("Registered audit migration required")
        _insert(conn, checked, raw)
    except AuditPersistenceError:
        raise
    except Exception:
        raise AuditPersistenceError("Business audit could not be persisted") from None


class AuditStore:
    def __init__(self, data_dir: Path, *, connect, clock=time.monotonic, fallback_limits=(1000, 1048576)):
        count, byte_limit = fallback_limits
        if type(count) is not int or type(byte_limit) is not int or not 1 <= count <= 1000 or not 1 <= byte_limit <= 1048576:
            raise ValueError("Invalid bounded fallback limits")
        self.connect, self.clock = connect, clock
        self.fallback_path = Path(data_dir) / "audit-fallback.jsonl"
        self._gap_path = Path(data_dir) / "audit-gap.json"
        self._count_limit, self._byte_limit = count, byte_limit
        self._lock, self._io_lock = RLock(), RLock()
        self._lines, self._fallback_ids = [], {}
        self._fallback_bytes, self._opaque_file = 0, False
        self._memory, self._memory_bytes = {}, 0
        self._permanent_gap, self._dropped = False, 0
        self._active, self._tasks, self._closed = 0, set(), False
        self._coverage = None
        self._read_gap()
        self._load_fallback()
        try:
            conn = self.connect()
            try:
                row = conn.execute("SELECT value_json FROM runtime_meta WHERE key='audit_coverage_start'").fetchone()
                if row:
                    import json
                    value = json.loads(row[0])
                    if (type(value) is dict and value.get("schemaVersion") == 1
                        and type(value.get("startedAt")) in (int, float)
                        and value.get("historicalAttemptsBackfilled") is False):
                        self._coverage = {"schemaVersion": 1, "startedAt": value["startedAt"],
                            "historicalAttemptsBackfilled": False}
                gap = conn.execute("SELECT substr(value_json,1,1025) FROM runtime_meta WHERE key='audit_gap'").fetchone()
                if gap:
                    self._merge_gap(gap[0])
            finally:
                conn.close()
        except Exception:
            pass  # Unknown epoch stays NULL, never manufactures old coverage.

    def _merge_gap(self, raw):
        try:
            if len(raw) > 1024:
                raise ValueError("Oversized gap status")
            value = strict_json(raw)
            if (type(value) is not dict or set(value) != {"permanentGap", "dropped"}
                or type(value["permanentGap"]) is not bool or type(value["dropped"]) is not int
                or not 0 <= value["dropped"] <= 9223372036854775807):
                raise ValueError("Malformed gap status")
            with self._lock:
                self._permanent_gap |= value["permanentGap"] or value["dropped"] > 0
                self._dropped = max(self._dropped, value["dropped"])
        except Exception:
            self._permanent_gap = True

    def _read_gap(self):
        try:
            with self._gap_path.open("rb") as stream:
                raw = stream.read(1025)
            self._merge_gap(raw)
        except FileNotFoundError:
            pass
        except Exception:
            self._permanent_gap = True

    def _persist_gap(self):
        # Either destination can survive a failure of the other. Existing
        # permanent gaps are monotone; restart/recovery never clears them.
        with self._lock:
            needs_db = self._permanent_gap or self._dropped
        if needs_db:
            conn = None
            try:
                conn = self.connect(); conn.execute("BEGIN IMMEDIATE")
                old = conn.execute("SELECT substr(value_json,1,1025) FROM runtime_meta WHERE key='audit_gap'").fetchone()
                if old:
                    self._merge_gap(old[0])
                with self._lock:
                    value = canonical_json({"permanentGap": self._permanent_gap, "dropped": self._dropped})
                conn.execute("INSERT INTO runtime_meta(key,value_json) VALUES('audit_gap',?) "
                    "ON CONFLICT(key) DO UPDATE SET value_json=excluded.value_json,row_version=row_version+1", (value,))
                conn.commit()
            except Exception:
                if conn is not None:
                    try:
                        conn.rollback()
                    except Exception:
                        pass
            finally:
                if conn is not None:
                    try:
                        conn.close()
                    except Exception:
                        pass  # A DB cleanup fault must not suppress the sidecar.
        with self._lock:
            raw = canonical_json({"permanentGap": self._permanent_gap, "dropped": self._dropped}).encode()
        temp = self._gap_path.with_name("audit-gap-" + str(uuid4()) + ".tmp")
        try:
            with temp.open("xb") as stream:
                stream.write(raw); stream.flush(); os.fsync(stream.fileno())
            os.replace(temp, self._gap_path)
        except Exception:
            pass  # Total disk failure cannot persist the loss marker; stderr remains.
        finally:
            try:
                temp.unlink(missing_ok=True)
            except OSError:
                pass

    def _load_fallback(self):
        try:
            with self.fallback_path.open("rb") as stream:
                raw = stream.read(self._byte_limit + 1)
            self._fallback_bytes = len(raw)
            if len(raw) > self._byte_limit or len(raw.splitlines()) > self._count_limit:
                self._opaque_file = True
                self._permanent_gap = True
                self._persist_gap()
                return
            self._lines = raw.splitlines(keepends=True)
            for line in self._lines:
                try:
                    if not line.endswith(b"\n"):
                        raise ValueError("Partial line")
                    item = AuditEvent.model_validate_json(line)
                    item, text = _payload(item)
                    if item.eventType != "http_attempt":
                        raise ValueError("Unexpected event type")
                    previous = self._fallback_ids.get(item.eventId)
                    if previous is not None and previous != text:
                        raise ValueError("Conflicting fallback")
                    self._fallback_ids[item.eventId] = text
                except Exception:
                    self._permanent_gap = True
            if self._permanent_gap:
                self._persist_gap()
        except FileNotFoundError:
            pass
        except Exception:
            self._opaque_file, self._permanent_gap = True, True
            self._persist_gap()

    def status(self):
        with self._lock:
            count = max(1, len(self._lines)) if self._opaque_file else len(self._lines)
            return AuditStatus(self._coverage is not None and not (self._permanent_gap or count or self._memory or self._active),
                self._permanent_gap, self._dropped, count, self._fallback_bytes,
                len(self._memory), self._memory_bytes, self._active,
                dict(self._coverage) if self._coverage is not None else None)

    def query_events(self, *, limit, start, end, cursor=None, event_type=None):
        """Explicit columns, parameterized time/index range, at most 101 rows."""
        import math
        from .audit_events import UUID_PATTERN
        if (type(limit) is not int or not 1 <= limit <= 100
            or any(type(value) not in (int, float) or not math.isfinite(value) or value < 0 for value in (start, end))
            or not 0 <= end - start <= 31 * 86400 or event_type is not None and event_type not in AUDIT_EVENT_TYPES):
            raise ValueError("Invalid bounded audit query")
        sql = ("SELECT id,request_id,session_id,turn_id,run_id,event_type,details_json,created_at "
            "FROM audit_events WHERE created_at>=? AND created_at<=?")
        args = [start, end]
        if cursor is not None:
            stamp, event_id = cursor
            if type(stamp) not in (int, float) or not math.isfinite(stamp) or stamp < 0 or not isinstance(event_id, str) or not UUID_PATTERN.fullmatch(event_id):
                raise ValueError("Invalid audit cursor")
            sql += " AND (created_at<? OR (created_at=? AND id<?))"
            args.extend((stamp, stamp, event_id))
        if event_type is not None:
            sql += " AND event_type=?"; args.append(event_type)
        sql += " ORDER BY created_at DESC,id DESC LIMIT ?"; args.append(limit + 1)
        conn = None
        try:
            conn = self.connect()
            rows = conn.execute(sql, tuple(args)).fetchmany(limit + 1)
            result = []
            for row in rows:
                item, raw = _payload(AuditEvent.model_validate_json(row["details_json"]))
                mirror = (item.eventId, item.requestId, item.sessionId, item.turnId, item.runId, item.eventType, item.createdAt)
                if tuple(row[key] for key in ("id", "request_id", "session_id", "turn_id", "run_id", "event_type", "created_at")) != mirror:
                    raise AuditPersistenceError("Audit row is inconsistent")
                result.append(item)
            return result[:limit], len(result) > limit
        except Exception:
            raise AuditPersistenceError("Audit records are unavailable") from None
        finally:
            if conn is not None:
                conn.close()

    def _unpersisted(self, item, raw, *, permanent=False):
        with self._lock:
            size = len(raw.encode()) + 1
            old = self._memory.get(item.eventId)
            if old is not None and old != raw:
                self._dropped += 1; self._permanent_gap = True
            elif old is None:
                if len(self._memory) < self._count_limit and self._memory_bytes + size <= self._byte_limit:
                    self._memory[item.eventId] = raw; self._memory_bytes += size
                else:
                    self._dropped += 1; self._permanent_gap = True
            self._permanent_gap |= permanent
        digest = hashlib.sha256(item.eventId.encode()).hexdigest()[:16]
        print("audit_unpersisted event_hash=" + digest, file=sys.stderr)
        return AuditWriteResult("dropped", item.eventId, False)

    def note_failure(self, event_id):
        """Emergency visibility without event-loop filesystem I/O or raw errors."""
        with self._lock:
            self._permanent_gap = True; self._dropped += 1
        print("audit_unpersisted event_hash=" + hashlib.sha256(event_id.encode()).hexdigest()[:16], file=sys.stderr)

    def _append_fallback(self, line):
        with self.fallback_path.open("ab") as stream:
            written = stream.write(line)
            stream.flush(); os.fsync(stream.fileno())
            if written != len(line):
                raise OSError("Incomplete audit append")

    def record_attempt(self, event):
        item, raw = _payload(event)
        if item.eventType != "http_attempt":
            raise ValueError("Only attempts may use separate persistence")
        with self._io_lock:
            conn = None
            try:
                conn = self.connect()
                conn.execute("BEGIN IMMEDIATE")
                _insert(conn, item, raw)
                conn.commit()
                return AuditWriteResult("db", item.eventId, True)
            except AuditConflict:
                try:
                    conn.rollback()  # Release its write lock before a gap-marker transaction.
                except Exception:
                    pass
                with self._lock:
                    self._permanent_gap = True; self._dropped += 1
                self._persist_gap()
                return AuditWriteResult("dropped", item.eventId, False)
            except Exception:
                if conn is not None:
                    try:
                        conn.rollback()
                    except Exception:
                        pass
            finally:
                if conn is not None:
                    try:
                        conn.close()
                    except Exception:
                        pass  # Confirmed commit stays committed; failure still falls back.
            line = (raw + "\n").encode()
            with self._lock:
                previous = self._fallback_ids.get(item.eventId)
                if previous == raw:
                    return AuditWriteResult("fallback", item.eventId, True)
                dirty_tail = bool(self._lines and not self._lines[-1].endswith(b"\n"))
                full = self._opaque_file or dirty_tail or previous is not None or len(self._lines) >= self._count_limit or self._fallback_bytes + len(line) > self._byte_limit
            if full:
                result = self._unpersisted(item, raw, permanent=True)
                self._persist_gap()
                return result
            try:
                self._append_fallback(line)
                with self._lock:
                    self._lines.append(line); self._fallback_ids[item.eventId] = raw
                    self._fallback_bytes += len(line)
                return AuditWriteResult("fallback", item.eventId, True)
            except Exception:
                # Partial native writes are not safe append positions. Reload the
                # bounded file before another writer is admitted.
                with self._lock:
                    self._lines, self._fallback_ids = [], {}
                self._load_fallback()
                result = self._unpersisted(item, raw)
                self._persist_gap()
                return result

    def _replace_fallback(self, lines):
        temp = self.fallback_path.with_name("audit-fallback-" + str(uuid4()) + ".tmp")
        try:
            with temp.open("xb") as stream:
                stream.write(b"".join(lines)); stream.flush(); os.fsync(stream.fileno())
            os.replace(temp, self.fallback_path)
        finally:
            temp.unlink(missing_ok=True)

    def recover_fallback(self):
        with self._io_lock:
            with self._lock:
                # An opaque file remains untouched, but independently validated
                # admission-overflow RAM can still use a healthy database.
                lines = [] if self._opaque_file else list(self._lines)
                memory = list(self._memory.items())
            kept, recovered, duplicates, conflicts = [], 0, 0, 0
            unavailable = False
            for index, line in enumerate(lines):
                conn = None
                try:
                    if not line.endswith(b"\n"):
                        raise ValueError("Partial audit line")
                    item, raw = _payload(AuditEvent.model_validate_json(line))
                    if item.eventType != "http_attempt":
                        raise ValueError("Unexpected fallback type")
                    conn = self.connect(); conn.execute("BEGIN IMMEDIATE")
                    inserted = _insert(conn, item, raw)
                    conn.commit()  # Must precede removing even an exact duplicate.
                    recovered += int(inserted); duplicates += int(not inserted)
                except AuditConflict:
                    conflicts += 1; kept.append(line)
                    with self._lock:
                        self._permanent_gap = True
                except Exception as error:
                    kept.append(line)
                    if isinstance(error, ValueError):
                        with self._lock:
                            self._permanent_gap = True
                    else:
                        unavailable = True
                finally:
                    if conn is not None:
                        try:
                            conn.rollback()
                        except Exception:
                            pass
                        try:
                            conn.close()
                        except Exception:
                            pass
                if unavailable:
                    kept.extend(lines[index + 1:])
                    break  # One database fault, not 1000 successive busy waits.
            cleanup_failed = False
            if kept != lines:
                try:
                    self._replace_fallback(kept)
                    with self._lock:
                        self._lines = kept
                        self._fallback_bytes = sum(len(line) for line in kept)
                        self._fallback_ids = {}
                        for line in kept:
                            try:
                                item, raw = _payload(AuditEvent.model_validate_json(line))
                                self._fallback_ids[item.eventId] = raw
                            except Exception:
                                pass
                except Exception:
                    cleanup_failed = True
            # Memory is retried only during bounded explicit recovery/shutdown.
            for event_id, raw in memory:
                if unavailable:
                    break
                result = self.record_attempt(AuditEvent.model_validate_json(raw))
                if result.persisted:
                    with self._lock:
                        self._memory.pop(event_id, None)
                        self._memory_bytes -= len(raw.encode()) + 1
                else:
                    break  # One unavailable sink, not a busy wait per RAM item.
            self._persist_gap()
            with self._lock:
                remaining = (max(1, len(self._lines)) if self._opaque_file else len(self._lines)) + len(self._memory)
            return RecoveryReport(recovered, duplicates, conflicts, remaining, cleanup_failed)

    def _start_owned_io(self, operation, *, failed_attempt=None):
        """The admitted worker owns terminal faults even after its waiter left."""
        def worker():
            try:
                return operation()
            except Exception:
                # Never rethrow filesystem/provider text to a waiter or asyncio.
                # All native recovery/marker I/O remains inside this actual slot.
                with self._lock:
                    self._permanent_gap = True
                result = None
                if failed_attempt is not None:
                    item, raw = failed_attempt
                    result = self._unpersisted(item, raw, permanent=True)
                try:
                    self._persist_gap()
                except Exception:
                    pass
                return result
            finally:
                with self._lock:
                    self._active -= 1
        task = asyncio.create_task(asyncio.to_thread(worker))
        with self._lock:
            self._tasks.add(task)
        def done(completed):
            with self._lock:
                self._tasks.discard(completed)
            if completed.cancelled() or completed.exception() is not None:
                # Last-resort ownership (e.g. loop teardown/BaseException), no
                # synchronous disk I/O or raw exception logging in this callback.
                with self._lock:
                    self._permanent_gap = True
        task.add_done_callback(done)
        return task

    async def _run_io(self, operation, *, wait_ms, failed_attempt=None):
        with self._lock:
            if self._closed or self._active >= 8:
                return _BUSY
            self._active += 1
        task = self._start_owned_io(operation, failed_attempt=failed_attempt)
        try:
            return await asyncio.wait_for(asyncio.shield(task), min(500, max(0, wait_ms)) / 1000)
        except asyncio.TimeoutError:
            return _PENDING

    async def save_attempt(self, event, *, wait_ms=500):
        item, raw = _payload(event)
        if item.eventType != "http_attempt":
            raise ValueError("Attempt required")
        result = await self._run_io(lambda: self.record_attempt(item), wait_ms=wait_ms, failed_attempt=(item, raw))
        if result is _PENDING:
            return AuditWriteResult("pending", item.eventId, False)
        if result is _BUSY:
            with self._lock:
                closed = self._closed
            if closed:
                self.note_failure(item.eventId)
                return AuditWriteResult("dropped", item.eventId, False)
            return self._unpersisted(item, raw)
        return result

    async def recover(self, *, wait_ms=500):
        result = await self._run_io(self.recover_fallback, wait_ms=wait_ms)
        return None if result is _PENDING or result is _BUSY else result

    async def close(self, *, wait_seconds=2):
        deadline = self.clock() + min(2, max(0, wait_seconds))
        with self._lock:
            self._closed = True
            tasks = set(self._tasks)
        if tasks:
            await asyncio.wait(tasks, timeout=max(0, deadline - self.clock()))
        with self._lock:
            residual = self._active
            needs_recovery = bool(self._memory or self._lines or self._permanent_gap)
        if not residual and needs_recovery and self.clock() < deadline:
            with self._lock:
                self._active += 1
            task = self._start_owned_io(self.recover_fallback)
            await asyncio.wait({task}, timeout=max(0, deadline - self.clock()))
        with self._lock:
            return {"residualJobs": self._active, "unpersistedCount": len(self._memory),
                "permanentGap": self._permanent_gap}
