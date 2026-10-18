"""Actual synthetic HTTP work; timings and growth are observations, not an SLA."""
import importlib
import json
import math
from pathlib import Path
import subprocess
import sys

import pytest


def benchmark():
    try:
        return importlib.import_module("app.scripts.benchmark_game_paths")
    except ModuleNotFoundError as error:
        if error.name == "app.scripts.benchmark_game_paths":
            pytest.fail("TS17 D25 game path benchmark is not implemented")
        raise


def assert_complete(report, warmups=3, samples=20):
    assert report["status"] == "complete" and report["evidenceKind"] == "declared_synthetic_benchmark"
    assert (report["warmups"], report["samples"]) == (warmups, samples)
    total = 2 * (warmups + samples)
    assert report["workload"] == {"sessions": total, "turns": total, "messages": total * 2, "charged": total,
        "auditEvents": total * 4, "sessionCreatedEvents": total, "turnCommittedEvents": total,
        "httpAttempts": total * 2, "traceFiles": total, "traceLines": total}
    for name, source, calls in (("ruleHit", "deterministic", 0), ("ruleMiss", "llm", 1)):
        measured = report[name]
        rows = measured["records"]
        assert len(rows) == samples and [row["ordinal"] for row in rows] == list(range(samples))
        assert all(row["source"] == source and row["modelCalls"] == calls and row["kind"] == "answer"
            and row["charged"] and row["statusCode"] == 200 for row in rows)
        values = sorted(row["elapsedMs"] for row in rows)
        assert all(math.isfinite(value) and value >= 0 for value in values)
        assert measured["p50Ms"] == values[math.ceil(samples * 0.5) - 1]
        assert measured["p95Ms"] == values[math.ceil(samples * 0.95) - 1]
        assert measured["errorRate"] == 0
    assert report["modelCalls"] == warmups + samples
    assert report["growth"]["traceBytes"] > 0 and report["growth"]["auditJsonBytes"] > 0
    assert report["resources"]["dbFileBytes"] > 0 and report["resources"]["walFileBytes"] >= 0
    assert report["resources"]["cpuMilliseconds"] >= 0 and report["resources"]["pythonAllocatedPeakBytes"] >= 0
    assert report["cleanupConfirmed"] is True and report["shutdown"] == {
        "runtimeClosed": True, "modelActive": 0, "auditResidualJobs": 0, "auditUnpersisted": 0,
        "auditPermanentGap": False, "temporaryDirectoryRemoved": True}
    assert report["comparisonBeforeUpgrade"] is None and report["realProviderLatency"] is None


def test_actual_rule_hit_miss_all_twenty_samples_and_native_workload_growth():
    assert_complete(benchmark().measure_game_paths())


def test_bounded_smaller_measurement_still_executes_real_both_paths():
    assert_complete(benchmark().measure_game_paths(warmups=0, samples=1), 0, 1)


@pytest.mark.parametrize("options", [{"warmups": True}, {"warmups": -1}, {"warmups": 11},
    {"samples": True}, {"samples": 0}, {"samples": 101}, {"samples": 1.5}])
def test_measurement_rejects_unbounded_or_boolean_inputs(options):
    with pytest.raises(ValueError):
        benchmark().measure_game_paths(**options)


def test_failed_measurement_keeps_real_lifespan_cleanup_and_no_success_quantiles(monkeypatch):
    measure = benchmark()
    def fail(*args, **kwargs):
        raise RuntimeError("PRIVATE_SYNTHETIC_BENCHMARK_ERROR")
    monkeypatch.setattr(measure, "_sample", fail)
    report = measure.measure_game_paths(warmups=0, samples=1)
    assert report["status"] == "failed" and report["failureCode"] == "game_path_benchmark_failed"
    assert report["cleanupConfirmed"] is True
    assert report["shutdown"]["runtimeClosed"] is True and report["shutdown"]["auditResidualJobs"] == 0
    assert all(value not in json.dumps(report) for value in ("PRIVATE", "p50Ms", "p95Ms"))
    assert "ruleHit" not in report and "ruleMiss" not in report


def test_late_failed_sample_retains_prior_raw_work_without_success_quantiles(monkeypatch):
    measure = benchmark()
    real_sample = measure._sample
    def sample(client, runtime, model, name, ordinal):
        if name == "ruleMiss":
            raise RuntimeError("PRIVATE_LATE_SAMPLE_FAILURE")
        return real_sample(client, runtime, model, name, ordinal)
    monkeypatch.setattr(measure, "_sample", sample)
    report = measure.measure_game_paths(warmups=0, samples=1)
    assert report["status"] == "failed" and report["cleanupConfirmed"] is True
    records = report["attemptedRecords"]
    assert len(records) == 2
    assert records[0]["path"] == "ruleHit" and records[0]["outcome"] == "passed" and records[0]["modelCalls"] == 0
    assert records[1] == {"path": "ruleMiss", "phase": "measured", "ordinal": 0, "outcome": "failed",
        "code": "game_path_benchmark_failed", "elapsedMs": None}
    assert "p50Ms" not in json.dumps(report) and "PRIVATE" not in json.dumps(report)


def test_game_path_cli_executes_real_default_workload():
    benchmark()
    child = subprocess.run([sys.executable, "-m", "app.scripts.benchmark_game_paths"],
        cwd=Path(__file__).resolve().parents[2], capture_output=True, text=True, timeout=30)
    assert child.returncode == 0, child.stderr
    assert_complete(json.loads(child.stdout))


def test_game_path_cli_rejects_external_paths_without_printing_them():
    benchmark()
    child = subprocess.run([sys.executable, "-m", "app.scripts.benchmark_game_paths", "PRIVATE_OUTSIDE_PATH"],
        cwd=Path(__file__).resolve().parents[2], capture_output=True, text=True, timeout=10)
    assert child.returncode != 0 and child.stdout == "" and "PRIVATE" not in child.stderr
