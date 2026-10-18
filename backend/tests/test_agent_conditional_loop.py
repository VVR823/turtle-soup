"""Conditional synthetic adapter reads actual results, never private/gold data."""
import json
from threading import Event

import pytest

from app import baselines
from .test_rule_snapshots import rule_storage
from .test_repair_corpus import frozen_corpus, setup_run
from .test_candidate_validation import scope
from .test_agent_store import raw_rows
from .test_model_gateway import ScriptedTransport


@pytest.mark.parametrize("labels,expected", [(("是", "与此无关"), "awaiting_review"),
    (("不是", "与此无关"), "needs_human")])
def test_model_fixture_branches_on_actual_fixed_regression_then_saves_or_hands_off(rule_storage, labels, expected):
    from app.agents.regression import FixedRegression
    from app.agents.repair_agent import RepairAgent
    from app.agents.tools import ToolExecutor
    from app.model_gateway import ModelGateway
    source = scope()
    regression = FixedRegression(rule_storage, corpus=frozen_corpus(source, labels=labels))
    owner, run, _, draft, _ = setup_run(rule_storage, regression, source)
    class ConditionalTransport(ScriptedTransport):
        def invoke(self, messages, *, deadline, cancelled):
            self.calls.append(deadline)
            payload = baselines.strict_json(messages[1].content)
            completed = [s["result"] for s in payload["steps"] if s["state"] == "completed"
                and s["action"].get("action") != "model_decision"]
            if not completed:
                action = dict(action="tool", tool="run_regression", arguments=dict(draft=draft.model_dump(mode="json")))
            elif "reportId" in completed[-1]:
                report = completed[-1]
                if report["status"] != "complete":
                    action = dict(action="finish", needsHumanReason="Actual synthetic regression has counterexamples")
                else:
                    action = dict(action="tool", tool="save_candidate_rule", arguments=dict(
                        draft=draft.model_dump(mode="json"), regressionReportId=report["reportId"]))
            else: action = dict(action="finish", candidateId=completed[-1]["id"])
            return json.dumps(action)
    transport = ConditionalTransport([])
    shared = ModelGateway(adapter_factory=lambda: transport); rule_storage.model_gateway = shared
    try:
        status = RepairAgent(owner, ToolExecutor(owner, regression=regression), shared).drive(run.id, run.leaseToken, Event())
        assert status.state == expected and status.reason is None
        assert status.modelAttemptsUsed == (3 if expected == "awaiting_review" else 2)
        assert status.toolAttemptsUsed == (2 if expected == "awaiting_review" else 1)
        reports = [baselines.strict_json(s.resultJson) for s in owner.steps(run.id)
            if s.action.action == "tool" and s.action.tool == "run_regression"]
        assert reports[0]["evidenceKind"] == "synthetic_fixture" and reports[0]["inputCaseCount"] == 7
        assert reports[0]["status"] == ("complete" if expected == "awaiting_review" else "failed")
        candidates = raw_rows("rule_candidates")
        assert len(candidates) == (1 if expected == "awaiting_review" else 0)
        if candidates: assert candidates[0]["status"] == "pending" and status.candidateId == candidates[0]["id"]
        assert len(transport.calls) == status.modelAttemptsUsed
    finally: assert shared.close(wait_seconds=0.1)["active"] == 0
