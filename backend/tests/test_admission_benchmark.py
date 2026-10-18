"""Synthetic100 drivers, actual gateway ownership; not100 concurrent website users."""
import importlib
import json
import math
from pathlib import Path
import subprocess
import sys

import pytest


def benchmark():
    try:
        return importlib.import_module("app.scripts.benchmark_admission")
    except ModuleNotFoundError as error:
        if error.name == "app.scripts.benchmark_admission":
            pytest.fail("TS17 D25 admission benchmark is not implemented")
        raise


def assert_complete(report):
    assert report["status"] == "complete"
    assert report["evidenceKind"] == "declared_synthetic_benchmark"
    assert report["measurementScope"] == "model_gateway_admission_controlled_hold"
    assert report["applicants"] == 100
    assert report["initialAdmission"] == {"accepted": 2, "queued": 32, "rejected": 66}
    assert report["outcomes"] == {"admitted": 34, "rejected": 66, "failed": 0}
    assert report["peaks"] == {"activeOwners": 2, "waitingOnline": 32}
    assert report["transport"] == {"started": 34, "closed": 34}
    rows = report["records"]
    assert len(rows) == 100 and sorted(row["ordinal"] for row in rows) == list(range(100))
    assert all(math.isfinite(row["elapsedMs"]) and row["elapsedMs"] >= 0 for row in rows)
    for outcome, amount in (("admitted", 34), ("rejected", 66)):
        values = sorted(row["elapsedMs"] for row in rows if row["outcome"] == outcome)
        assert len(values) == amount
        assert report["timings"][outcome]["p50Ms"] == values[math.ceil(amount * 0.5) - 1]
        assert report["timings"][outcome]["p95Ms"] == values[math.ceil(amount * 0.95) - 1]
    assert all(row["code"] == ("passed" if row["outcome"] == "admitted" else "model_busy") for row in rows)
    assert report["cleanupConfirmed"] is True
    assert report["finalGateway"]["closed"] is True
    assert report["finalGateway"]["active"] == report["finalGateway"]["waiting_online"] == 0
    assert report["resources"]["cpuMilliseconds"] >= 0
    assert report["resources"]["pythonAllocatedPeakBytes"] >= 0
    assert report["comparisonBeforeUpgrade"] is None and report["realProviderLatency"] is None


def test_actual100_gateway_applicants_preserve_all_outcomes_and_cleanup():
    assert_complete(benchmark().measure_admission())


def test_failed_caller_batch_never_gets_quantiles_and_does_not_leak_raw_error(monkeypatch):
    measure = benchmark()
    from app.model_gateway import ModelGateway
    def fail(*args, **kwargs):
        raise RuntimeError("PRIVATE_FAKE_PROVIDER_FAILURE")
    monkeypatch.setattr(ModelGateway, "invoke", fail)
    report = measure.measure_admission()
    assert report["status"] == "failed" and report["failureCode"] == "admission_benchmark_failed"
    assert report["cleanupConfirmed"] is True and "timings" not in report
    assert len(report["records"]) == 100
    assert sorted(row["ordinal"] for row in report["records"]) == list(range(100))
    assert all(row["outcome"] == "failed" and row["code"] == "admission_call_failed" for row in report["records"])
    assert "PRIVATE" not in json.dumps(report)


def test_standalone_cli_executes_real_batch_and_returns_complete_json():
    benchmark()
    root = Path(__file__).resolve().parents[2]
    child = subprocess.run([sys.executable, "-m", "app.scripts.benchmark_admission"],
        cwd=root, capture_output=True, text=True, timeout=20)
    assert child.returncode == 0, child.stderr
    assert_complete(json.loads(child.stdout))


def test_cli_refuses_external_paths_before_any_batch():
    benchmark()
    root = Path(__file__).resolve().parents[2]
    child = subprocess.run([sys.executable, "-m", "app.scripts.benchmark_admission", "PRIVATE_EXTERNAL_PATH"],
        cwd=root, capture_output=True, text=True, timeout=10)
    assert child.returncode != 0 and child.stdout == ""
    assert "PRIVATE_EXTERNAL_PATH" not in child.stderr
