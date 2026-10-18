"""LOCAL recovery prerequisite, not a production process discovery/stop command.

The caller must actually stop its declared fixture writers. External inventory
remains a declaration; no global quiescence or production authorization is issued.
"""
from app.runtime import Runtime
from app.scripts.snapshot_recovery import RecoveryError


_WRITERS = {"api", "cron", "timer", "legacy_merge", "legacy_cleanup",
            "manual_scripts", "direct_database"}


def require_local_quiescence(runtime: Runtime, external_writers: dict[str, str]) -> dict:
    """Read current owned resource state; never close, cancel or initialize it."""
    if not isinstance(runtime, Runtime) or runtime.settings.TESTING is not True:
        raise RecoveryError("Local testing runtime required")
    if (type(external_writers) is not dict or external_writers.keys() != _WRITERS
            or any(type(state) is not str or state not in ("stopped", "disabled")
                   for state in external_writers.values())):
        raise RecoveryError("Complete stopped external inventory required")
    if runtime.closed is not True or runtime.pending_agents.snapshot()["queued"] != 0:
        raise RecoveryError("Runtime admission or pending intent remains")
    gateway = runtime.model_gateway
    if gateway is not None:
        state = gateway.snapshot()
        if state["closed"] is not True or any(state[name] != 0 for name in (
            "active", "waiting_online", "active_online", "active_agent",
            "timed_out_but_running", "cleanup_failed"
        )):
            raise RecoveryError("Owned model work remains")
    if runtime.agent_worker is not None:
        state = runtime.agent_worker.snapshot()
        receipt = runtime.agent_shutdown
        if (receipt is None or receipt.cleanupConfirmed is not True
                or state.admissionClosed is not True or state.cleanupConfirmed is not True
                or state.coordinatorAlive is not False or state.heartbeatAlive is not False
                or state.activeRunId is not None):
            raise RecoveryError("Owned Agent work or shutdown evidence remains")
    for client in (runtime.http_client, runtime.http_async_client):
        if client is not None and client.is_closed is not True:
            raise RecoveryError("Owned HTTP transport remains")
    if runtime.audit_store is not None:
        receipt = runtime.audit_shutdown
        status = runtime.audit_store.status()
        # The store owns this admission lock. Read it, never mutate its state or
        # infer admission closure merely from a stale Runtime receipt.
        with runtime.audit_store._lock:
            admission_closed = runtime.audit_store._closed
        if (admission_closed is not True or not isinstance(receipt, dict)
                or receipt.get("residualJobs") != 0 or receipt.get("unpersistedCount") != 0
                or status.activeIO != 0 or status.memoryCount != 0):
            raise RecoveryError("Owned audit work or shutdown evidence remains")
    return {"localOnly": True, "productionReady": False, "ownedResourcesStopped": True,
            "externalInventoryDeclared": True, "quiescenceVerified": False}
