"""Owned offline adapters call the actual host, never an expected-label oracle."""
import time
import math
from threading import Lock
from uuid import uuid4

from app.audit_context import AttemptCollector, attempt_context
from app.config import Settings
from app.model_gateway import InjectedAdapter, ModelFailure, ModelGateway
from app.runtime import Runtime, runtime_context
from app.schemas import HOST_ENGINE_VERSION, HostVersions, Soup
from app.testing import FakeModel
from .catalog import validate_catalog
from .contracts import DatasetError
from .run_contracts import DriverOutcome, EvaluationInput


class BudgetedGateway:
    """One host model decision; count reservations before transport, not observations."""
    def __init__(self, gateway, *, deadline, attempt_limit, collector, clock=time.monotonic):
        if (type(deadline) not in {int, float} or not math.isfinite(deadline)
            or type(attempt_limit) is not int or not 1 <= attempt_limit <= 2):
            raise DatasetError("eval_budget_invalid")
        self.gateway, self.deadline, self.attempt_limit = gateway, deadline, attempt_limit
        self.collector, self.clock = collector, clock
        self._lock = Lock(); self._count = 0; self._invoked = False; self.input_chars = None; self._cancelled = False

    @property
    def attempt_count(self):
        with self._lock: return self._count

    def stop_reservations(self):
        with self._lock: self._cancelled = True

    def invoke(self, messages, *, deadline, max_attempts=2, cancelled=None, traffic_class="online", before_attempt=None):
        if type(deadline) not in {int, float} or not math.isfinite(deadline): raise ModelFailure("model_timeout")
        if type(max_attempts) is not int or not 1 <= max_attempts <= 2: raise ModelFailure("model_policy_unknown")
        with self._lock:
            if self._invoked: raise ModelFailure("model_policy_unknown")
            self._invoked = True
        if (type(messages) is not list or not messages or any(type(m) is not dict
            or type(m.get("content")) is not str for m in messages)):
            raise ModelFailure("model_output_invalid")
        chars = sum(len(m["content"]) for m in messages)
        if chars > 8000: raise ModelFailure("context_too_large")
        self.input_chars = chars
        effective_deadline = min(deadline, self.deadline)
        def reserve(ordinal, local_deadline):
            with self._lock:
                if self._cancelled: raise ModelFailure("model_cancelled")
                if self._count >= self.attempt_limit: raise ModelFailure("model_policy_unknown")
                self._count += 1
            if before_attempt is not None: before_attempt(ordinal, local_deadline)
        return self.gateway.invoke(messages, deadline=effective_deadline, max_attempts=min(max_attempts, self.attempt_limit),
            cancelled=cancelled, traffic_class=traffic_class, before_attempt=reserve,
            response_contract="host_judgment_json")

    def close(self, *, wait_seconds=2):
        return self.gateway.close(wait_seconds=wait_seconds)


