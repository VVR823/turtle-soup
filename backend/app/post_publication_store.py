"""Durable observation plans, not a model/caller-reported success endpoint."""
from contextlib import contextmanager
from dataclasses import dataclass
import time

from pydantic import TypeAdapter

from . import baselines, migrations
from .agents.contracts import AgentError
from .agents.store import AgentStore
from .audit_events import CanonicalId
from .post_publication_contracts import (PostPublicationError, PostPublicationPlan,
    PostPublicationResult, checked_observation, validate_result)

_PLAN_COLUMNS = dict(runId='id', operationKey='operation_key', candidateId='candidate_id',
    publicationOperationKey='publication_operation_key', soupId='soup_id', puzzleVersion='puzzle_version',
    publishedRuleVersion='published_rule_version', publishedAt='published_at', startedAt='started_at',
    deadlineAt='deadline_at', trafficClass='traffic_class', evidenceKind='evidence_kind')
_COUNT_COLUMNS = dict(attemptedCaseCount='attempted_case_count', passedCaseCount='passed_case_count',
    counterexampleCaseCount='counterexample_case_count', errorCaseCount='error_case_count',
    unsupportedCaseCount='unsupported_case_count')


@dataclass(frozen=True)
class PostPublicationRecord:
    plan: PostPublicationPlan
    result: PostPublicationResult | None

    @property
    def state(self):
        return 'running' if self.result is None else self.result.state


