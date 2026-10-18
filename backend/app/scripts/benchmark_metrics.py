"""Owned synthetic metrics measurement; never production traffic or capacity proof.

Run with ``python -m app.scripts.benchmark_metrics``. No user database paths,
provider credentials, network calls or output-overwrite options are accepted.
The identical SQL batch comparison is NOT an old-schema reader benchmark.
"""
import asyncio
from contextlib import closing
import json
import math
import os
from pathlib import Path
import platform
import sqlite3
from tempfile import TemporaryDirectory
import time
import tracemalloc
from types import SimpleNamespace
from unittest.mock import patch
from uuid import uuid4

from app import baselines, metrics, migrations
from app.audit_events import AuditEvent, AttemptDetails
from app.config import Settings
from app.metrics_contracts import MetricsCounts, MetricsError, MetricsPage, MetricsQuery, MetricsSummary
from app.runtime import Runtime
from app.schemas import HOST_ENGINE_VERSION, Soup


def nearest_rank(values, probability):
    if (not values or isinstance(probability, bool) or not isinstance(probability, (int, float))
        or not math.isfinite(probability) or not 0 < probability <= 1
        or any(isinstance(value, bool) or not isinstance(value, (int, float))
            or not math.isfinite(value) or value < 0 for value in values)):
        raise ValueError("Finite nonnegative samples and a probability in (0,1] are required")
    return sorted(values)[math.ceil(len(values) * probability) - 1]


