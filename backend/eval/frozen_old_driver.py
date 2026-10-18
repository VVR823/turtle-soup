"""Whole archived old algorithms with owned offline transport and case budgets."""
import hashlib
import math
import random
import time
from pathlib import Path
from threading import Lock
from uuid import uuid4

from langchain_core.messages import AIMessage
from langchain_core.runnables import RunnableLambda
from app.audit_context import AttemptCollector, attempt_context
from app.baselines import digest
from app.config import Settings
from app.model_gateway import InjectedAdapter, ModelFailure, ModelGateway
from app.schemas import HostResult, HostVersions
from app.testing import FakeModel
from .catalog import validate_catalog
from .contracts import DatasetError
from .frozen_old_sources import frozen_old_source_identity, load_frozen_old_modules
from .legacy import _read_copy, checked_path
from .run_contracts import DriverOutcome, EvaluationInput, SystemSpec

ENGINE = "host-ts01-frozen-v1"
ANSWERS = ("是", "不是", "是也不是", "算是", "与此无关")


def frozen_old_system_spec(answer, *, seed=0):
    from .run_cli import _fixed_system_spec
    if type(seed) is not int or not 0 <= seed < 2**63:
        raise DatasetError("eval_driver_scope_mismatch")
    identity = frozen_old_source_identity()
    base = _fixed_system_spec("pure_llm", answer)
    root = Path(__file__).parent
    sources = ("frozen_old_driver.py", "frozen_old_sources.py", "frozen_ts01_sources/source-manifest.json")
    extra = {name: hashlib.sha256(_read_copy(checked_path(root / name))).hexdigest() for name in sources}
    old = {item["path"]: item["sha256"] for item in identity["sources"]}
    spec = base.model_copy(update={"name": "frozen_old", "engineVersion": ENGINE, "seed": seed,
        "implementationDigest": digest({"modernProducer": base.implementationDigest, "old": identity, "bridge": extra}),
        "promptDigest": digest({"protocol": "ts01-original-json-then-text",
            "sources": {name: old["backend/app/" + name + ".py"] for name in ("ai_host", "prompts", "schemas")}})})
    return SystemSpec.model_validate_json(spec.model_dump_json(warnings="error"))


class _RawCase:
    """Each old invoke gets one transport; reservations belong to the whole case."""
    def __init__(self, gateway, *, deadline, limit, clock):
        self.gateway, self.deadline, self.limit, self.clock = gateway, deadline, limit, clock
        self.count = 0
        self.input_chars = None
        self.observations = []
        self.last_code = None
        self.stopped = False
        self._lock = Lock()

    def stop(self):
        with self._lock:
            self.stopped = True
            return self.count

    def invoke(self, value):
        # A second old invoke means the original first parser rejected output.
        if self.observations and self.observations[-1].status == "succeeded":
            self.observations[-1] = self.observations[-1].model_copy(
                update={"status": "failed", "errorCode": "model_output_invalid"})
            self.last_code = "model_output_invalid"
        try:
            messages = value.to_messages() if hasattr(value, "to_messages") else value
            if type(messages) is not list or not messages:
                raise ModelFailure("model_output_invalid")
            payload = [{"role": "system" if m.type == "system" else "user" if m.type == "human" else "assistant",
                "content": m.content} for m in messages]
            if any(type(m["content"]) is not str for m in payload):
                raise ModelFailure("model_output_invalid")
            chars = sum(len(m["content"]) for m in payload)
            if chars > 8000:
                raise ModelFailure("context_too_large")
            self.input_chars = max(self.input_chars or 0, chars)
            if self.clock() >= self.deadline:
                raise ModelFailure("model_timeout")
            with self._lock:
                if self.stopped:
                    raise ModelFailure("model_cancelled")
                if self.count >= self.limit:
                    raise ModelFailure(self.last_code or "model_policy_unknown")
            collector = AttemptCollector(str(uuid4()), clock=self.clock, traffic_class="synthetic")
            def reserve(ordinal, local_deadline):
                with self._lock:
                    if self.stopped:
                        raise ModelFailure("model_cancelled")
                    if self.clock() >= min(self.deadline, local_deadline):
                        raise ModelFailure("model_timeout")
                    if self.count >= self.limit:
                        raise ModelFailure(self.last_code or "model_policy_unknown")
                    self.count += 1
            try:
                with attempt_context(collector):
                    raw = self.gateway.invoke(payload, deadline=self.deadline, max_attempts=1,
                        before_attempt=reserve, response_contract="legacy_raw")
                self.last_code = None
                return AIMessage(content=raw)
            finally:
                calls = collector.finish(status_code=None, method="OTHER", route_template="unmatched",
                    response_started=False, disconnected=False).details.modelCalls
                for call in calls:
                    self.observations.append(call.model_copy(update={"ordinal": len(self.observations)+1}))
        except ModelFailure as error:
            self.last_code = error.code
            raise


