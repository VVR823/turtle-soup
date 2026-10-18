"""Deterministic model transport for isolated tests, never a quality judge."""
import json
from threading import Lock

from langchain_core.messages import AIMessage
from langchain_core.runnables import RunnableLambda


class FakeModel(RunnableLambda):
    """Return a scripted output. Does not read expected answers or call a provider."""

    def __init__(self, answer: str = "与此无关"):
        if answer not in ("是", "不是", "是也不是", "算是", "与此无关"):
            raise ValueError("FakeModel answer must be a five-class answer")
        self.answer = answer
        self.calls = []
        self._calls_lock = Lock()
        super().__init__(self._respond)

    def _respond(self, messages):
        with self._calls_lock:
            self.calls.append(messages)
        return AIMessage(content=json.dumps({
            "reasoning": "Synthetic offline fixture, not evidence of model quality.",
            "answer": self.answer,
        }, ensure_ascii=False))


class SyntheticRepairModel(FakeModel):
    """Owned UI transport branches on actual tool results, never reads corpus labels."""
    def __init__(self, draft):
        self.draft = draft
        super().__init__()

    def _respond(self, messages):
        # The online host uses dict messages; the Agent uses LangChain messages.
        system = getattr(messages[0], "content", None) if messages else None
        if not isinstance(system, str) or not system.startswith("Repair rules within server limits."):
            return super()._respond(messages)
        from .baselines import strict_json
        payload = strict_json(messages[1].content)
        completed = [step["result"] for step in payload["steps"] if step["state"] == "completed"
            and step["action"].get("action") != "model_decision"]
        if not completed:
            action = dict(action="tool", tool="run_regression", arguments=dict(draft=self.draft.model_dump(mode="json")))
        elif "reportId" in completed[-1]:
            report = completed[-1]
            action = dict(action="tool", tool="save_candidate_rule", arguments=dict(draft=self.draft.model_dump(mode="json"),
                regressionReportId=report["reportId"])) if report["status"] == "complete" else dict(
                    action="finish", needsHumanReason="Actual synthetic regression is incomplete or has counterexamples")
        else:
            action = dict(action="finish", candidateId=completed[-1]["id"])
        with self._calls_lock:
            self.calls.append(messages)
        return AIMessage(content=json.dumps(action, ensure_ascii=False))
