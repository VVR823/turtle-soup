"""Bounded published-version observations; never a candidate preview or live model."""
import asyncio
from contextlib import contextmanager
from dataclasses import replace
import math
from pathlib import Path
import time
from uuid import uuid4

from . import baselines, migrations
from .agents.contracts import AgentError, StrictAgentModel
from .agents.regression import _SOURCES
from .agents.source_identity import verified_process_sources
from .agents.store import AgentStore
from .ai_host import handle_host_response
from .audit_context import attempt_context
from .audit_events import CanonicalId
from .post_publication_contracts import (ObservedCase, PostPublicationError, PostPublicationPlan,
    PostPublicationResult, checked_observation)
from .post_publication_source import PostPublicationSourceResolver
from .post_publication_store import PostPublicationStore
from .rule_contract import RuleVersion, read_rule_snapshot
from .runtime import Runtime, _verified_repair_corpus, runtime_context
from .schemas import HostVersions


class ObservationRequest(StrictAgentModel):
    operationKey: CanonicalId
    candidateId: CanonicalId
    publishedRuleVersion: RuleVersion


class _ProviderDisabled(Exception):
    pass


class _NoProviderRuntime(Runtime):
    def get_model_gateway(self):
        # call_llm only catches ContextLimitError/ModelFailure. This sentinel
        # escapes to the observer; neither a transport nor a fake answer exists.
        raise _ProviderDisabled()


_EXTRA_SOURCES = ('post_publication_regression.py', 'post_publication_source.py',
    'post_publication_store.py', 'post_publication_contracts.py', 'post_publication_schema.py',
    'routers/admin_regressions.py')


