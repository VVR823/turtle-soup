"""Bounded local Agent execution after restoration; no cloud or human verdict."""
import asyncio
from contextlib import closing
import json

import pytest

from app import db, migrations
from app.agents.repair_agent import RepairAgent
from app.agents.tools import ToolExecutor
from app.agents.worker import AgentWorker
from app.config import Settings
from app.model_gateway import ModelGateway
from app.runtime import Runtime, runtime_context
from app.scripts.snapshot_recovery import backup, restore
from app.testing import FakeModel
from .test_agent_store import create, store
from .test_candidate_review_store import proposal
from .test_model_gateway import ScriptedTransport
from .test_release_recovery import hashes
from .test_rule_snapshots import rule_storage


@pytest.mark.parametrize('version', [3, 4, 5])
def test_restored_queue_runs_once_with_preserved_identity_and_bounded_cleanup(rule_storage, tmp_path_factory, version):
    original = rule_storage
    with closing(db._connect()) as conn:
        migrations.migrate(conn, original.soups, target_version=version)
    _, _, queued = create(original)
    source = original.settings.DATA_DIR
    soups = original.soups
    asyncio.run(original.aclose())
    source_hashes = hashes(source)
    outputs = tmp_path_factory.mktemp('final-restored-agent')
    archive, restored = outputs / 'archive', outputs / 'restored'
    assert backup(str(source), str(archive), str(outputs / 'backup.json'))['migrationVersion'] == version
    archive_hashes = hashes(archive)
    assert restore(str(archive), str(restored), str(outputs / 'restore.json'))['migrationVersion'] == version
    active = Runtime(Settings.for_test(restored, ENABLE_AGENT=True), model=FakeModel(), soups=soups)
    transport = ScriptedTransport([
        json.dumps({'action': 'tool', 'tool': 'get_turn_trace', 'arguments': {'turnId': queued.manifest.context.turnId}}),
        json.dumps({'action': 'finish', 'needsHumanReason': 'Synthetic restored evidence needs a human verdict'}),
    ])
    gateway = ModelGateway(adapter_factory=lambda: transport)
    active.model_gateway = gateway
    owner = store(active, lease_seconds=60)
    worker = AgentWorker(active, owner, RepairAgent(owner, ToolExecutor(owner), gateway))
    active.agent_worker = worker
    try:
        with runtime_context(active):
            assert owner.read(queued.id) == queued  # Opening never executes queued work.
            assert transport.calls == []
            result = worker.run_once()  # One explicit bounded test operation, no coordinator loop.
            assert result.id == queued.id and owner.read(queued.id).requestId == queued.requestId
            assert result.state == 'needs_human' and result.candidateId is None
            assert result.modelAttemptsUsed == 2 and result.toolAttemptsUsed == 1
            steps = owner.steps(queued.id)
            assert len(steps) == 4 and all(step.state == 'completed' for step in steps)
            assert [step.action.tool for step in steps if step.action.action == 'tool'] == ['get_turn_trace']
            assert worker.run_once() is None and owner.read(queued.id).checkpoint.modelAttemptsUsed == 2
            assert len(transport.calls) == 2
            assert worker.close(wait_seconds=1).cleanupConfirmed
            assert gateway.close(wait_seconds=1)['active'] == 0
            if version >= 4:
                review, new_run, candidate_id = proposal(active)
                detail = review.detail(candidate_id)
                assert new_run.state == 'awaiting_review' and detail.candidateStatus == 'pending'
                assert detail.material.report.evidenceKind == 'synthetic_fixture'
                assert detail.material.report.status == 'complete'
                assert detail.publishedRuleVersion is None  # No synthetic review becomes publication.
            with closing(db._connect()) as conn:
                migrations.verify_schema(conn, required_version=version)
    finally:
        asyncio.run(active.aclose())
    assert not worker.snapshot().coordinatorAlive and not worker.snapshot().heartbeatAlive
    assert hashes(source) == source_hashes and hashes(archive) == archive_hashes
