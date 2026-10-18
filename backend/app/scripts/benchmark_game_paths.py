"""Owned synthetic HTTP rule paths and persisted growth, not online latency.

Import is inert; no external paths/settings/providers/CLI args are accepted.
"""
from contextlib import closing
import json
import os
from pathlib import Path
import platform
import sqlite3
from tempfile import TemporaryDirectory
import time
import tracemalloc
from uuid import UUID, uuid4

from fastapi.testclient import TestClient

from app import db
from app.audit_events import AuditEvent
from app.config import Settings
from app.main import create_app
from app.runtime import runtime_context
from app.schemas import Checkpoint, DifficultyLimits, Soup
from app.scripts.benchmark_metrics import nearest_rank
from app.testing import FakeModel


def _disk(directory):
    database = directory / "sessions.db"
    wal = directory / "sessions.db-wal"
    traces = tuple((directory / "traces").glob("*.jsonl"))
    return {"dbFileBytes": database.stat().st_size if database.exists() else 0,
        "walFileBytes": wal.stat().st_size if wal.exists() else 0,
        "traceBytes": sum(path.stat().st_size for path in traces)}


def _audit_bytes(runtime):
    with runtime_context(runtime), closing(db._connect()) as conn:
        return conn.execute("SELECT coalesce(sum(length(cast(details_json AS BLOB))),0) FROM audit_events").fetchone()[0]


def _sample(client, runtime, model, name, ordinal):
    created = client.post("/api/chat", json={"soupId": "synthetic-path-benchmark", "level": "tianyi", "requestId": str(uuid4())})
    if created.status_code != 200:
        raise ValueError("Synthetic session creation failed")
    sid = created.json()["sessionId"]
    if str(UUID(sid)) != sid:
        raise ValueError("Unexpected synthetic session identity")
    calls_before = len(model.calls)
    started = time.perf_counter()
    response = client.post("/api/chat", json={"sessionId": sid, "requestId": str(uuid4()),
        "question": "小明是凶手吗？" if name == "ruleHit" else "他是凶手吗？"})
    elapsed = (time.perf_counter() - started) * 1000
    if response.status_code != 200:
        raise ValueError("Synthetic ask failed")
    reply = response.json()
    model_calls = len(model.calls) - calls_before
    expected_source, expected_calls = ("deterministic", 0) if name == "ruleHit" else ("llm", 1)
    rows = (runtime.settings.DATA_DIR / "traces" / (sid + ".jsonl")).read_text(encoding="utf-8").splitlines()
    if len(rows) != 1:
        raise ValueError("Missing or duplicate actual turn trace")
    trace = json.loads(rows[0])
    with runtime_context(runtime), closing(db._connect()) as conn:
        events = list(conn.execute("SELECT details_json FROM audit_events WHERE event_type='turn_committed' AND turn_id=?",
            (reply["turnId"],)))
        session = conn.execute("SELECT questions_asked FROM sessions WHERE id=?", (sid,)).fetchone()
    if len(events) != 1:
        raise ValueError("Missing committed turn evidence")
    event = AuditEvent.model_validate_json(events[0][0])
    if (reply["kind"] != "answer" or reply["state"] != "completed" or reply["isFreeReminder"] is not False
        or session[0] != 1 or model_calls != expected_calls
        or (trace["kind"], trace["source"], trace["chargeable"]) != ("answer", expected_source, True)
        or (event.details.kind, event.details.source, event.details.charged) != ("answer", expected_source, True)
        or event.sessionId != sid or event.details.versions.model_dump(mode="json") != trace["versions"]):
        raise ValueError("Actual measured path does not match its claimed scope")
    return {"ordinal": ordinal, "elapsedMs": elapsed, "source": event.details.source,
        "modelCalls": model_calls, "kind": event.details.kind, "charged": event.details.charged, "statusCode": response.status_code}


def _workload(runtime):
    with runtime_context(runtime), closing(db._connect()) as conn:
        counts = {"sessions": conn.execute("SELECT count(*) FROM sessions").fetchone()[0],
            "turns": conn.execute("SELECT count(*) FROM turns").fetchone()[0],
            "messages": conn.execute("SELECT count(*) FROM messages").fetchone()[0],
            "charged": conn.execute("SELECT coalesce(sum(questions_asked),0) FROM sessions").fetchone()[0],
            "auditEvents": conn.execute("SELECT count(*) FROM audit_events").fetchone()[0]}
        for name, kind in (("sessionCreatedEvents", "session_created"), ("turnCommittedEvents", "turn_committed"), ("httpAttempts", "http_attempt")):
            counts[name] = conn.execute("SELECT count(*) FROM audit_events WHERE event_type=?", (kind,)).fetchone()[0]
    traces = tuple((runtime.settings.DATA_DIR / "traces").glob("*.jsonl"))
    counts.update(traceFiles=len(traces), traceLines=sum(len(path.read_text(encoding="utf-8").splitlines()) for path in traces))
    return counts


