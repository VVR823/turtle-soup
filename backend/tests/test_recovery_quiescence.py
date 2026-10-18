"""LOCAL stop-writer prerequisite, not a claim about a production server.

Breaks caught: treating Runtime.closed as enough while owned adapter/worker,
transport, audit writes or pending intent still exist; missing external inventory.
"""
import asyncio
import importlib
from dataclasses import replace
from threading import Event

import httpx
import pytest

from .test_agent_store import agent_storage, create
from .test_agent_worker import configured
from .test_feedback_storage import storage


WRITERS = {"api": "stopped", "cron": "disabled", "timer": "disabled",
           "legacy_merge": "disabled", "legacy_cleanup": "disabled",
           "manual_scripts": "stopped", "direct_database": "stopped"}


def gate():
    name = "app.scripts.recovery_quiescence"
    assert importlib.util.find_spec(name) is not None, "LOCAL resource quiescence gate is missing"
    return importlib.import_module(name).require_local_quiescence


def test_live_runtime_cannot_be_certified_as_stopped(runtime):
    check = gate()
    from app.scripts.snapshot_recovery import RecoveryError
    with pytest.raises(RecoveryError):
        check(runtime, WRITERS)


def test_actual_closed_empty_local_runtime_has_only_scoped_declarations(runtime):
    check = gate()
    asyncio.run(runtime.aclose())
    result = check(runtime, WRITERS)
    assert result == {"localOnly": True, "productionReady": False, "ownedResourcesStopped": True,
                      "externalInventoryDeclared": True, "quiescenceVerified": False}


@pytest.mark.parametrize("writer", list(WRITERS))
@pytest.mark.parametrize("state", [None, "active", "unknown", True, ["stopped"]])
def test_missing_unknown_or_active_external_writer_keeps_maintenance(runtime, writer, state):
    check = gate()
    from app.scripts.snapshot_recovery import RecoveryError
    asyncio.run(runtime.aclose())
    inventory = {**WRITERS, writer: state}
    if state is None:
        del inventory[writer]
    with pytest.raises(RecoveryError):
        check(runtime, inventory)


def test_uninventoried_extra_writer_is_not_silently_ignored(runtime):
    check = gate()
    from app.scripts.snapshot_recovery import RecoveryError
    asyncio.run(runtime.aclose())
    with pytest.raises(RecoveryError):
        check(runtime, {**WRITERS, "unknown_worker": "stopped"})


def test_non_testing_runtime_is_rejected_without_loading_or_touching_production(runtime):
    check = gate()
    from app.scripts.snapshot_recovery import RecoveryError
    runtime.settings = replace(runtime.settings, TESTING=False)
    asyncio.run(runtime.aclose())
    with pytest.raises(RecoveryError):
        check(runtime, WRITERS)


def test_pending_intent_after_shutdown_does_not_count_as_drained(runtime):
    check = gate()
    from app.scripts.snapshot_recovery import RecoveryError
    runtime.pending_agents.enqueue("synthetic-intent", "synthetic-digest")
    asyncio.run(runtime.aclose())
    with pytest.raises(RecoveryError):
        check(runtime, WRITERS)
    runtime.pending_agents.cancel("synthetic-intent")
    assert check(runtime, WRITERS)["ownedResourcesStopped"] is True


@pytest.mark.parametrize("asynchronous", [False, True])
def test_unclosed_owned_http_transport_prevents_quiescence(runtime, asynchronous):
    check = gate()
    from app.scripts.snapshot_recovery import RecoveryError
    asyncio.run(runtime.aclose())
    # Allocate a real local transport after teardown to exercise escaped owner,
    # without making network requests or hiding cleanup in a fake Runtime.
    if asynchronous:
        runtime.http_async_client = httpx.AsyncClient(transport=httpx.MockTransport(lambda _: httpx.Response(200)))
    else:
        runtime.http_client = httpx.Client(transport=httpx.MockTransport(lambda _: httpx.Response(200)))
    try:
        with pytest.raises(RecoveryError):
            check(runtime, WRITERS)
    finally:
        if asynchronous:
            asyncio.run(runtime.http_async_client.aclose())
        else:
            runtime.http_client.close()
    assert check(runtime, WRITERS)["ownedResourcesStopped"] is True


