"""Fixed bounded safety probes; missing reviewed corpus never becomes a pass.

An explicit server-selected verified dev/regression corpus can additionally
exercise the unapproved preview. It never manufactures labels or calls live
models; mechanical success still does not grant human approval/publication.
"""
import math
import time
from pathlib import Path
from threading import Event
from uuid import NAMESPACE_URL, uuid5

from langchain_core.messages import AIMessage

from .. import baselines
from ..audit_context import attempt_context
from ..model_gateway import InjectedAdapter, ModelFailure, ModelGateway
from ..question_normalization import normalize_exact_question
from ..runtime import Runtime, runtime_context
from ..testing import FakeModel
from .contracts import (AgentError, ExecutionIdentity, RegressionCaseResult, RegressionReport,
    checked_draft, checked_model, draft_digest, parse_tool_action)
from .store import RunRecord
from .preview import CandidatePreview
from .validation import validate_candidate
from .source_identity import verified_process_sources

_POLICY = "repair-fixed-safety-v1"
_PROBES = ("closed-tool-json", "fact-scope", "exact-negation", "fake-protocol", "malformed-protocol", "reviewed-corpus")
_SOURCES = ("agents/regression.py", "agents/contracts.py", "agents/store.py", "agents/tools.py",
    "agents/validation.py", "agents/tool_contracts.py", "model_gateway.py", "testing.py",
    "baselines.py", "rule_contract.py", "host_evidence.py", "host_rules.py", "question_normalization.py",
    "agents/preview.py", "ai_host.py", "runtime.py", "host_cache.py", "host_context.py", "schemas.py",
    "rag.py", "prompts.py", "audit_context.py", "audit_events.py", "audit_store.py", "task_context.py",
    "feedback_contract.py", "feedback_store.py", "db.py", "migrations.py", "config.py", "paths.py",
    "model_admission.py", "rate_limit.py", "rate_policy.py", "request_guards.py", "request_lifecycle.py",
    "scoring.py", "__init__.py", "agents/__init__.py", "../eval/__init__.py", "../eval/legacy.py",
    "../eval/catalog.py", "../eval/contracts.py", "../eval/manifest.py",
    "../eval/grouping.py", "../eval/inventory.py", "../eval/proofs.py", "agents/source_identity.py",
    "agents/decision_contracts.py", "agents/agent_prompt.py", "agents/repair_agent.py", "agents/worker.py", "main.py",
    "agents/admin_contracts.py", "routers/agent_runs.py", "request_contract.py",
    "candidate_review.py", "candidate_review_contracts.py", "rule_publication.py", "routers/admin_candidates.py")


class _MalformedProtocol:
    """A fixed inert protocol counterexample, never supplied by the model."""
    def invoke(self, messages):
        return AIMessage(content='{"answer":"是","answer":"不是","reasoning":"Synthetic duplicate"}')


class _BoundedGateway:
    """Clamp the original host's 45s request to this owned fixed-suite budget."""
    def __init__(self, remaining):
        self.remaining = remaining
        self.gateway = ModelGateway(adapter_factory=lambda: InjectedAdapter(FakeModel()), max_active=1)

    def invoke(self, messages, *, deadline, **kwargs):
        return self.gateway.invoke(messages, deadline=min(deadline,
            time.monotonic() + max(0.0, self.remaining())), max_attempts=1,
            cancelled=kwargs.get("cancelled"), traffic_class="agent")

    def close(self):
        return self.gateway.close(wait_seconds=min(0.1, max(0.0, self.remaining())))


