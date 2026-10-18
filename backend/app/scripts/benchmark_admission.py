"""Controlled synthetic100-slot applicants, not HTTP capacity or provider latency.

No paths, settings, providers or arguments are accepted; import is inert.
All drivers/adapters belong to this short-lived measurement, not the website.
"""
from concurrent.futures import ThreadPoolExecutor
import json
import os
import platform
from threading import Barrier, Event, Lock, current_thread
import time
import tracemalloc

from app.model_gateway import ModelFailure, ModelGateway
from app.scripts.benchmark_metrics import nearest_rank


class _ControlledIO:
    def __init__(self):
        self.release = Event()
        self.lock = Lock()
        self.started = 0
        self.closed = 0
        self.worker_threads = set()

    def factory(self):
        fixture = self
        with self.lock:
            self.worker_threads.add(current_thread())

        class Adapter:
            def invoke(self, messages, *, deadline, cancelled):
                with fixture.lock:
                    fixture.started += 1
                while not fixture.release.wait(0.01):
                    if cancelled.is_set():
                        raise ModelFailure("model_cancelled")
                    if time.monotonic() >= deadline:
                        raise ModelFailure("model_timeout")
                return '{"answer":"是","reasoning":"declared synthetic admission fixture"}'

            def request_cancel(self):
                pass  # Gateway's owned cancellation Event is observed above.

            def close(self):
                with fixture.lock:
                    fixture.closed += 1

        return Adapter()


def _measure_batch():
    io, barrier = _ControlledIO(), Barrier(101)
    gateway = ModelGateway(adapter_factory=io.factory)
    pool, futures, drivers = None, [], set()
    driver_lock = Lock()
    report = {}
    peaks = {"activeOwners": 0, "waitingOnline": 0}

    def observe():
        snapshot = gateway.snapshot()
        peaks["activeOwners"] = max(peaks["activeOwners"], snapshot["active"])
        peaks["waitingOnline"] = max(peaks["waitingOnline"], snapshot["waiting_online"])
        return snapshot

    def apply(ordinal):
        with driver_lock:
            drivers.add(current_thread())
        started = time.monotonic()
        outcome, code = "failed", "admission_call_failed"
        try:
            barrier.wait(timeout=5)
            started = time.monotonic()
            value = gateway.invoke([ordinal], deadline=started + 8, max_attempts=1)
            if value.answer == "是":
                outcome, code = "admitted", "passed"
        except ModelFailure as error:
            code = error.code
            outcome = "rejected" if code == "model_busy" else "failed"
        except Exception:
            pass  # No transport/driver exception text enters a report.
        return {"ordinal": ordinal, "outcome": outcome, "code": code,
            "elapsedMs": (time.monotonic() - started) * 1000}

    try:
        pool = ThreadPoolExecutor(max_workers=100, thread_name_prefix="ts17-admission-driver")
        for ordinal in range(100):
            futures.append(pool.submit(apply, ordinal))
        barrier.wait(timeout=5)
        stop_at = time.monotonic() + 5
        while True:
            snapshot = observe()
            completed = [future.result() for future in futures if future.done()]
            if any(row["outcome"] != "rejected" for row in completed):
                raise ValueError("Batch failed before controlled release")
            if snapshot["active"] == 2 and snapshot["waiting_online"] == 32 and len(completed) == 66:
                with io.lock:
                    if io.started != 2:
                        raise ValueError("Plateau lacks actual transport owners")
                report["initialAdmission"] = {"accepted": snapshot["active"],
                    "queued": snapshot["waiting_online"], "rejected": len(completed)}
                break
            if time.monotonic() >= stop_at:
                raise ValueError("No bounded admission plateau")
            io.release.wait(0.002)
        io.release.set()
        while not all(future.done() for future in futures):
            observe()
            if time.monotonic() >= stop_at + 3:
                raise ValueError("Drain did not complete within original budget")
            Event().wait(0.002)
        rows = [future.result() for future in futures]
        if sorted(row["ordinal"] for row in rows) != list(range(100)):
            raise ValueError("Incomplete applicants")
        counts = {name: sum(row["outcome"] == name for row in rows) for name in ("admitted", "rejected", "failed")}
        if counts != {"admitted": 34, "rejected": 66, "failed": 0}:
            raise ValueError("Unexpected outcome accounting")
        with io.lock:
            if io.started != counts["admitted"] or io.closed != io.started:
                raise ValueError("Actual transport accounting mismatch")
        report.update(status="complete", records=rows, outcomes=counts, peaks=peaks,
            timings={name: {"p50Ms": nearest_rank([row["elapsedMs"] for row in rows if row["outcome"] == name], 0.5),
                "p95Ms": nearest_rank([row["elapsedMs"] for row in rows if row["outcome"] == name], 0.95)}
                for name in ("admitted", "rejected")})
    except Exception:
        report = {"status": "failed", "failureCode": "admission_benchmark_failed"}
    finally:
        io.release.set()
        barrier.abort()
        # Always release the fixture before waiting on drivers or owner close.
        if pool is not None:
            pool.shutdown(wait=True, cancel_futures=True)
        # Even a failed batch retains every submitted driver's terminal record.
        report["records"] = [future.result() if not future.cancelled() else {
            "ordinal": ordinal, "outcome": "failed", "code": "admission_fixture_cancelled", "elapsedMs": None}
            for ordinal, future in enumerate(futures)]
        closed = gateway.close(wait_seconds=1)
        for thread in tuple(io.worker_threads):
            thread.join(timeout=1)
        stopped = all(not thread.is_alive() for thread in (*drivers, *io.worker_threads))
        report.update(finalGateway=closed, transport={"started": io.started, "closed": io.closed},
            threadsStopped=stopped,
            cleanupConfirmed=stopped and closed["closed"] and closed["active"] == 0 and closed["waiting_online"] == 0)
        if not report["cleanupConfirmed"]:
            report = {key: value for key, value in report.items() if key not in {"timings", "initialAdmission", "outcomes", "peaks"}}
            report.update(status="failed", failureCode="admission_benchmark_cleanup_failed")
    return report


def measure_admission():
    result = {"schemaVersion": 1, "evidenceKind": "declared_synthetic_benchmark",
        "measurementScope": "model_gateway_admission_controlled_hold", "applicants": 100,
        "environment": {"python": platform.python_version(), "platform": platform.platform(), "logicalCpuCount": os.cpu_count()},
        "comparisonBeforeUpgrade": None, "realProviderLatency": None,
        "limitations": ["Temporary100 test drivers, NOT100 concurrent HTTP website users",
            "Gateway2-owner/32-queue policy, NOT machine CPU capacity or production QPS",
            "Raw time includes intentional transport holding and tracemalloc overhead",
            "No matching before-upgrade measurement, provider latency, RSS, SLA or model quality evidence"]}
    trace_owned = not tracemalloc.is_tracing()
    started_cpu = time.process_time()
    if trace_owned:
        tracemalloc.start()
    try:
        result.update(_measure_batch())
        result["resources"] = {"cpuMilliseconds": (time.process_time() - started_cpu) * 1000,
            "pythonAllocatedPeakBytes": tracemalloc.get_traced_memory()[1],
            "allocationScope": "owned_run" if trace_owned else "existing_process_trace_peak"}
    finally:
        if trace_owned:
            tracemalloc.stop()
    return result


if __name__ == "__main__":
    import sys
    if len(sys.argv) != 1:
        raise SystemExit("No arguments or external paths are accepted")
    output = measure_admission()
    print(json.dumps(output, ensure_ascii=False, allow_nan=False))
    raise SystemExit(0 if output["status"] == "complete" else 1)