class PureLLMDriver:
    name = "pure_llm"

    def __init__(self, *, settings, fake_model, clock=time.monotonic):
        if (not isinstance(settings, Settings) or settings.TESTING is not True
            or settings.ALLOW_REAL_MODEL is not False or settings.LOAD_RUNTIME_PUZZLES is not False
            or settings.LLM_PROVIDER != "fake" or not isinstance(fake_model, FakeModel)):
            raise DatasetError("eval_offline_driver_required")
        self.clock = clock
        self.runtime = Runtime(settings, model=fake_model)
        self.gateway = ModelGateway(adapter_factory=lambda: InjectedAdapter(fake_model), max_active=1, clock=clock)
        self.runtime.model_gateway = self.gateway

    def decide(self, input, *, deadline):
        from app.ai_host import call_llm, handle_host_response
        try:
            started = self.clock()
            if type(started) not in {int, float} or not math.isfinite(started): raise DatasetError("eval_clock_invalid")
            input = EvaluationInput.model_validate_json(input.model_dump_json(warnings="error"))
            validate_catalog((input.puzzle,))
            if (input.system.name != self.name or input.system.providerId != "fake"
                or input.system.engineVersion != HOST_ENGINE_VERSION):
                raise DatasetError("eval_driver_scope_mismatch")
            if type(deadline) not in {int, float} or not math.isfinite(deadline): raise DatasetError("eval_clock_invalid")
            deadline = min(deadline, started + input.system.budget.caseTimeoutSeconds)
        except DatasetError: raise
        except Exception: raise DatasetError("eval_driver_input_invalid") from None
        if self.runtime.closed or self.gateway.snapshot()["active"]:
            return DriverOutcome(host=None, errorCode="driver_unavailable", modelObservations=(), modelAttemptCount=0,
                inputChars=None, contextTurnsIncluded=None, decisionAttempted=False, cleanupComplete=False)
        if self.clock() >= deadline:
            return DriverOutcome(host=None, errorCode="budget_exhausted", modelObservations=(), modelAttemptCount=0,
                inputChars=None, contextTurnsIncluded=None, decisionAttempted=False, cleanupComplete=True)
        collector = AttemptCollector(str(uuid4()), clock=self.clock, traffic_class="synthetic")
        budgeted = BudgetedGateway(self.gateway, deadline=deadline,
            attempt_limit=input.system.budget.modelAttemptsPerCase, collector=collector, clock=self.clock)
        self.runtime.model_gateway = budgeted
        versions = HostVersions(puzzleVersion=input.puzzleVersion, ruleVersion=input.puzzle.ruleSnapshot.ruleVersion,
            engineVersion=input.system.engineVersion, normalizationVersion=input.system.normalizationVersion)
        history = [item for turn in input.history for item in (
            {"role": "user", "content": turn.question}, {"role": "host", "content": turn.answer, "answer": turn.answer, "kind": "answer"})]
        soup = Soup.model_validate_json(input.puzzle.soupJson)
        host, code = None, None
        try:
            with runtime_context(self.runtime), attempt_context(collector):
                if self.name == "new_system":
                    host = handle_host_response(soup, history, input.question, versions=versions, rule_snapshot=input.puzzle.ruleSnapshot)
                else:
                    # Existing call_llm cannot select versions. Program owns the pinned input/renderer scope.
                    host = call_llm(soup, history, input.question, versions=versions).model_copy(update={"versions": versions})
        except KeyboardInterrupt:
            code = "cancelled"
            budgeted.stop_reservations()
            # Freeze owned reservations before harvesting observations; stop
            # retries and request actual owner cleanup, not remote termination.
            try: self.gateway.close(wait_seconds=2)
            except (Exception, KeyboardInterrupt): pass
        except Exception:
            code = "driver_error"
        observations = collector.finish(status_code=None, method="OTHER", route_template="unmatched",
            response_started=False, disconnected=False).details.modelCalls
        state = self.gateway.snapshot()
        return DriverOutcome(host=host, errorCode=code, modelObservations=observations, modelAttemptCount=budgeted.attempt_count,
            inputChars=budgeted.input_chars, contextTurnsIncluded=None, decisionAttempted=True,
            cleanupComplete=state["active"] == 0 and state["cleanup_failed"] == 0)

    def close(self):
        self.runtime.closed = True
        state = self.gateway.close(wait_seconds=2)
        self.runtime.deterministic_host_cache.clear()
        self.runtime.host_cache.clear(); self.runtime.llm_cache.clear()
        return state["closed"] is True and state["active"] == 0 and state["cleanup_failed"] == 0


class NewSystemDriver(PureLLMDriver):
    name = "new_system"


class UnavailableDriver:
    """Own no transport; retain a planned but unattempted decision explicitly."""
    def decide(self, input, *, deadline):
        return DriverOutcome(host=None, errorCode="driver_unavailable", modelObservations=(), modelAttemptCount=0,
            inputChars=None, contextTurnsIncluded=None, decisionAttempted=False, cleanupComplete=True)

    def close(self):
        return True


class UnavailableOldDriver(UnavailableDriver):
    """An explicitly unavailable old executor, never a renamed baseline substitute."""