def measure_game_paths(*, warmups=3, samples=20):
    if type(warmups) is not int or not 0 <= warmups <= 10 or type(samples) is not int or not 1 <= samples <= 100:
        raise ValueError("Bounded integer warmups/samples required")
    report = {"schemaVersion": 1, "evidenceKind": "declared_synthetic_benchmark", "warmups": warmups, "samples": samples,
        "measurementScope": "in_process_http_turn_persistence_audit_trace", "comparisonBeforeUpgrade": None, "realProviderLatency": None,
        "environment": {"python": platform.python_version(), "sqlite": sqlite3.sqlite_version,
            "platform": platform.platform(), "logicalCpuCount": os.cpu_count()},
        "limitations": ["Synthetic checkpoints/FakeModel, NOT genuine model or human quality",
            "In-process TestClient POSTask includes persistence/audit/trace, session creation excluded",
            "Rule hit is warm runtime cache; miss is new-session contextual FakeModel",
            "Tracemalloc instrumented, Python allocated peak NOT RSS; no matching old-upgrade/SLA/provider evidence"]}
    trace_owned = not tracemalloc.is_tracing()
    if trace_owned:
        tracemalloc.start()
    started_cpu = time.process_time()
    runtime, owned_path, measured, attempted = None, None, {}, []
    def sample(client, runtime, model, name, ordinal, phase):
        try:
            result = _sample(client, runtime, model, name, ordinal)
        except Exception:
            attempted.append({"path": name, "phase": phase, "ordinal": ordinal, "outcome": "failed",
                "code": "game_path_benchmark_failed", "elapsedMs": None})
            raise
        attempted.append({"path": name, "phase": phase, "outcome": "passed", **result})
        return result
    try:
        with TemporaryDirectory(prefix="turtle-game-path-benchmark-") as temporary:
            owned_path = Path(temporary)
            soup = Soup(id="synthetic-path-benchmark", title="合成测量", surface="小明和小红。", bottom="自行编写的合成事实：小明是凶手。",
                source="synthetic_demo", checkpoints=[Checkpoint(key="小明是凶手", answer=True)],
                difficultyLimits=DifficultyLimits(xuermu=4, baozi=4, tianyi=4))
            model = FakeModel("是")
            app = create_app(Settings.for_test(owned_path, ENABLE_TRACE=True), model=model, soups=[soup])
            try:
                with TestClient(app, raise_server_exceptions=False) as client:
                    runtime = app.state.runtime
                    before_disk, before_audit = _disk(owned_path), _audit_bytes(runtime)
                    for name in ("ruleHit", "ruleMiss"):
                        for ordinal in range(warmups):
                            sample(client, runtime, model, name, ordinal, "warmup")
                        records = [sample(client, runtime, model, name, ordinal, "measured") for ordinal in range(samples)]
                        measured[name] = {"records": records, "p50Ms": nearest_rank([row["elapsedMs"] for row in records], 0.5),
                            "p95Ms": nearest_rank([row["elapsedMs"] for row in records], 0.95), "errorRate": 0}
                    workload = _workload(runtime)
                    total = 2 * (warmups + samples)
                    expected = {"sessions": total, "turns": total, "messages": total * 2, "charged": total,
                        "auditEvents": total * 4, "sessionCreatedEvents": total, "turnCommittedEvents": total,
                        "httpAttempts": total * 2, "traceFiles": total, "traceLines": total}
                    if workload != expected or len(model.calls) != warmups + samples:
                        raise ValueError("Measured workload completeness mismatch")
                    after_disk = _disk(owned_path)
                    growth = {name: after_disk[name] - before_disk[name] for name in before_disk}
                    growth["auditJsonBytes"] = _audit_bytes(runtime) - before_audit
                    if growth["traceBytes"] <= 0 or growth["auditJsonBytes"] <= 0:
                        raise ValueError("Missing actual audit/trace growth")
                    measured.update(workload=workload, modelCalls=len(model.calls), growth=growth,
                        diskBefore=before_disk, diskAfter=after_disk)
            finally:
                runtime = app.state.runtime
            final_disk = _disk(owned_path)
            measured["resources"] = {"dbFileBytes": final_disk["dbFileBytes"], "walFileBytes": final_disk["walFileBytes"],
                "cpuMilliseconds": (time.process_time() - started_cpu) * 1000,
                "pythonAllocatedPeakBytes": tracemalloc.get_traced_memory()[1],
                "allocationScope": "owned_run" if trace_owned else "existing_process_trace_peak"}
        report.update(status="complete", **measured)
    except Exception:
        report.update(status="failed", failureCode="game_path_benchmark_failed")
    finally:
        if trace_owned:
            tracemalloc.stop()
        model_active = runtime.model_gateway.snapshot()["active"] if runtime is not None and runtime.model_gateway is not None else 0
        audit = runtime.audit_shutdown if runtime is not None else None
        shutdown = {"runtimeClosed": runtime is not None and runtime.closed, "modelActive": model_active,
            "auditResidualJobs": audit["residualJobs"] if audit is not None else None,
            "auditUnpersisted": audit["unpersistedCount"] if audit is not None else None,
            "auditPermanentGap": audit["permanentGap"] if audit is not None else None,
            "temporaryDirectoryRemoved": owned_path is not None and not owned_path.exists()}
        report["shutdown"] = shutdown
        report["attemptedRecords"] = attempted
        report["cleanupConfirmed"] = (shutdown["runtimeClosed"] and model_active == 0 and shutdown["auditResidualJobs"] == 0
            and shutdown["auditUnpersisted"] == 0 and shutdown["auditPermanentGap"] is False and shutdown["temporaryDirectoryRemoved"])
        if not report["cleanupConfirmed"]:
            report = {key: value for key, value in report.items() if key not in {"ruleHit", "ruleMiss"}}
            report.update(status="failed", failureCode="game_path_benchmark_cleanup_failed")
    return report


if __name__ == "__main__":
    import sys
    if len(sys.argv) != 1:
        raise SystemExit("No arguments or external paths are accepted")
    output = measure_game_paths()
    print(json.dumps(output, ensure_ascii=False, allow_nan=False))
    raise SystemExit(0 if output["status"] == "complete" else 1)