def test_actual_blocked_worker_is_rejected_even_after_runtime_close(agent_storage):
    check = gate()
    from app.scripts.snapshot_recovery import RecoveryError
    owner, worker, shared, transport = configured(agent_storage)
    agent_storage.agent_worker = worker
    create(agent_storage, owner=owner)
    entered, release = Event(), Event()

    def blocked():
        entered.set()
        assert release.wait(10)

    transport.before_return = blocked
    try:
        worker.start()
        assert entered.wait(2)
        asyncio.run(agent_storage.aclose())
        assert agent_storage.closed is True
        assert not agent_storage.agent_shutdown.cleanupConfirmed
        assert shared.snapshot()["active_agent"] == 1
        with pytest.raises(RecoveryError):
            check(agent_storage, WRITERS)
    finally:
        release.set()
        agent_storage.model_shutdown = shared.close(wait_seconds=1)
        agent_storage.agent_shutdown = worker.close(wait_seconds=1)
        assert agent_storage.model_shutdown["active"] == 0
        assert agent_storage.agent_shutdown.cleanupConfirmed
    assert check(agent_storage, WRITERS)["ownedResourcesStopped"] is True


def test_worker_without_actual_shutdown_receipt_is_not_assumed_stopped(agent_storage):
    check = gate()
    from app.scripts.snapshot_recovery import RecoveryError
    _, worker, _, _ = configured(agent_storage)
    agent_storage.agent_worker = worker
    asyncio.run(agent_storage.aclose())
    actual = agent_storage.agent_shutdown
    assert actual.cleanupConfirmed
    agent_storage.agent_shutdown = None
    with pytest.raises(RecoveryError):
        check(agent_storage, WRITERS)
    agent_storage.agent_shutdown = actual
    assert check(agent_storage, WRITERS)["ownedResourcesStopped"] is True


def test_missing_audit_shutdown_report_is_not_assumed_drained(storage):
    check = gate()
    from app import db
    from app.audit_store import AuditStore
    from app.scripts.snapshot_recovery import RecoveryError
    asyncio.run(storage.aclose())
    storage.audit_store = AuditStore(storage.settings.DATA_DIR, connect=db._connect)
    try:
        with pytest.raises(RecoveryError):
            check(storage, WRITERS)
    finally:
        storage.audit_shutdown = asyncio.run(storage.audit_store.close())
    assert storage.audit_shutdown["residualJobs"] == 0
    assert check(storage, WRITERS)["ownedResourcesStopped"] is True


def test_actual_pending_audit_job_prevents_maintenance_exit(storage):
    check = gate()
    from app import db
    from app.audit_store import AuditStore
    from app.scripts.snapshot_recovery import RecoveryError
    asyncio.run(storage.aclose())
    store = AuditStore(storage.settings.DATA_DIR, connect=db._connect)
    storage.audit_store = store
    entered, release = Event(), Event()
    real_recovery = store.recover_fallback

    def blocked_recovery():
        entered.set()
        assert release.wait(5)
        return real_recovery()

    async def scenario():
        task = asyncio.create_task(store._run_io(blocked_recovery, wait_ms=0))
        try:
            assert await asyncio.to_thread(entered.wait, 2)
            await task
            storage.audit_shutdown = await store.close(wait_seconds=0)
            assert storage.audit_shutdown["residualJobs"] == 1
            with pytest.raises(RecoveryError):
                check(storage, WRITERS)
        finally:
            release.set()
            if store._tasks:
                _, unfinished = await asyncio.wait(tuple(store._tasks), timeout=2)
                assert not unfinished
            storage.audit_shutdown = await store.close(wait_seconds=2)
        assert storage.audit_shutdown["residualJobs"] == 0
        assert check(storage, WRITERS)["ownedResourcesStopped"] is True

    asyncio.run(scenario())
