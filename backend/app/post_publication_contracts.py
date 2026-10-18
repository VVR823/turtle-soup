"""Closed post-publication observation contracts, not publication authority."""
from typing import Annotated, Literal

from pydantic import Field, StrictBool, field_validator, model_validator

from . import baselines
from .agents.contracts import StrictAgentModel, checked_model
from .audit_events import CanonicalId, Identity
from .rule_contract import Digest, PuzzleVersion, RuleVersion


class PostPublicationError(RuntimeError):
    def __init__(self, code='post_publication_invalid', status=422):
        self.code, self.status = code, status
        super().__init__(code)


class _ObservationModel(StrictAgentModel):
    schemaVersion: Literal[1] = 1

    @field_validator('schemaVersion', mode='before')
    @classmethod
    def real_schema(cls, value):
        if type(value) is not int:
            raise ValueError('Integer schema required')
        return value


class PlannedCase(StrictAgentModel):
    caseId: CanonicalId
    caseDigest: Digest


class PostPublicationPlan(_ObservationModel):
    runId: CanonicalId
    operationKey: CanonicalId
    candidateId: CanonicalId
    publicationOperationKey: CanonicalId
    publicationProofDigest: Digest
    soupId: Identity
    puzzleVersion: PuzzleVersion
    publishedRuleVersion: RuleVersion
    publishedAt: Annotated[float, Field(ge=0, lt=1e15)]
    startedAt: Annotated[float, Field(ge=0, lt=1e15)]
    deadlineAt: Annotated[float, Field(ge=0, lt=1e15)]
    trafficClass: Literal['real', 'test', 'synthetic', 'unknown']
    evidenceKind: Literal['synthetic_fixture', 'deterministic_regression']
    datasetDigest: Digest
    suiteManifestDigest: Digest
    cases: Annotated[tuple[PlannedCase, ...], Field(min_length=1, max_length=100)]

    @model_validator(mode='after')
    def bounded_scope(self):
        if (not self.publishedAt <= self.startedAt < self.deadlineAt <= self.startedAt + 5
            or len({case.caseId for case in self.cases}) != len(self.cases)
            or self.trafficClass == 'real' and self.evidenceKind == 'synthetic_fixture'):
            raise ValueError('Invalid observation scope')
        return self

    @property
    def plannedCaseCount(self):
        return len(self.cases)

    @property
    def planDigest(self):
        return baselines.digest(self.model_dump(mode='json'))

    @property
    def payloadDigest(self):
        # A retry's newly generated run/clock cannot alter the original receipt;
        # code, corpus, source proof, order and request scope remain bound.
        return baselines.digest(self.model_dump(mode='json', exclude={'runId', 'startedAt', 'deadlineAt'}))


class ObservedCase(StrictAgentModel):
    caseId: CanonicalId
    status: Literal['passed', 'counterexample', 'error', 'unsupported', 'not_attempted']


class PostPublicationResult(_ObservationModel):
    runId: CanonicalId
    planDigest: Digest
    finishedAt: Annotated[float, Field(ge=0, lt=1e15)]
    cleanupConfirmed: StrictBool
    terminationCode: Literal['finished', 'deadline', 'source_changed', 'error', 'cleanup_failed']
    caseResults: Annotated[tuple[ObservedCase, ...], Field(min_length=1, max_length=100)]

    @property
    def state(self):
        if self.counterexampleCaseCount:
            return 'failed'
        if (self.terminationCode == 'finished' and self.cleanupConfirmed
            and self.passedCaseCount == len(self.caseResults)):
            return 'passed'
        return 'incomplete'

    def _count(self, status):
        return sum(case.status == status for case in self.caseResults)

    @property
    def attemptedCaseCount(self):
        return len(self.caseResults) - self.notAttemptedCaseCount

    @property
    def passedCaseCount(self):
        return self._count('passed')

    @property
    def counterexampleCaseCount(self):
        return self._count('counterexample')

    @property
    def errorCaseCount(self):
        return self._count('error')

    @property
    def unsupportedCaseCount(self):
        return self._count('unsupported')

    @property
    def notAttemptedCaseCount(self):
        return self._count('not_attempted')


def checked_observation(model, value):
    try:
        return checked_model(model, value, max_bytes=65536)
    except Exception:
        raise PostPublicationError() from None


def validate_result(plan, result):
    """Typed consistency only; the store/runner must recheck publication authority."""
    try:
        plan = checked_observation(PostPublicationPlan, plan)
        result = checked_observation(PostPublicationResult, result)
        if (result.runId != plan.runId or result.planDigest != plan.planDigest
            or result.finishedAt < plan.startedAt
            or tuple(case.caseId for case in result.caseResults) != tuple(case.caseId for case in plan.cases)
            or result.state == 'passed' and result.finishedAt > plan.deadlineAt):
            raise ValueError('Result scope mismatch')
        stopped = False
        for case in result.caseResults:
            if case.status == 'not_attempted':
                stopped = True
            elif stopped:
                raise ValueError('Execution resumed after an unattempted case')
        return result
    except Exception:
        raise PostPublicationError() from None


class ObservationReceipt(_ObservationModel):
    plan: PostPublicationPlan
    result: PostPublicationResult | None
    state: Literal['running', 'passed', 'failed', 'incomplete']

    @model_validator(mode='after')
    def saved_outcome(self):
        expected = 'running' if self.result is None else validate_result(self.plan, self.result).state
        if self.state != expected:
            raise ValueError('Receipt state differs from saved observation')
        return self
