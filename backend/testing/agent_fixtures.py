"""Offline scenario reporting utility; never imported by application code.

All labels, approvals and models here are explicitly synthetic. Native stores,
tools, regression, gateway and RepairAgent still execute their real code paths.
"""
import json
from concurrent.futures import ThreadPoolExecutor
from threading import Event

from app import baselines
from app.agents.contracts import parse_tool_action
from app.agents.repair_agent import RepairAgent
from app.agents.tools import ToolExecutor
from app.model_gateway import ModelGateway


class _Conditional:
    def __init__(self, draft):
        self.draft, self.calls = draft, []

    def invoke(self, messages, *, deadline, cancelled):
        self.calls.append(deadline)
        payload = baselines.strict_json(messages[1].content)
        completed = [s["result"] for s in payload["steps"] if s["state"] == "completed"
            and s["action"].get("action") != "model_decision"]
        if not completed:
            action = dict(action="tool", tool="run_regression", arguments=dict(draft=self.draft.model_dump(mode="json")))
        elif "reportId" in completed[-1]:
            result = completed[-1]
            if result["status"] != "complete":
                action = dict(action="finish", needsHumanReason="Synthetic actual counterexample requires human review")
            else:
                action = dict(action="tool", tool="save_candidate_rule", arguments=dict(
                    draft=self.draft.model_dump(mode="json"), regressionReportId=result["reportId"]))
        else:
            action = dict(action="finish", candidateId=completed[-1]["id"])
        return json.dumps(action)

    def request_cancel(self):
        pass

    def close(self):
        pass


def _trace(owner, run, task, status, calls, cleanup, seeded):
    # These are actual persisted typed rows; no successful trajectory is
    # invented for failed, cancelled, uncertain or seeded historical work.
    records = owner.steps(run.id)
    steps, regressions = [], []
    for step in records:
        result = None if step.resultJson is None else baselines.strict_json(step.resultJson)
        steps.append(dict(seq=step.seq, operationKey=step.operationKey, state=step.state,
            action=step.action.action, tool=step.action.tool if step.action.action == "tool" else None,
            actionDigest=baselines.digest(step.action.model_dump(mode="json")),
            resultDigest=None if result is None else baselines.digest(result),
            resultStatus=None if result is None else result.get("status"),
            errorCode=None if result is None else result.get("errorCode", result.get("code"))))
        if step.action.action == "tool" and step.action.tool == "run_regression" and result is not None:
            regressions.append({name: result[name] for name in ("reportId", "status", "evidenceKind",
                "inputCaseCount", "attemptedCaseCount", "passedCaseCount", "caseResults", "cleanupConfirmed", "truncated")})
    from backend.tests.test_agent_store import raw_rows
    candidates = raw_rows("rule_candidates")
    return dict(schemaVersion=1, evidenceKind="declared_synthetic_task", taskKey=task,
        runId=run.id, contextDigest=run.manifest.contextDigest, state=status.state,
        stopReason=status.reason, candidateId=status.candidateId,
        candidateStatus=candidates[0]["status"] if candidates else None,
        modelAttemptsUsed=status.modelAttemptsUsed, toolAttemptsUsed=status.toolAttemptsUsed,
        originalDeadlineAt=run.checkpoint.deadlineAt, deadlineAt=status.deadlineAt,
        observedAdapterInvocations=calls, seededPriorReservations=seeded,
        providerAcceptedCalls=None, humanReferenceState="not_collected", realProviderState="not_called",
        cleanupConfirmed=cleanup["active"] == 0 and cleanup["cleanup_failed"] == 0,
        gatewayAfterClose=cleanup, steps=steps, regressions=regressions)


def run_agent_scenario(active, task, *, monkeypatch):
    from backend.tests.test_agent_store import running, create, store
    from backend.tests.test_agent_decisions import identity, reserve, outcome
    from backend.tests.test_repair_agent_loop import tool
    from backend.tests.test_model_gateway import ScriptedTransport
    finish = dict(action="finish", needsHumanReason="Synthetic mechanical handoff")
    seeded = dict(model=0, tool=0)
    regression = None
    if task in {"candidate", "counterexample"}:
        from app.agents.regression import FixedRegression
        from backend.tests.test_candidate_validation import scope
        from backend.tests.test_repair_corpus import frozen_corpus, setup_run
        source = scope()
        labels = ("是", "与此无关") if task == "candidate" else ("不是", "与此无关")
        regression = FixedRegression(active, corpus=frozen_corpus(source, labels=labels))
        owner, run, _, draft, _ = setup_run(active, regression, source)
        transport = _Conditional(draft)
    elif task == "deadline":
        now = [1000.0]; owner = store(active, clock=lambda: now[0])
        _, _, queued = create(active, owner=owner)
        run = owner.claim(queued.id, expected_row_version=0)
        now[0] = 1181.0
        transport = ScriptedTransport([])
    else:
        owner, _, run = running(active)
        if task == "invalid":
            transport = ScriptedTransport(["PRIVATE malformed", "different invalid"])
        elif task == "tool-failed":
            import app.agents.tools as module
            def failed(*args): raise RuntimeError("PRIVATE synthetic computation failure")
            monkeypatch.setattr(module, "truth_result", failed)
            transport = ScriptedTransport([json.dumps(tool(run, "retrieve_truth"))])
        elif task == "cleanup-unknown":
            transport = ScriptedTransport([json.dumps(finish)], broken_close=True)
        elif task == "resume-nine-seven":
            selected = tool(run, "get_turn_trace")
            for number in range(7):
                decision = identity(run, number * 2); reserve(owner, decision)
                owner.complete_decision(decision, outcome(action=selected))
                ToolExecutor(owner).execute(identity(run, number * 2 + 1), parse_tool_action(selected))
            invalid = identity(run, 14); reserve(owner, invalid); owner.complete_decision(invalid, outcome(status="invalid"))
            corrected = identity(run, 15); reserve(owner, corrected, correction=invalid.operationKey)
            owner.complete_decision(corrected, outcome(action=selected))
            seeded = dict(model=9, tool=7)
            transport = ScriptedTransport([json.dumps(finish)])
        elif task == "cancelled":
            entered, release = Event(), Event()
            def blocked(): entered.set(); assert release.wait(3)
            transport = ScriptedTransport([json.dumps(finish)], before_return=blocked)
        else:
            raise ValueError("Unknown declared synthetic scenario")
    shared = ModelGateway(adapter_factory=lambda: transport); active.model_gateway = shared
    agent = RepairAgent(owner, ToolExecutor(owner, regression=regression), shared)
    try:
        if task == "cancelled":
            with ThreadPoolExecutor(max_workers=1) as pool:
                future = pool.submit(agent.drive, run.id, run.leaseToken, Event())
                try:
                    assert entered.wait(2)
                    owner.cancel(run.id, expected_row_version=owner.read(run.id).rowVersion)
                finally: release.set()
                status = future.result(timeout=3)
        else:
            status = agent.drive(run.id, run.leaseToken, Event())
    finally:
        if task == "cancelled": release.set()
        cleanup = shared.close(wait_seconds=0.5)
    return _trace(owner, run, task, status, len(transport.calls), cleanup, seeded)
