"""Closed server lease policy preserves the original deadline and defaults."""
import pytest

from .test_agent_store import agent_storage, create, store
from .test_feedback_storage import storage


def test_worker_sixty_second_lease_and_renewal_never_restart_original_deadline(agent_storage):
    now = [1000.0]
    owner = store(agent_storage, clock=lambda: now[0], lease_seconds=60)
    _, _, queued = create(agent_storage, owner=owner)
    run = owner.claim(queued.id, expected_row_version=0)
    assert run.leaseExpiresAt == 1060.0 and run.checkpoint.deadlineAt == 1180.0
    now[0] = 1040.0
    beat = owner.heartbeat(run.id, run.leaseToken)
    assert beat.leaseExpiresAt == 1100.0 and beat.checkpoint == run.checkpoint and beat.leaseToken == run.leaseToken
    now[0] = 1090.0
    beat = owner.heartbeat(run.id, run.leaseToken)
    now[0] = 1140.0
    final = owner.heartbeat(run.id, run.leaseToken)
    assert final.leaseExpiresAt == 1180.0 and final.checkpoint == run.checkpoint


def test_sixty_second_reclaim_keeps_actual_old_checkpoint_and_denies_old_owner(agent_storage):
    from app.agents.contracts import AgentError
    now = [1000.0]; owner = store(agent_storage, clock=lambda: now[0], lease_seconds=60)
    _, _, queued = create(agent_storage, owner=owner)
    run = owner.claim(queued.id, expected_row_version=0)
    now[0] = 1061.0
    replacement = owner.claim(run.id, expected_row_version=run.rowVersion)
    assert replacement.checkpoint == run.checkpoint and replacement.leaseToken != run.leaseToken
    assert replacement.leaseExpiresAt == 1121.0
    with pytest.raises(AgentError): owner.heartbeat(run.id, run.leaseToken)


@pytest.mark.parametrize("value", [True, False, 60.0, "60", None, 0, 31, 90, 180])
def test_only_real_closed_server_thirty_or_sixty_second_lease_is_allowed(agent_storage, value):
    with pytest.raises((TypeError, ValueError)): store(agent_storage, lease_seconds=value)


def test_explicit_thirty_remains_same_as_standalone_default(agent_storage):
    now = [1000.0]; owner = store(agent_storage, clock=lambda: now[0], lease_seconds=30)
    _, _, queued = create(agent_storage, owner=owner)
    run = owner.claim(queued.id, expected_row_version=0)
    assert run.leaseExpiresAt == 1030.0 and run.checkpoint.deadlineAt == 1180.0