class FrozenOldDriver:
    name = "frozen_old"

    def __init__(self, *, settings, fake_model, clock=time.monotonic):
        if (not isinstance(settings, Settings) or settings.TESTING is not True
            or settings.ALLOW_REAL_MODEL is not False or settings.LOAD_RUNTIME_PUZZLES is not False
            or settings.LLM_PROVIDER != "fake" or not isinstance(fake_model, FakeModel)):
            raise DatasetError("eval_offline_driver_required")
        self.clock = clock
        self.spec = frozen_old_system_spec(fake_model.answer)
        self.modules = load_frozen_old_modules()
        self._decision_lock = Lock()
        self._closed = False
        self._seed = None
        try:
            old_settings = self.modules.config.Settings.for_test(settings.DATA_DIR)
            self.runtime = self.modules.runtime.Runtime(old_settings)
            # Discard old private exception prints in this owner only, never globally.
            self.modules.host.print = lambda *args, **kwargs: None
            self.gateway = ModelGateway(adapter_factory=lambda: InjectedAdapter(fake_model), max_active=1, clock=clock)
        except BaseException:
            self.modules.close()
            raise

    def decide(self, input, *, deadline):
        try:
            input = EvaluationInput.model_validate_json(input.model_dump_json(warnings="error"))
            validate_catalog((input.puzzle,))
            fixed = self.spec.model_copy(update={"seed": input.system.seed, "budget": input.system.budget})
            if input.system != fixed:
                raise DatasetError("eval_driver_scope_mismatch")
            started = self.clock()
            if (type(started) not in {int, float} or not math.isfinite(started)
                or type(deadline) not in {int, float} or not math.isfinite(deadline)):
                raise DatasetError("eval_clock_invalid")
            deadline = min(deadline, started + input.system.budget.caseTimeoutSeconds)
        except DatasetError:
            raise
        except Exception:
            raise DatasetError("eval_driver_input_invalid") from None
        def unavailable(code, *, clean):
            return DriverOutcome(host=None, errorCode=code, modelObservations=(), modelAttemptCount=0,
                inputChars=None, contextTurnsIncluded=None, decisionAttempted=False, cleanupComplete=clean)
        if self._closed or self.gateway.snapshot()["active"] or not self._decision_lock.acquire(blocking=False):
            return unavailable("driver_unavailable", clean=False)
        try:
            if self._closed:
                return unavailable("driver_unavailable", clean=False)
            if self._seed is None:
                self._seed = input.system.seed
                self.modules.host.random = random.Random(self._seed)
            elif self._seed != input.system.seed:
                raise DatasetError("eval_driver_scope_mismatch")
            if self.clock() >= deadline:
                return unavailable("budget_exhausted", clean=True)
            raw_case = _RawCase(self.gateway, deadline=deadline,
                limit=input.system.budget.modelAttemptsPerCase, clock=self.clock)
            self.runtime.model = RunnableLambda(raw_case.invoke)
            history = [m for turn in input.history[-12:] for m in (
                {"role": "user", "content": turn.question}, {"role": "host", "content": turn.answer})]
            soup = self.modules.schemas.Soup.model_validate_json(input.puzzle.soupJson)
            versions = HostVersions(puzzleVersion=input.puzzleVersion, ruleVersion=input.puzzle.ruleSnapshot.ruleVersion,
                engineVersion=ENGINE, normalizationVersion=input.system.normalizationVersion)
            host, code = None, None
            try:
                with self.modules.runtime.runtime_context(self.runtime):
                    result = self.modules.host.handle_host_response(soup, history, input.question)
                # No hard CPU preemption promise; a late result still cannot
                # masquerade as a successful equal-budget decision.
                if self.clock() >= deadline:
                    code = raw_case.last_code or "budget_exhausted"
                elif (type(result) is not dict or type(result.get("reply")) is not str
                    or not result["reply"] or len(result["reply"]) > 2000):
                    code = "invalid_output"
                elif any(result.get(flag) for flag in ("is_win", "is_reveal", "is_giveup")):
                    code = "unexpected_host_kind"
                elif result["reply"] in ANSWERS or (result.get("matched_checkpoint") == "always_yes"
                    and result["reply"] in ("……是", "嗯，是", "是。")):
                    answer = result["reply"] if result["reply"] in ANSWERS else "是"
                    host = HostResult(kind="answer", answer=answer, chargeable=True, source="legacy",
                        reply=result["reply"], versions=versions)
                elif raw_case.last_code is not None:
                    code = raw_case.last_code
                elif raw_case.count == 0:
                    host = HostResult(kind="reminder", chargeable=False, source="flow",
                        reply=result["reply"], versions=versions)
                else:
                    code = "model_output_invalid"
            except KeyboardInterrupt:
                raw_case.stop()
                self._closed = True
                code = "cancelled"
                try:
                    self.gateway.close(wait_seconds=2)
                except (Exception, KeyboardInterrupt):
                    pass
            except Exception:
                code = raw_case.last_code or "driver_error"
            # Seal reservations under their granting lock before exporting a
            # terminal ledger. A timed-out worker still owns its gateway slot,
            # but cannot add reservations after this immutable outcome.
            model_count = raw_case.stop()
            state = self.gateway.snapshot()
            return DriverOutcome(host=host, errorCode=code, modelObservations=tuple(raw_case.observations),
                modelAttemptCount=model_count, inputChars=raw_case.input_chars,
                contextTurnsIncluded=min(5, len(input.history)) if model_count else None,
                decisionAttempted=True, cleanupComplete=state["active"] == 0 and state["cleanup_failed"] == 0)
        finally:
            self._decision_lock.release()

    def close(self):
        self._closed = True
        state = self.gateway.close(wait_seconds=2)
        if state["active"] or state["cleanup_failed"] or not self._decision_lock.acquire(blocking=False):
            return False
        try:
            self.runtime.closed = True
            self.runtime.llm_cache.clear()
            self.runtime.host_cache.clear()
            self.runtime.model = None
            return self.modules.close()
        finally:
            self._decision_lock.release()