class PostPublicationStore:
    """Short owned transactions; the server supplies a fresh publication verifier.

    This store does not execute probes or decide which source is approved. A
    schema-valid plan is never sufficient authorization. No auto migration,
    database initialization, journal-mode change or provider construction.
    """
    def __init__(self, runtime, *, verify_source, verify_fresh=None, clock=time.time):
        if not callable(verify_source):
            raise TypeError('Explicit server publication verifier required')
        self.verify_source = verify_source
        if verify_fresh is not None and not callable(verify_fresh):
            raise TypeError('Server fresh-input verifier must be callable')
        self.verify_fresh = verify_fresh
        self.agent_store = AgentStore(runtime, authorize_create=lambda context: False, clock=clock)

    def _source(self, conn, plan):
        try:
            if self.verify_source(conn, plan) is not True:
                raise ValueError('Missing source authority')
        except Exception:
            raise PostPublicationError('post_publication_source_invalid', 409) from None

    @contextmanager
    def _transaction(self, *, write, authority, passed_deadline=None, fresh=None, verify_passed_budget=None):
        def final_source():
            if authority:
                try:
                    self._source(conn, authority[0])
                    if fresh and self.verify_fresh is not None:
                        try:
                            if self.verify_fresh(conn, authority[0]) is not True:
                                raise ValueError('Fresh inputs changed')
                        except Exception:
                            raise PostPublicationError('post_publication_source_changed', 409) from None
                    if self.agent_store.runtime.closed:
                        raise PostPublicationError('post_publication_unavailable', 503)
                    if passed_deadline and self.agent_store._now() > passed_deadline[0]:
                        raise PostPublicationError('post_publication_deadline', 409)
                    if passed_deadline and verify_passed_budget is not None and verify_passed_budget() is not True:
                        raise PostPublicationError('post_publication_deadline', 409)
                except PostPublicationError as error:
                    raise AgentError(error.code, error.status) from None
        try:
            with self.agent_store._transaction(write=write, before_commit=final_source) as conn:
                try:
                    migrations.verify_schema(conn, required_version=5)
                    yield conn
                except PostPublicationError as error:
                    raise AgentError(error.code, error.status) from None
        except AgentError as error:
            code = error.code if error.code.startswith('post_publication_') else 'post_publication_unavailable'
            raise PostPublicationError(code, error.status) from None

    @staticmethod
    def _key(value):
        try:
            return TypeAdapter(CanonicalId).validate_python(value, strict=True)
        except Exception:
            raise PostPublicationError() from None

    @staticmethod
    def _record(conn, row):
        phase = conn.execute("SELECT value_json FROM runtime_meta WHERE key='migration_005_report'").fetchone()
        coverage = baselines.strict_json(phase[0])['phase005']['coverageStart']
        return PostPublicationStore.checked_record(row, coverage)

    @staticmethod
    def checked_record(row, coverage):
        """Pure immutable ledger validation, shared by the same-snapshot reader."""
        if row is None:
            raise PostPublicationError('post_publication_not_found', 404)
        try:
            plan = checked_observation(PostPublicationPlan, row['plan_json'])
            if (row['plan_json'] != baselines.canonical_json(plan.model_dump(mode='json'))
                or row['plan_digest'] != plan.planDigest or row['payload_digest'] != plan.payloadDigest
                or row['planned_case_count'] != plan.plannedCaseCount or plan.startedAt < coverage
                or any(row[column] != getattr(plan, field) for field, column in _PLAN_COLUMNS.items())):
                raise ValueError('Stored plan projection mismatch')
            result = None
            if row['result_json'] is None:
                if (row['state'] != 'running' or row['result_digest'] is not None or row['finished_at'] is not None
                    or any(row[column] != 0 for column in _COUNT_COLUMNS.values())):
                    raise ValueError('Pending record has invented outcomes')
            else:
                result = validate_result(plan, row['result_json'])
                body = result.model_dump(mode='json')
                if (row['result_json'] != baselines.canonical_json(body)
                    or row['result_digest'] != baselines.digest(body) or row['state'] != result.state
                    or row['finished_at'] != result.finishedAt
                    or any(row[column] != getattr(result, field) for field, column in _COUNT_COLUMNS.items())):
                    raise ValueError('Stored result projection mismatch')
            return PostPublicationRecord(plan, result)
        except Exception:
            raise PostPublicationError('post_publication_record_invalid', 503) from None

    def get(self, operation_key):
        key, authority = self._key(operation_key), []
        with self._transaction(write=False, authority=authority) as conn:
            record = self._record(conn, conn.execute(
                'SELECT * FROM post_publication_runs WHERE operation_key=?', (key,)).fetchone())
            self._source(conn, record.plan)
            authority.append(record.plan)
            return record

    def reserve(self, plan):
        plan = checked_observation(PostPublicationPlan, plan)
        authority, fresh = [], []
        with self._transaction(write=True, authority=authority, fresh=fresh) as conn:
            self._source(conn, plan)
            old = conn.execute('SELECT * FROM post_publication_runs WHERE operation_key=?', (plan.operationKey,)).fetchone()
            if old is not None:
                record = self._record(conn, old)
                if record.plan.payloadDigest != plan.payloadDigest:
                    raise PostPublicationError('post_publication_conflict', 409)
                authority.append(record.plan)
                return record, False
            now = self.agent_store._now()
            phase = conn.execute("SELECT value_json FROM runtime_meta WHERE key='migration_005_report'").fetchone()
            coverage = baselines.strict_json(phase[0])['phase005']['coverageStart']
            if not coverage <= plan.startedAt <= now < plan.deadlineAt:
                raise PostPublicationError('post_publication_deadline', 409)
            values = {column: getattr(plan, field) for field, column in _PLAN_COLUMNS.items()}
            values.update(payload_digest=plan.payloadDigest, plan_digest=plan.planDigest,
                plan_json=baselines.canonical_json(plan.model_dump(mode='json')),
                planned_case_count=plan.plannedCaseCount, state='running')
            # All names are fixed server mappings; only values enter parameters.
            conn.execute('INSERT INTO post_publication_runs (' + ','.join(values) + ') VALUES ('
                + ','.join(':' + key for key in values) + ')', values)
            record = self._record(conn, conn.execute(
                'SELECT * FROM post_publication_runs WHERE id=?', (plan.runId,)).fetchone())
            authority.append(plan)
            fresh.append(True)
            return record, True

    def finish(self, operation_key, result, *, verify_passed_budget=None):
        if verify_passed_budget is not None and not callable(verify_passed_budget):
            raise TypeError('Server execution-budget verifier must be callable')
        key, authority = self._key(operation_key), []
        result = checked_observation(PostPublicationResult, result)
        passed_deadline, fresh = [], []
        with self._transaction(write=True, authority=authority, passed_deadline=passed_deadline, fresh=fresh,
            verify_passed_budget=verify_passed_budget) as conn:
            record = self._record(conn, conn.execute(
                'SELECT * FROM post_publication_runs WHERE operation_key=?', (key,)).fetchone())
            self._source(conn, record.plan)
            result = validate_result(record.plan, result)
            if result.finishedAt > self.agent_store._now():
                raise PostPublicationError('post_publication_invalid', 422)
            if record.result is not None:
                if record.result != result:
                    raise PostPublicationError('post_publication_conflict', 409)
                authority.append(record.plan)
                return record
            body = result.model_dump(mode='json')
            values = {column: getattr(result, field) for field, column in _COUNT_COLUMNS.items()}
            values.update(state=result.state, result_json=baselines.canonical_json(body),
                result_digest=baselines.digest(body), finished_at=result.finishedAt)
            changed = conn.execute('UPDATE post_publication_runs SET ' + ','.join(name + '=:' + name for name in values)
                + " WHERE id=:identity AND state='running'", dict(values, identity=record.plan.runId))
            if changed.rowcount != 1:
                raise PostPublicationError('post_publication_conflict', 409)
            if result.state == 'passed':
                passed_deadline.append(record.plan.deadlineAt)
            finished = self._record(conn, conn.execute(
                'SELECT * FROM post_publication_runs WHERE id=?', (record.plan.runId,)).fetchone())
            authority.append(record.plan)
            fresh.append(True)
            return finished
