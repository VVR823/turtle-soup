"""Eight complete synthetic mechanical records are not eight human labels."""
import json

import pytest

from app import baselines
from .test_agent_store import agent_storage, raw_rows
from .test_feedback_storage import storage
from .test_rule_snapshots import rule_storage

EXPECTED = {
    "candidate": ("awaiting_review", None, 3, 2, 3, 5, True),
    "counterexample": ("needs_human", None, 2, 1, 2, 3, True),
    "invalid": ("needs_human", "model_output_invalid", 2, 0, 2, 2, True),
    "tool-failed": ("needs_human", "tool_failed", 1, 2, 1, 3, True),
    "cancelled": ("cancelled", "cancellation", 1, 0, 1, 1, True),
    "deadline": ("needs_human", "deadline", 0, 0, 0, 0, True),
    "resume-nine-seven": ("needs_human", None, 10, 8, 1, 18, True),
    "cleanup-unknown": ("needs_human", "model_unavailable", 1, 0, 1, 1, False),
}


@pytest.mark.parametrize("task", list(EXPECTED))
def test_declared_synthetic_task_report_contains_actual_entire_ledger_and_honest_outcome(request, monkeypatch, task):
    from testing.agent_fixtures import run_agent_scenario
    active = request.getfixturevalue("rule_storage" if task in {"candidate", "counterexample"} else "agent_storage")
    report = run_agent_scenario(active, task, monkeypatch=monkeypatch)
    state, reason, models, tools, calls, work_steps, cleanup = EXPECTED[task]
    assert report["evidenceKind"] == "declared_synthetic_task" and report["taskKey"] == task
    assert report["state"] == state and report["stopReason"] == reason
    assert report["modelAttemptsUsed"] == models and report["toolAttemptsUsed"] == tools
    assert report["observedAdapterInvocations"] == calls and report["cleanupConfirmed"] is cleanup
    assert report["humanReferenceState"] == "not_collected" and report["providerAcceptedCalls"] is None
    steps = report["steps"]
    assert [s["seq"] for s in steps] == list(range(work_steps + 1))
    assert len({s["operationKey"] for s in steps}) == len(steps)
    assert all(s["resultDigest"] is None if s["state"] == "planned" else s["resultDigest"] is not None for s in steps)
    assert report["runId"] and report["contextDigest"] and report["deadlineAt"] is not None
    assert report["deadlineAt"] == report["originalDeadlineAt"]
    runs, actual_steps = raw_rows("agent_runs"), raw_rows("agent_steps")
    assert len(runs) == 1 and runs[0]["id"] == report["runId"] and runs[0]["state"] == report["state"]
    assert json.loads(runs[0]["manifest_json"])["contextDigest"] == report["contextDigest"]
    assert [(s["seq"], s["operationKey"], s["state"]) for s in steps] == [
        (s["seq"], s["operation_key"], s["state"]) for s in actual_steps]
    if task == "resume-nine-seven": assert report["seededPriorReservations"] == {"model": 9, "tool": 7}
    else: assert report["seededPriorReservations"] == {"model": 0, "tool": 0}
    if task == "counterexample":
        regression = report["regressions"][0]
        assert regression["inputCaseCount"] == regression["attemptedCaseCount"] == 7
        assert any(not case["passed"] for case in regression["caseResults"])
        assert report["candidateId"] is None
    if task == "candidate": assert report["candidateStatus"] == "pending" and report["candidateId"] is not None
    if task == "tool-failed": assert len([s for s in steps if s["state"] == "failed"]) == 2
    if task == "cancelled": assert steps[0]["state"] == "planned" and steps[0]["resultDigest"] is None
    if task == "cleanup-unknown": assert report["gatewayAfterClose"]["cleanup_failed"] == 1
    raw = baselines.canonical_json(report)
    assert "PRIVATE" not in raw and "rawOutput" not in raw and "expectedLabel" not in raw
    assert json.loads(raw)["taskKey"] == task
    request.node.user_properties.append(("agent_task_report", raw))