def _seed(path, soups):
    """Statistical rows only: these are not 1000 game/store executions."""
    with closing(sqlite3.connect(path)) as conn:
        conn.row_factory = sqlite3.Row
        conn.execute("PRAGMA foreign_keys=ON")
        conn.execute("PRAGMA journal_mode=WAL")
        migrations.migrate(conn, soups, target_version=4)
        versions = baselines.active_manifest(conn)
        window_start = float(math.ceil(time.time()))
        traffic = ("real", "test", "synthetic", "legacy")
        attempt_traffic = traffic + (None,)
        sessions = [str(uuid4()) for _ in range(200)]
        conn.executemany("INSERT INTO sessions(id,soup_id,created_at,puzzle_version,rule_version,compat_state,traffic_class) VALUES(?,?,?,?,?,'compatible',?)",
            [(session, soups[index % 4].id, window_start + 100 + (index // 4 % 27) * 86400,
                versions["puzzleVersions"][soups[index % 4].id], versions["ruleVersion"], traffic[index % 4])
                for index, session in enumerate(sessions)])
        kinds = ("answer", "reminder", "system_error", "win", "answer")
        conn.executemany("INSERT INTO turns(id,session_id,request_id,payload_hash,question,state,kind,charged,puzzle_version,rule_version,engine_version,created_at,completed_at) VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?)",
            [(str(uuid4()), sessions[index % 200], str(uuid4()), "synthetic-volume", "Synthetic benchmark question?",
                "failed" if kinds[index % 5] == "system_error" else "completed", kinds[index % 5],
                int(kinds[index % 5] in ("answer", "win")),
                versions["puzzleVersions"][soups[index % 4].id], versions["ruleVersion"], HOST_ENGINE_VERSION,
                window_start + 1000 + index, window_start + 1001 + index) for index in range(1000)])
        attempts = []
        for index in range(5000):
            item = AuditEvent(eventId=str(uuid4()), eventType="http_attempt", createdAt=window_start + 1000 + index,
                details=AttemptDetails(method="GET", routeTemplate="/health", statusCode=200, durationMs=1.0,
                    outcome="success", responseStarted=True, disconnected=False, trafficClass=attempt_traffic[index % 5]))
            attempts.append((item.eventId, item.model_dump_json(), item.createdAt))
        conn.executemany("INSERT INTO audit_events(id,event_type,details_json,created_at) VALUES(?,'http_attempt',?,?)", attempts)
        conn.commit()
        rows = {name: conn.execute(f"SELECT count(*) FROM {table}").fetchone()[0]
            for name, table in (("sessions", "sessions"), ("turns", "turns"), ("auditEvents", "audit_events"))}
        if rows != {"sessions": 200, "turns": 1000, "auditEvents": 5000}:
            raise ValueError("Incorrect owned fixture scale")
        # Independently inspect stored source rows, not the reader's SQL/summary.
        counts = {}
        for classification in (*traffic, 'unknown'):
            counts[classification] = MetricsCounts(
                sessionsCreated=conn.execute("SELECT count(*) FROM sessions WHERE traffic_class=?", (classification,)).fetchone()[0],
                successfulChargedTurns=conn.execute("SELECT count(*) FROM turns t JOIN sessions s ON s.id=t.session_id WHERE s.traffic_class=? AND t.state='completed' AND t.charged=1 AND t.kind IN ('answer','win')", (classification,)).fetchone()[0],
                httpAttempts=conn.execute("SELECT count(*) FROM audit_events WHERE json_extract(details_json,'$.details.trafficClass') IS ?",
                    (None if classification == 'unknown' else classification,)).fetchone()[0])
            if counts[classification] != MetricsCounts(sessionsCreated=0 if classification == 'unknown' else 50,
                    successfulChargedTurns=0 if classification == 'unknown' else 150, httpAttempts=1000):
                raise ValueError("Incorrect owned fixture classifications")
        expected = MetricsSummary(counts=counts["real"], excluded={name: counts[name] for name in (*traffic[1:], 'unknown')},
            unscopedReal=MetricsCounts(httpAttempts=1000),
            postPublicationRegression={'state': 'unknown', 'observedRuns': None,
                'failedRuns': None, 'reason': 'schema_5_required'})
        return rows, expected.model_dump(mode="json"), window_start


def _profile(call, warmups, samples, kind):
    for _ in range(warmups):
        call()
    observed = []
    for _ in range(samples):
        started = time.perf_counter()
        call()
        observed.append((time.perf_counter() - started) * 1000)
    return {"comparisonKind": kind, "samplesMs": observed,
        "p50Ms": nearest_rank(observed, 0.5), "p95Ms": nearest_rank(observed, 0.95)}


def _batch(path, statements, warmups, samples):
    # Fresh prepared statements after every schema change; all results consumed.
    with closing(sqlite3.connect(path, cached_statements=0)) as conn:
        conn.execute("PRAGMA query_only=ON")
        plans = [str(tuple(row)) for sql, parameters in statements
            for row in conn.execute("EXPLAIN QUERY PLAN " + sql, parameters)]

        def read():
            deadline = time.monotonic() + 3.0
            conn.set_progress_handler(lambda: int(time.monotonic() >= deadline), 1000)
            try:
                conn.execute("BEGIN")
                for sql, parameters in statements:
                    conn.execute(sql, parameters).fetchall()
                if time.monotonic() >= deadline:
                    raise MetricsError("metrics_busy", 503)
            finally:
                conn.set_progress_handler(None, 0)
                conn.rollback()

        return _profile(read, warmups, samples, "same_statement_batch_not_reader"), plans


def _measure_owned(path, warmups, samples):
    soups = [Soup(id=f"benchmark-{index}", title="Synthetic", surface="Synthetic surface", bottom="Synthetic truth",
        checkpoints=[{"key": "fact", "answer": True}], confusionPoints=[{"q": "Synthetic?", "a": "是"}]) for index in range(4)]
    runtime = Runtime(Settings.for_test(path.parent), soups=soups)
    try:
        rows, expected, window_start = _seed(path, soups)
        query = MetricsQuery(start=window_start, end=window_start + 31 * 86400.0, limit=100)
        statements = []
        original_connect = sqlite3.connect

        class Observer(metrics._DeadlineConnection):
            def execute(self, sql, parameters=()):
                if sql in (metrics._SUMMARY_SQL, metrics._GROUP_SQL):
                    statements.append((sql, dict(parameters)))
                return super().execute(sql, parameters)

        def connect(*args, **kwargs):
            kwargs["factory"] = Observer
            return original_connect(*args, **kwargs)

        # This standalone/offline process observes the real reader, without
        # changing sqlite3.connect globally or adding test hooks to the reader.
        facade = SimpleNamespace(**{**vars(sqlite3), "connect": connect})
        with patch.object(metrics, "sqlite3", facade):
            initial_page = metrics.query_metrics(runtime, query)
            actual = initial_page.summary.model_dump(mode="json")
        if actual != expected or len(statements) != 2:
            raise ValueError("Actual reader disagrees with independent source counts/batch")
        with closing(original_connect(path)) as conn:
            for name in migrations._METRICS_INDEX_NAMES:
                conn.execute(f"DROP INDEX {name}")
            conn.commit()
        before, plans_before = _batch(path, statements, warmups, samples)
        with closing(original_connect(path)) as conn:
            conn.row_factory = sqlite3.Row
            for sql in migrations.METRICS_SQL:
                conn.execute(sql)
            conn.commit()
            migrations.verify_schema(conn, required_version=4)
        after, plans_after = _batch(path, statements, warmups, samples)

        serialized_sizes = []

        def read():
            page = metrics.query_metrics(runtime, query)
            encoded = page.model_dump_json()
            decoded = MetricsPage.model_validate_json(encoded)
            if decoded != page or decoded.summary.model_dump(mode="json") != expected:
                raise ValueError("Measured reader changed its counts")
            serialized_sizes.append(len(encoded.encode('utf-8')))

        reader = _profile(read, warmups, samples, "end_to_end_reader")
        reader.update(serializationIncluded=True, serializedBytes=serialized_sizes[warmups:],
            measurementScope='snapshot_schema_catalog_aggregates_full_json_serialization_and_roundtrip')
        return {"inputRows": rows, "expectedSummary": expected, "actualSummary": actual,
            "aggregateStatementCount": len(statements), "reader": reader,
            "sqlBatchBeforeIndexes": before, "sqlBatchAfterIndexes": after,
            "plansBeforeIndexes": plans_before, "plansAfterIndexes": plans_after,
            "query": query.model_dump(mode="json"), "coverage": initial_page.coverage.model_dump(mode='json'),
            "fixtureClockStrategy": 'declared_synthetic_rows_after_actual_migration_coverage',
            "trafficClasses": ['real', 'test', 'synthetic', 'legacy', 'unknown']}
    finally:
        asyncio.run(runtime.aclose())


def measure_metrics(*, warmups=3, samples=20):
    if type(warmups) is not int or not 0 <= warmups <= 10 or type(samples) is not int or not 1 <= samples <= 100:
        raise ValueError("Bounded integer warmups/samples required")
    result = {"schemaVersion": 1, "evidenceKind": "declared_synthetic_benchmark", "warmups": warmups, "samples": samples,
        "environment": {"python": platform.python_version(), "sqlite": sqlite3.sqlite_version,
            "platform": platform.platform(), "logicalCpuCount": os.cpu_count()},
        "limitations": ["Statistical synthetic rows, not real users or model accuracy",
            "SQL batch before/after is not an old-reader comparison",
            "Local Python allocation peak is not RSS, production capacity or an SLA",
            "Timings include tracemalloc instrumentation; not uninstrumented latency"]}
    trace_owned = not tracemalloc.is_tracing()
    started_cpu = time.process_time()
    if trace_owned:
        tracemalloc.start()
    owned_path = None
    try:
        with TemporaryDirectory(prefix="turtle-metrics-benchmark-") as temporary:
            owned_path = Path(temporary)
            db_path = owned_path / "sessions.db"
            measured = _measure_owned(db_path, warmups, samples)
            resources = {"cpuMilliseconds": (time.process_time() - started_cpu) * 1000,
                "pythonAllocatedPeakBytes": tracemalloc.get_traced_memory()[1],
                "allocationScope": "owned_run" if trace_owned else "existing_process_trace_peak",
                "dbFileBytes": db_path.stat().st_size,
                "walFileBytes": Path(str(db_path) + "-wal").stat().st_size if Path(str(db_path) + "-wal").exists() else 0}
        result.update(status="complete", **measured, resources=resources)
    except MetricsError as error:
        result.update(status="failed", failureCode=error.code)
    except Exception:
        # A failed measurement has no successful/partial quantiles or raw error.
        result.update(status="failed", failureCode="metrics_benchmark_failed")
    finally:
        if trace_owned:
            tracemalloc.stop()
        result["cleanupConfirmed"] = owned_path is not None and not owned_path.exists()
    return result


if __name__ == "__main__":
    import sys
    if len(sys.argv) != 1:
        raise SystemExit("No database paths or other arguments are accepted")
    report = measure_metrics()
    print(json.dumps(report, ensure_ascii=False, allow_nan=False))
    raise SystemExit(0 if report["status"] == "complete" else 1)
