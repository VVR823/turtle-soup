"""Explicit synthetic runner fixtures, never actual human or model evidence."""
from uuid import UUID
from threading import Event

from langchain_core.messages import AIMessage
from app.testing import FakeModel


class ScriptedFakeModel(FakeModel):
    def __init__(self, outputs):
        super().__init__()
        self.outputs = tuple(outputs)
        self.entered = Event()
        self.release = Event()

    def _respond(self, messages):
        with self._calls_lock:
            index = len(self.calls)
            self.calls.append(messages)
        self.entered.set()
        output = self.outputs[index]
        if output == "BLOCK":
            self.release.wait(5)
            output = '{"reasoning":"synthetic","answer":"是"}'
        if isinstance(output, Exception):
            raise output
        return output if isinstance(output, AIMessage) else AIMessage(content=output)


def answer_json(answer="是"):
    from app.baselines import canonical_json
    return canonical_json({"reasoning": "synthetic fixture", "answer": answer})


def small_snapshot(reviewed, catalog, *, groups=2, standalone=True, opposite_second=False):
    from eval.contracts import ExpectedLabel, case_digest, review_context_digest
    from eval.grouping import audit_groups
    from eval.manifest import freeze_regression
    from .test_dataset_grouping import sources
    cases = []
    for group in range(groups):
        for index in range(1, 4):
            case = reviewed.model_copy(update=dict(caseId=str(UUID(int=100 + group * 3 + index)),
                split="regression", caseType="context", conversationId=f"conversation-{group}", contextIndex=index,
                question=(f"Is keeper {group} awake?" if index == 1 else "Is he awake?" if index == 2 else f"Is he waiting {group}?"),
                familyGroup=f"synthetic-family-{group}"))
            receipt = case.review.model_copy(update={"caseDigest": case_digest(case), "contextDigest": None})
            if group == 1 and opposite_second:
                receipt = receipt.model_copy(update={"expectedLabel": ExpectedLabel(kind="answer", answer="不是")})
            cases.append(case.model_copy(update={"review": receipt}))
    if standalone:
        case = reviewed.model_copy(update=dict(caseId=str(UUID(int=99)), split="regression", question="Is the boat present?"))
        cases.append(case.model_copy(update={"review": case.review.model_copy(update={"caseDigest": case_digest(case)})}))
    rows = tuple(cases)
    rows = tuple(c.model_copy(update={"review": c.review.model_copy(update={
        "contextDigest": review_context_digest(c, rows)})}) if c.caseType == "context" else c for c in rows)
    source = sources(rows)
    audit = audit_groups((), repair_cases=rows, source_digests=source, source_complete=True)
    return freeze_regression(rows, catalog=catalog, audit=audit, source_digests=source, frozen_at="2026-10-09T00:00:00Z")


class RecordingDriver:
    def __init__(self, outputs=(), *, clean=True):
        self.inputs = []
        self.outputs = tuple(outputs)
        self.clean = clean
        self.closed = False

    def decide(self, input, *, deadline):
        from app.schemas import HostResult, HostVersions
        from eval.run_contracts import DriverOutcome
        index = len(self.inputs)
        self.inputs.append(input)
        output = self.outputs[index] if index < len(self.outputs) else "不是"
        if isinstance(output, Exception): raise output
        if not isinstance(output, str): return output
        versions = HostVersions(puzzleVersion=input.puzzleVersion, ruleVersion=input.puzzle.ruleSnapshot.ruleVersion)
        if output == "reminder":
            host = HostResult(kind="reminder", chargeable=False, source="flow", reply="synthetic reminder", versions=versions)
        elif output == "error":
            host = HostResult(kind="system_error", chargeable=False, source="llm", reply="synthetic error",
                errorCode="model_quota", versions=versions)
        elif output == "win":
            host = HostResult(kind="win", chargeable=True, source="deterministic", reply="是", versions=versions)
        else:
            host = HostResult(kind="answer", answer=output, chargeable=True, source="deterministic", reply=output, versions=versions)
        return DriverOutcome(host=host, errorCode=None, modelObservations=(), modelAttemptCount=0,
            inputChars=None, contextTurnsIncluded=None, decisionAttempted=True, cleanupComplete=self.clean)

    def close(self):
        self.closed = True
        return self.clean
