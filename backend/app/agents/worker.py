"""One owned coordinator and independent heartbeat; SQLite owns the queue."""
import math
import time
from dataclasses import dataclass
from threading import Event, Lock, RLock, Thread

from ..runtime import Runtime
from .contracts import AgentError
from .repair_agent import RepairAgent
from .store import AgentStore


@dataclass(frozen=True)
class WorkerShutdown:
    admissionClosed: bool
    coordinatorAlive: bool
    heartbeatAlive: bool
    activeRunId: str | None
    cleanupConfirmed: bool
    lastError: str | None


class AgentWorker:
    def __init__(self, runtime, store, agent):
        if (not isinstance(runtime, Runtime) or not isinstance(store, AgentStore)
            or not isinstance(agent, RepairAgent) or store.runtime is not runtime
            or agent.store is not store or agent.gateway is not runtime.model_gateway
            or store.lease_seconds != 60 or not runtime.settings.ENABLE_AGENT
            or runtime.settings.API_WORKER_COUNT != 1 or runtime.closed):
            raise TypeError("Explicit enabled single-app worker with sixty-second store required")
        self.runtime, self.store, self.agent = runtime, store, agent
        self._lock, self._execution = RLock(), Lock()
        self._stop, self._cancelled = Event(), Event()
        self._heartbeat_stop = Event()
        self._coordinator, self._heartbeat = None, None
        self._active_run, self._busy, self._last_error = None, False, None

    def snapshot(self):
        with self._lock:
            coordinator = bool(self._coordinator and self._coordinator.is_alive())
            heartbeat = bool(self._heartbeat and self._heartbeat.is_alive())
            state = self.agent.gateway.snapshot()
            return WorkerShutdown(admissionClosed=self._stop.is_set(), coordinatorAlive=coordinator,
                heartbeatAlive=heartbeat, activeRunId=self._active_run,
                cleanupConfirmed=not (coordinator or heartbeat or self._busy
                    or state["active_agent"] or state["cleanup_failed"]), lastError=self._last_error)

    def stop_admission(self):
        with self._lock:
            self._stop.set()
            self._cancelled.set()
            self._heartbeat_stop.set()

    def start(self):
        # Verify explicit003 without migration or first provider invocation.
        with self._lock:
            if self._stop.is_set() or self.runtime.closed:
                raise AgentError("agent_unavailable", 503)
            if self._coordinator is not None:
                return
            with self.store._transaction(write=False):
                pass
            self._coordinator = Thread(target=self._serve, daemon=True,
                name="turtle-soup-agent-" + self.runtime.instance_id)
            try:
                self._coordinator.start()
            except Exception:
                self._last_error = "agent_unavailable"
                self.stop_admission()
                raise AgentError("agent_unavailable", 503) from None

    def _serve(self):
        while not self._stop.is_set():
            try:
                self.run_once()
            except AgentError as error:
                with self._lock:
                    self._last_error = error.code
            if self._stop.wait(0.25):
                break

    @staticmethod
    def _wait_heartbeat(stop):
        return stop.wait(10.0)

    def _renew(self, run, cancelled, stop):
        while not self._wait_heartbeat(stop):
            try:
                self.store.heartbeat(run.id, run.leaseToken)
            except AgentError as error:
                with self._lock:
                    self._last_error = error.code
                # Ordinary commits take this same lock for their final check.
                # Failed renewal revokes this execution before any later commit.
                with self.runtime.lock:
                    cancelled.set()
                stop.set()
                break

    def run_once(self):
        # Claim the persisted checkpoint, then renew on an independent thread
        # while drive may block. Store/agent gates preserve budgets/deadline and
        # fence a lost owner; a heartbeat is not proof model cleanup completed.
        # This trusted server entry also makes native recovery tests bounded.
        # No model/HTTP caller can invoke it or supply queue/lease parameters.
        if not self._execution.acquire(blocking=False):
            return None
        try:
            with self._lock:
                if (self._stop.is_set() or self.runtime.closed
                    or (self._heartbeat and self._heartbeat.is_alive())):
                    return None
            state = self.agent.gateway.snapshot()
            if state["closed"] or state["active"] or state["waiting_online"] or state["cleanup_failed"]:
                return None
            run = None
            for pending in self.store.pending_runs():
                if pending.checkpoint.deadlineAt is not None and self.store._now() >= pending.checkpoint.deadlineAt:
                    return self.store.stop(pending.id, lease_token=pending.leaseToken,
                        state="needs_human", reason="deadline")
                try:
                    run = self.store.claim(pending.id, expected_row_version=pending.rowVersion)
                    break
                except AgentError as error:
                    with self._lock:
                        self._last_error = error.code
                    if pending.state == "queued" and error.code in {
                        "agent_context_stale", "agent_source_reload_required",
                        "agent_suite_changed", "agent_traffic_mismatch"
                    }:
                        try:
                            return self.store.handoff_stale_queued(pending.id,
                                expected_row_version=pending.rowVersion)
                        except AgentError as handoff_error:
                            # Another owner/admin or a transient outage must
                            # not be overwritten by this scheduling hint.
                            with self._lock:
                                self._last_error = handoff_error.code
            if run is None:
                return None
            with self._lock:
                if self._stop.is_set() or self.runtime.closed:
                    return self.store.stop(run.id, lease_token=run.leaseToken,
                        state="needs_human", reason="shutting_down")
                self._busy, self._active_run = True, run.id
                self._cancelled, self._heartbeat_stop = Event(), Event()
                cancelled, heartbeat_stop = self._cancelled, self._heartbeat_stop
                self._heartbeat = Thread(target=self._renew, args=(run, cancelled, heartbeat_stop), daemon=True,
                    name="turtle-soup-agent-heartbeat-" + self.runtime.instance_id)
                try:
                    self._heartbeat.start()
                except Exception:
                    self._last_error = "agent_unavailable"
                    self._busy, self._active_run = False, None
                    self.stop_admission()
                    return self.store.stop(run.id, lease_token=run.leaseToken,
                        state="needs_human", reason="model_unavailable")
            try:
                return self.agent.drive(run.id, run.leaseToken, cancelled)
            finally:
                heartbeat_stop.set()
                self._heartbeat.join(timeout=0.1)
                with self._lock:
                    self._busy, self._active_run = False, None
        finally:
            self._execution.release()

    def close(self, *, wait_seconds=2):
        if type(wait_seconds) not in (int, float) or not math.isfinite(wait_seconds) or not 0 <= wait_seconds <= 2:
            raise ValueError("Worker join must be bounded to two seconds")
        self.stop_admission()
        deadline = time.monotonic() + wait_seconds
        with self._lock:
            threads = (self._coordinator, self._heartbeat)
        for thread in threads:
            if thread is not None and thread.ident is not None:
                thread.join(timeout=max(0.0, deadline - time.monotonic()))
        # Runtime owns shared gateway teardown. Joining this worker never
        # closes online transports or asserts remote inference terminated.
        return self.snapshot()