class FixedRegression:
    def __init__(self, runtime: Runtime, *, corpus=None, clock=time.monotonic, utc_clock=time.time):
        if not isinstance(runtime, Runtime) or not callable(clock) or not callable(utc_clock):
            raise TypeError("Explicit runtime and server clocks required")
        self.runtime, self.clock, self.utc_clock = runtime, clock, utc_clock
        self.corpus, self._cases = None, ()
        if corpus is not None:
            from eval.manifest import load_repair_corpus, verify_frozen_dataset
            try:
                self.corpus = verify_frozen_dataset(corpus)
                self._cases = load_repair_corpus(self.corpus)
                if not 1 <= len(self._cases) <= 100:
                    raise ValueError("Fixed corpus limit")
            except Exception:
                raise AgentError("agent_corpus_invalid", 422) from None
        # Only registered code assets are read; no model-controlled paths,
        # player data, dotenv, database, gateway or application initialization.
        self.suite_manifest_digest = self._suite_identity()

    def _suite_identity(self):
        try:
            root = Path(__file__).resolve().parent.parent
            sources = verified_process_sources(root, _SOURCES)
            return baselines.digest(dict(policy=_POLICY, probes=_PROBES,
                sources=sources, corpus=self.corpus.manifest.datasetDigest if self.corpus else None))
        except AgentError:
            raise
        except Exception:
            raise AgentError("agent_suite_unavailable", 503) from None

    @staticmethod
    def _time(clock):
        value = clock()
        if type(value) not in (int, float) or not math.isfinite(value) or value < 0:
            raise AgentError("agent_clock_invalid", 503)
        return float(value)

    def run(self, draft, *, run, identity, soup, rule_snapshot):
        started = self._time(self.clock)
        utc_started = self._time(self.utc_clock)
        draft = checked_draft(draft)
        run = checked_model(RunRecord, run, max_bytes=1048576)
        identity = checked_model(ExecutionIdentity, identity)
        if (self.runtime.closed or run.state != "running" or identity.runId != run.id
            or identity.leaseToken != run.leaseToken
            or (run.manifest.suiteManifestDigest is not None
                and run.manifest.suiteManifestDigest != self.suite_manifest_digest)):
            raise AgentError("agent_regression_scope_invalid", 409)
        conflict = validate_candidate(draft, context=run.manifest.context, soup=soup, rule_snapshot=rule_snapshot)
        if self.corpus is not None:
            # The sealed corpus is explicit server input, not a model-chosen
            # filename. Revalidate copies and every full catalog member.
            from eval.manifest import load_repair_corpus
            from eval.catalog import validate_catalog
            from eval.contracts import EvalPuzzle
            try:
                cases = load_repair_corpus(self.corpus)
                catalog = validate_catalog(tuple(EvalPuzzle.model_validate_json(baselines.canonical_json(p))
                    for p in baselines.strict_json(self.corpus.catalogJson)))
                if (len(catalog) != 1 or catalog[0].soupId != soup.id
                    or catalog[0].soupJson != baselines.canonical_json(soup.model_dump(mode="json"))
                    or catalog[0].ruleSnapshot != rule_snapshot
                    or any(c.soupId != soup.id or c.puzzleVersion != draft.puzzleVersion for c in cases)):
                    raise ValueError("Corpus source mismatch")
            except Exception:
                raise AgentError("agent_corpus_invalid", 422) from None
        else:
            cases = ()
        # A reused server object or hot-edited checkout must not run new assets
        # under a fingerprint captured when the object was constructed.
        if self._suite_identity() != self.suite_manifest_digest:
            raise AgentError("agent_suite_changed", 409)
        stop = started + min(5.0, max(0.0, run.checkpoint.deadlineAt - utc_started))
        results, cleanup = [], True

        def remaining():
            return min(stop - self._time(self.clock), run.checkpoint.deadlineAt - self._time(self.utc_clock))

        def closed_tool():
            for raw in ('{"action":"tool","tool":"shell","arguments":{}}',
                '{"action":"tool","tool":"sql","arguments":{}}',
                '{"action":"tool","tool":"publish","arguments":{}}',
                '{"action":"tool","action":"finish","tool":"run_regression","arguments":{}}'):
                try:
                    parse_tool_action(raw)
                except AgentError:
                    continue
                return False
            return True

        def fact_scope():
            try:
                validate_candidate(draft.model_copy(update={"factIds": ("f1:" + "e" * 64,)}),
                    context=run.manifest.context, soup=soup, rule_snapshot=rule_snapshot)
            except AgentError:
                return True
            return False

        def protocol(*, malformed=False):
            nonlocal cleanup
            owned = ModelGateway(adapter_factory=lambda: InjectedAdapter(
                _MalformedProtocol() if malformed else FakeModel()), max_active=1)
            try:
                try:
                    with attempt_context(None):
                        result = owned.invoke([], deadline=time.monotonic() + max(0.0, remaining()),
                            max_attempts=1, cancelled=Event(), traffic_class="agent")
                    return not malformed and result.answer == "与此无关"
                except ModelFailure as error:
                    return malformed and error.code == "model_output_invalid"
            finally:
                state = owned.close(wait_seconds=min(0.1, max(0.0, remaining())))
                cleanup = cleanup and state.get("closed") is True and state.get("active") == 0

        safety = (closed_tool, fact_scope,
            lambda: normalize_exact_question("小明是凶手吗？") != normalize_exact_question("小明不是凶手吗？"),
            lambda: protocol(), lambda: protocol(malformed=True))
        plan = [(str(uuid5(NAMESPACE_URL, _POLICY + "/" + _PROBES[index])), "fixed_safety", probe, "probe_failed")
            for index, probe in enumerate(safety)]
        owned, gateway, histories = None, None, {}
        preview = CandidatePreview(draft, context=run.manifest.context, soup=soup, rule_snapshot=rule_snapshot) \
            if cases and conflict.status in {"no_known_conflict", "reviewable_replace"} else None

        def decision(case):
            nonlocal owned, gateway
            if preview is None:
                return False
            if owned is None:
                owned = Runtime(self.runtime.settings, model=FakeModel(), soups=[soup])
                gateway = _BoundedGateway(remaining)
                owned.model_gateway = gateway
            from ..ai_host import handle_host_response
            from ..schemas import HostVersions
            history = histories.setdefault(case.conversationId, []) if case.caseType == "context" else []
            with runtime_context(owned), attempt_context(None):
                baseline = handle_host_response(soup, history, case.question,
                    versions=HostVersions(puzzleVersion=draft.puzzleVersion, ruleVersion=draft.baseRuleVersion),
                    rule_snapshot=rule_snapshot)
            result = preview.apply(case.question, baseline)
            if result.kind == "system_error":
                raise AgentError("agent_regression_incomplete", 409)
            if case.caseType == "context":
                # Actual preceding decisions, never expected/gold history.
                history.extend([dict(role="user", content=case.question), dict(role="host", content=result.reply,
                    answer=result.answer, kind=result.kind, is_free_reminder=not result.chargeable)])
            label = case.review.expectedLabel
            return result.kind == label.kind and (label.kind != "answer" or result.answer == label.answer)

        # Preserve context order independently of UUID/source presentation.
        ordered = sorted(cases, key=lambda c: (c.conversationId or c.caseId, c.contextIndex or 0))
        plan.extend((case.caseId, "dev_regression", lambda c=case: decision(c), "counterexample") for case in ordered)
        candidate_cases = [c for c in cases if normalize_exact_question(c.question) == draft.canonicalQuestionKey
            and c.review.expectedLabel.kind == "answer"]
        unrelated = [c for c in cases if normalize_exact_question(c.question) != draft.canonicalQuestionKey]
        missing = not cases or not candidate_cases or (draft.operation == "replace" and not unrelated)
        if missing:
            plan.append((str(uuid5(NAMESPACE_URL, _POLICY + "/reviewed-corpus")), "dev_regression", lambda: False, "needs_corpus"))
        try:
            for case_id, suite, probe, failure_code in plan:
                code = "deadline" if remaining() <= 0 else None
                if code is None:
                    try:
                        code = "passed" if probe() else failure_code
                    except Exception:
                        code = "probe_failed"
                    if remaining() <= 0:
                        code = "deadline"
                results.append(RegressionCaseResult(caseId=case_id, suite=suite, passed=code == "passed", code=code))
                if code == "deadline" or not cleanup:
                    break
        finally:
            if gateway is not None:
                state = gateway.close()
                cleanup = cleanup and state.get("closed") is True and state.get("active") == 0
                owned.closed = True
        # Source edits during probes also cannot be signed as a clean result.
        if self._suite_identity() != self.suite_manifest_digest:
            raise AgentError("agent_suite_changed", 409)
        elapsed = max(0.0, self._time(self.clock) - started)
        status = "failed" if any(r.code in {"probe_failed", "counterexample"} for r in results) else "incomplete"
        if (not missing and len(results) == len(plan) and all(r.passed for r in results)
            and cleanup and elapsed <= 5.0):
            status = "complete"
        return checked_model(RegressionReport, RegressionReport(reportId=identity.operationKey, runId=run.id,
            draftDigest=draft_digest(draft), contextDigest=run.manifest.contextDigest,
            suiteManifestDigest=self.suite_manifest_digest, puzzleVersion=draft.puzzleVersion,
            baseRuleVersion=draft.baseRuleVersion, evidenceKind="synthetic_fixture" if cases
                and all(c.authorRole == "synthetic" for c in cases) else "deterministic_regression", status=status,
            inputCaseCount=len(plan), attemptedCaseCount=len(results), passedCaseCount=sum(r.passed for r in results),
            elapsedSeconds=elapsed, truncated=False, cleanupConfirmed=cleanup, caseResults=tuple(results)))