class PostPublicationRegression:
    def __init__(self, runtime, *, clock=time.monotonic, utc_clock=time.time):
        if not isinstance(runtime, Runtime) or not callable(clock) or not callable(utc_clock):
            raise TypeError('Explicit runtime and server clocks required')
        self.runtime, self.clock, self.utc_clock = runtime, clock, utc_clock
        self.source = PostPublicationSourceResolver(runtime)
        self.reader = AgentStore(runtime, authorize_create=lambda context: False)
        self.store = PostPublicationStore(runtime, verify_source=self._publication_fence,
            verify_fresh=self._fresh_input_fence, clock=utc_clock)

    @contextmanager
    def _reader_transaction(self):
        try:
            with self.reader._transaction(write=False) as conn:
                try:
                    yield conn
                except PostPublicationError as error:
                    raise AgentError(error.code, error.status) from None
        except AgentError as error:
            code = error.code if error.code.startswith('post_publication_') else 'post_publication_unavailable'
            raise PostPublicationError(code, error.status) from None

    @staticmethod
    def _time(clock):
        value = clock()
        if type(value) not in (int, float) or not math.isfinite(value) or not 0 <= value < 1e15:
            raise PostPublicationError('post_publication_clock_invalid', 503)
        return float(value)

    def _publication_fence(self, conn, plan):
        source = self.source.load(conn, plan.candidateId, plan.publishedRuleVersion)
        return all(getattr(source, name) == getattr(plan, name) for name in
            ('candidateId', 'publicationOperationKey', 'publicationProofDigest', 'soupId',
             'puzzleVersion', 'publishedRuleVersion', 'publishedAt'))

    def _inputs(self, conn, request):
        from eval.manifest import load_repair_corpus
        source = self.source.load(conn, request.candidateId, request.publishedRuleVersion)
        soup = baselines.session_soup(conn, source.puzzleVersion)
        snapshot = read_rule_snapshot(conn, source.puzzleVersion, source.publishedRuleVersion)
        try:
            corpus = _verified_repair_corpus(self.runtime.repair_corpus,
                testing=self.runtime.settings.TESTING, soups=[soup])
            if corpus is None:
                raise ValueError('Missing server corpus')
            cases = load_repair_corpus(corpus)
            if any(case.soupId != source.soupId or case.puzzleVersion != source.puzzleVersion for case in cases):
                raise ValueError('Case scope mismatch')
            ordered = tuple(sorted(cases, key=lambda case: (case.conversationId or case.caseId, case.contextIndex or 0)))
            return source, soup, snapshot, corpus, ordered
        except Exception:
            raise PostPublicationError('post_publication_corpus_invalid', 422) from None

    @staticmethod
    def _suite(corpus):
        root = Path(__file__).resolve().parent
        sources = verified_process_sources(root, tuple(dict.fromkeys((*_SOURCES, *_EXTRA_SOURCES))))
        return baselines.digest(dict(policy='published-host-no-provider-v1', sources=sources,
            datasetDigest=corpus.manifest.datasetDigest))

    def _live_inputs(self, plan, request):
        with self._reader_transaction() as conn:
            source, soup, snapshot, corpus, cases = self._inputs(conn, request)
            if (source.publicationProofDigest != plan.publicationProofDigest
                or corpus.manifest.datasetDigest != plan.datasetDigest or self._suite(corpus) != plan.suiteManifestDigest):
                raise PostPublicationError('post_publication_source_changed', 409)
            return soup, snapshot, corpus, cases

    def _fresh_input_fence(self, conn, plan):
        # Only a newly admitted plan/new terminal result takes this fence.
        # Historical reads/acks still verify publication/privacy authority,
        # but cannot be reinterpreted using a replacement server dataset.
        from eval.contracts import case_digest
        request = ObservationRequest(operationKey=plan.operationKey, candidateId=plan.candidateId,
            publishedRuleVersion=plan.publishedRuleVersion)
        source, _, _, corpus, cases = self._inputs(conn, request)
        return (source.publicationProofDigest == plan.publicationProofDigest
            and corpus.manifest.datasetDigest == plan.datasetDigest
            and self._suite(corpus) == plan.suiteManifestDigest
            and tuple((case.caseId, case_digest(case)) for case in cases)
                == tuple((case.caseId, case.caseDigest) for case in plan.cases))

    def run(self, request):
        request = checked_observation(ObservationRequest, request)
        try:
            old = self.store.get(request.operationKey)
        except PostPublicationError as error:
            if error.code != 'post_publication_not_found':
                raise
        else:
            if (old.plan.candidateId, old.plan.publishedRuleVersion) != (request.candidateId, request.publishedRuleVersion):
                raise PostPublicationError('post_publication_conflict', 409)
            return old  # Historical acknowledgement is not fresh execution.
        started, utc_started = self._time(self.clock), self._time(self.utc_clock)
        with self._reader_transaction() as conn:
            migrations.verify_schema(conn, required_version=5)
            source, soup, snapshot, corpus, cases = self._inputs(conn, request)
            suite = self._suite(corpus)
        from eval.contracts import case_digest
        synthetic = any(case.authorRole == 'synthetic' or case.origin == 'public_synthetic' for case in cases)
        plan = PostPublicationPlan(runId=str(uuid4()), operationKey=request.operationKey,
            candidateId=source.candidateId, publicationOperationKey=source.publicationOperationKey,
            publicationProofDigest=source.publicationProofDigest, soupId=source.soupId,
            puzzleVersion=source.puzzleVersion, publishedRuleVersion=source.publishedRuleVersion,
            publishedAt=source.publishedAt, startedAt=utc_started, deadlineAt=utc_started + 5,
            trafficClass='test' if self.runtime.settings.TESTING else source.trafficClass,
            evidenceKind='synthetic_fixture' if synthetic else 'deterministic_regression',
            datasetDigest=corpus.manifest.datasetDigest, suiteManifestDigest=suite,
            cases=tuple(dict(caseId=case.caseId, caseDigest=case_digest(case)) for case in cases))
        record, created = self.store.reserve(plan)
        if not created:
            return record
        # Recheck code/corpus/publication after admission, before any host probe.
        soup, snapshot, _, cases = self._live_inputs(plan, request)
        owned = _NoProviderRuntime(replace(self.runtime.settings, ENABLE_TRACE=False), model=None, soups=[soup])
        results, histories, termination, cleanup = [], {}, 'finished', False
        versions = HostVersions(puzzleVersion=plan.puzzleVersion, ruleVersion=plan.publishedRuleVersion)
        def remaining():
            budget = min(started + 5 - self._time(self.clock), plan.deadlineAt - self._time(self.utc_clock))
            with self.runtime.lock:
                if self.runtime.closed:
                    raise PostPublicationError('post_publication_unavailable', 503)
            return budget
        try:
            for case in cases:
                if remaining() <= 0:
                    termination = 'deadline'
                    break
                history = histories.setdefault(case.conversationId, []) if case.caseType == 'context' else []
                try:
                    with runtime_context(owned), attempt_context(None):
                        result = handle_host_response(soup, history, case.question, versions=versions, rule_snapshot=snapshot)
                    if result.kind == 'system_error':
                        status = 'error'
                    else:
                        expected = case.review.expectedLabel
                        status = 'passed' if result.kind == expected.kind and (
                            result.kind != 'answer' or result.answer == expected.answer) else 'counterexample'
                        if case.caseType == 'context':
                            history.extend([dict(role='user', content=case.question), dict(role='host', content=result.reply,
                                answer=result.answer, kind=result.kind, is_free_reminder=not result.chargeable)])
                except _ProviderDisabled:
                    status = 'unsupported'
                except Exception:
                    status = 'error'
                results.append(ObservedCase(caseId=case.caseId, status=status))
                if remaining() <= 0:
                    termination = 'deadline'
                    break
        finally:
            try:
                asyncio.run(owned.aclose())
            except Exception:
                cleanup = False
            else:
                cleanup = (owned.closed and owned.model_gateway is None and owned.agent_worker is None
                    and owned.audit_store is None and owned.http_client is None and owned.http_async_client is None)
        results.extend(ObservedCase(caseId=case.caseId, status='not_attempted') for case in cases[len(results):])
        if not cleanup:
            termination = 'cleanup_failed'
        self._live_inputs(plan, request)
        if remaining() <= 0:
            termination = 'deadline'
        result = PostPublicationResult(runId=plan.runId, planDigest=plan.planDigest,
            finishedAt=self._time(self.utc_clock), cleanupConfirmed=cleanup,
            terminationCode=termination, caseResults=tuple(results))
        try:
            # Fence the original monotonic AND UTC budget after the final
            # source checks, immediately before a newly passed commit.
            return self.store.finish(plan.operationKey, result, verify_passed_budget=lambda: remaining() > 0)
        except PostPublicationError as error:
            if error.code != 'post_publication_deadline':
                raise
            # Fresh all-pass finalization raced a late source check. The first
            # transaction rolled back; preserve the same plan as incomplete.
            result = result.model_copy(update={'finishedAt': self._time(self.utc_clock), 'terminationCode': 'deadline'})
            return self.store.finish(plan.operationKey, result)
