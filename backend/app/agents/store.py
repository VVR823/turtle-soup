"""Explicit-runtime short run transactions; no worker, model or publication."""
import math
import sqlite3
import time
from dataclasses import dataclass
from contextlib import contextmanager
from contextvars import ContextVar
from threading import Event
from typing import Annotated, Literal
from uuid import uuid4

from pydantic import Field, StrictInt, TypeAdapter, field_validator, model_validator

from .. import audit_store, baselines, db
from ..audit_events import AgentBusinessDetails, AuditEvent, CanonicalId
from ..feedback_contract import FeedbackError, RowVersion
from ..migrations import verify_schema
from ..runtime import Runtime, runtime_context
from ..task_context import TOOLS, _freeze
from .contracts import (AgentCheckpoint, AgentError, AgentManifest, ExecutionIdentity, StrictAgentModel,
    CandidateRecord, FinishAction, RegressionReport, ToolAction, candidate_digest, checked_draft, checked_model,
    draft_digest, parse_agent_action, parse_tool_action)
from .decision_contracts import DecisionIntent, DecisionResult, StopIntent, StopResult, AgentStatus, StepSummary

RunState = Literal["queued", "running", "awaiting_review", "needs_human", "failed", "cancelled"]
_execution_scope = ContextVar("repair_execution_scope", default=None)


class RunRecord(StrictAgentModel):
    id: CanonicalId
    requestId: CanonicalId
    feedbackId: CanonicalId
    state: RunState
    checkpoint: AgentCheckpoint
    manifest: AgentManifest
    leaseToken: CanonicalId | None
    leaseExpiresAt: Annotated[float, Field(ge=0)] | None
    rowVersion: RowVersion
    createdAt: Annotated[float, Field(ge=0)]
    updatedAt: Annotated[float, Field(ge=0)]

    @model_validator(mode="after")
    def coherent(self):
        if ((self.leaseToken is None) != (self.leaseExpiresAt is None)
            or self.feedbackId != self.manifest.context.feedbackId
            or self.updatedAt < self.createdAt):
            raise ValueError("Run identity mismatch")
        if self.state == "queued" and (self.leaseToken is not None or self.checkpoint.firstStartedAt is not None):
            raise ValueError("Queued run cannot have started")
        if self.state == "running" and (self.leaseToken is None or self.checkpoint.firstStartedAt is None
            or self.leaseExpiresAt > self.checkpoint.deadlineAt):
            raise ValueError("Running lease required")
        if self.state not in {"queued", "running"} and self.leaseToken is not None:
            raise ValueError("Terminal run cannot retain a lease")
        return self


class StepRecord(StrictAgentModel):
    runId: CanonicalId
    seq: Annotated[StrictInt, Field(ge=0, le=9223372036854775807)]
    operationKey: CanonicalId
    action: ToolAction | FinishAction | DecisionIntent | StopIntent
    state: Literal["planned", "completed", "failed"]
    resultJson: Annotated[str, Field(min_length=1, max_length=32768)] | None
    createdAt: Annotated[float, Field(ge=0)]

    @model_validator(mode="after")
    def coherent(self):
        if (self.state == "planned") != (self.resultJson is None):
            raise ValueError("A planned intent is not a completed result")
        if self.resultJson is not None and (len(self.resultJson.encode("utf-8")) > 32768
            or type(baselines.strict_json(self.resultJson)) is not dict):
            raise ValueError("Bounded structured result required")
        if isinstance(self.action, DecisionIntent) and self.resultJson is not None:
            result = checked_model(DecisionResult, self.resultJson)
            if (self.state != "completed" or result.inputDigest != self.action.inputDigest
                or result.promptDigest != self.action.promptDigest):
                raise ValueError("Stored decision binding mismatch")
        if isinstance(self.action, StopIntent):
            if self.state != "completed" or self.resultJson is None:
                raise ValueError("Stop must be atomic with terminal result")
            result = checked_model(StopResult, self.resultJson)
            if result.runId != self.runId or result.state != self.action.state or result.reason != self.action.reason:
                raise ValueError("Stored stop binding mismatch")
        return self


@dataclass(frozen=True)
class StepReservation:
    step: StepRecord
    newly_created: bool


class FinishRecord(StrictAgentModel):
    runId: CanonicalId
    state: Literal["awaiting_review", "needs_human"]
    candidateId: CanonicalId | None
    executionDigest: Annotated[str, Field(pattern=r"^[0-9a-f]{64}$", min_length=64, max_length=64)]

    @model_validator(mode="after")
    def candidate_state(self):
        if (self.state == "awaiting_review") != (self.candidateId is not None):
            raise ValueError("Finish outcome mismatch")
        return self


class ToolFailure(StrictAgentModel):
    schemaVersion: Literal[1] = 1
    code: Literal["agent_tool_failed", "agent_deadline_exhausted", "agent_input_invalid", "agent_scope_invalid",
        "agent_tool_forbidden", "agent_report_incomplete", "agent_candidate_conflict", "agent_unavailable"]

    @field_validator("schemaVersion", mode="before")
    @classmethod
    def real_schema(cls, value):
        if type(value) is not int:
            raise ValueError("Real schema required")
        return value


class AgentStore:
    def __init__(self, runtime: Runtime, *, authorize_create, clock=time.time, lease_seconds=30):
        if not isinstance(runtime, Runtime) or not callable(authorize_create) or not callable(clock):
            raise TypeError("Explicit runtime, authorization and clock required")
        if type(lease_seconds) is not int or lease_seconds not in (30, 60):
            raise ValueError("Closed server lease must be 30 or 60 seconds")
        self.runtime, self.authorize_create, self.clock = runtime, authorize_create, clock
        self.lease_seconds = lease_seconds

    def _now(self):
        value = self.clock()
        if type(value) not in (float, int) or not math.isfinite(value) or value < 0:
            raise AgentError("agent_clock_invalid", 503)
        return float(value)

    @contextmanager
    def execution_scope(self, run_id, lease_token, cancelled):
        """Trusted loop authority, propagated to its owned gateway thread only.

        Not a model parameter, serialized record or second resource owner.
        A new lease gets a new scope; terminal stopping never uses this fence.
        """
        run_id = TypeAdapter(CanonicalId).validate_python(run_id, strict=True)
        lease_token = TypeAdapter(CanonicalId).validate_python(lease_token, strict=True)
        if not isinstance(cancelled, Event):
            raise TypeError("Owned cancellation event required")
        token = _execution_scope.set((self, run_id, lease_token, cancelled))
        try:
            yield
        finally:
            _execution_scope.reset(token)

    def _check_execution(self, identity=None):
        scope = _execution_scope.get()
        if scope is not None and scope[0] is self:
            if identity is not None and (identity.runId, identity.leaseToken) != scope[1:3]:
                raise AgentError("agent_lease_expired", 409)
            if scope[3].is_set():
                raise AgentError("agent_execution_cancelled", 409)

    @contextmanager
    def _transaction(self, *, write=True, before_commit=None):
        # No db.initialize: feature activation/migration is an explicit operator
        # decision. Runtime context is restored even from a foreign worker.
        if self.runtime.closed:
            raise AgentError("agent_unavailable", 503)
        with runtime_context(self.runtime):
            conn = None
            try:
                # Feature gating must not create a missing database or switch
                # journal mode before required003 has actually been verified.
                path = self.runtime.settings.DATA_DIR / "sessions.db"
                conn = sqlite3.connect(path.resolve().as_uri() + "?mode=rw", uri=True, timeout=10)
                conn.row_factory = sqlite3.Row
                conn.execute("PRAGMA foreign_keys=ON")
                conn.execute("BEGIN IMMEDIATE" if write else "BEGIN")
                # BEGIN may wait for an owned SQLite writer. Admission before
                # that wait is not authority to resume work after shutdown.
                with self.runtime.lock:
                    if self.runtime.closed:
                        raise AgentError("agent_unavailable", 503)
                    if write:
                        self._check_execution()
                verify_schema(conn, required_version=3)
                yield conn
                # Closing and ordinary commit have one linearization lock.
                # Never hold it across SQLite lock acquisition or Agent work.
                # A trusted caller may supply a bounded final identity fence;
                # it and commit share this lock, never a second transaction.
                with self.runtime.lock:
                    if self.runtime.closed:
                        raise AgentError("agent_unavailable", 503)
                    if write:
                        self._check_execution()
                    if before_commit is not None:
                        before_commit()
                    conn.commit()
            except BaseException as error:
                if conn is not None:
                    conn.rollback()
                if isinstance(error, (AgentError, KeyboardInterrupt, SystemExit)):
                    raise
                if isinstance(error, FeedbackError) and error.status in (400, 401, 403, 404, 409, 422):
                    # Revocation/stale source is a controlled refusal requiring
                    # new human input, not a retryable transient storage outage.
                    raise AgentError("agent_context_stale", 409) from None
                raise AgentError("agent_unavailable", 503) from None
            finally:
                if conn is not None:
                    conn.close()

    def _record(self, row):
        if row is None:
            raise AgentError("agent_run_not_found", 404)
        body = dict(id=row["id"], requestId=row["request_id"], feedbackId=row["feedback_id"], state=row["state"],
            checkpoint=baselines.strict_json(row["checkpoint_json"]), manifest=baselines.strict_json(row["manifest_json"]),
            leaseToken=row["lease_token"], leaseExpiresAt=row["lease_expires_at"], rowVersion=row["row_version"],
            createdAt=row["created_at"], updatedAt=row["updated_at"])
        return checked_model(RunRecord, body, max_bytes=1048576)

    def _load(self, conn, run_id):
        identity = TypeAdapter(CanonicalId).validate_python(run_id, strict=True)
        run = self._record(conn.execute("SELECT * FROM agent_runs WHERE id=?", (identity,)).fetchone())
        frozen = run.manifest.context
        current = _freeze(conn, frozen.feedbackId, frozen.sourceFeedbackVersion, frozen.allowedTools)
        if current != frozen:
            raise AgentError("agent_context_stale", 409)
        if run.manifest.trafficClass != ("test" if self.runtime.settings.TESTING else "real"):
            raise AgentError("agent_traffic_mismatch", 409)
        return run

    def _audit(self, conn, run, action, now, *, identity=None, candidate=None, payload=None):
        audit_store.insert_business_event(conn, AuditEvent(eventId=str(uuid4()),
            eventType="rule_candidate" if action == "candidate_saved" else "agent_step"
                if action in {"step_planned", "step_completed", "step_failed"} else "agent_run",
            requestId=run.requestId, runId=run.id, turnId=run.manifest.context.turnId, createdAt=now,
            details=AgentBusinessDetails(runId=run.id, action=action, state=run.state, rowVersion=run.rowVersion,
                payloadDigest=baselines.digest(dict(run=run.model_dump(mode="json"), mutation=payload)),
                modelAttemptsUsed=run.checkpoint.modelAttemptsUsed, toolAttemptsUsed=run.checkpoint.toolAttemptsUsed,
                trafficClass=run.manifest.trafficClass, operationKey=None if identity is None else identity.operationKey,
                seq=None if identity is None else identity.seq, candidateId=None if candidate is None else candidate.id)))

    def create(self, *, request_id, feedback_id, expected_feedback_version, allowed_tools, suite_manifest_digest):
        with self._transaction() as conn:
            request_id = TypeAdapter(CanonicalId).validate_python(request_id, strict=True)
            feedback_id = TypeAdapter(CanonicalId).validate_python(feedback_id, strict=True)
            version = TypeAdapter(RowVersion).validate_python(expected_feedback_version, strict=True)
            if (type(allowed_tools) is not tuple or not allowed_tools or len(allowed_tools) > 5
                or len(set(allowed_tools)) != len(allowed_tools) or not set(allowed_tools) <= TOOLS):
                raise AgentError("agent_tool_forbidden", 409)
            context = _freeze(conn, feedback_id, version, allowed_tools)
            if self.authorize_create(context) is not True:
                raise AgentError("agent_authorization_required", 403)
            manifest = checked_model(AgentManifest, dict(context=context.model_dump(mode="json"),
                contextDigest=baselines.digest(context.model_dump(mode="json")), suiteManifestDigest=suite_manifest_digest,
                trafficClass="test" if self.runtime.settings.TESTING else "real"), max_bytes=524288)
            existing = conn.execute("SELECT * FROM agent_runs WHERE request_id=?", (request_id,)).fetchone()
            if existing is not None:
                prior = self._load(conn, existing["id"])
                if prior.manifest != manifest or prior.feedbackId != feedback_id:
                    raise AgentError("agent_request_conflict", 409)
                return prior
            if conn.execute("SELECT count(*) FROM agent_runs WHERE state='queued'").fetchone()[0] >= 10:
                raise AgentError("agent_queue_full", 429)
            now, identity = self._now(), str(uuid4())
            checkpoint = AgentCheckpoint()
            conn.execute("INSERT INTO agent_runs(id,request_id,feedback_id,state,checkpoint_json,manifest_json,created_at,updated_at) "
                "VALUES(?,?,?,'queued',?,?,?,?)", (identity, request_id, feedback_id,
                    checkpoint.model_dump_json(), manifest.model_dump_json(warnings="error"), now, now))
            run = self._load(conn, identity)
            self._audit(conn, run, "queued", now)
            return run

    def read(self, run_id):
        with self._transaction(write=False) as conn:
            return self._load(conn, run_id)

    def steps(self, run_id):
        with self._transaction(write=False) as conn:
            run = self._load(conn, run_id)
            return tuple(self._step(row) for row in conn.execute(
                "SELECT * FROM agent_steps WHERE run_id=? ORDER BY seq", (run.id,)))

    def pending_runs(self):
        """Bounded server-only scheduling hints; claim rechecks live scope.

        Never an admin/model response or a second RAM queue. Include expired
        running tasks for conservative recovery, without changing deadlines.
        """
        with self._transaction(write=False) as conn:
            return tuple(self._record(row) for row in conn.execute(
                "SELECT * FROM agent_runs WHERE state='queued' OR (state='running' AND lease_expires_at<=?) "
                "ORDER BY created_at,id LIMIT 10", (self._now(),)))

    @contextmanager
    def _terminal_stop_transaction(self):
        """Dedicated authority-removal path, never used by normal operations.

        Runtime may be closing and the source may be revoked. No caller flag
        can make tool/decision/candidate writes use this exception.
        """
        with runtime_context(self.runtime):
            conn = None
            try:
                path = self.runtime.settings.DATA_DIR / "sessions.db"
                conn = sqlite3.connect(path.resolve().as_uri() + "?mode=rw", uri=True, timeout=10)
                conn.row_factory = sqlite3.Row
                conn.execute("PRAGMA foreign_keys=ON")
                conn.execute("BEGIN IMMEDIATE")
                verify_schema(conn, required_version=3)
                yield conn
                conn.commit()
            except BaseException as error:
                if conn is not None:
                    conn.rollback()
                if isinstance(error, (AgentError, KeyboardInterrupt, SystemExit)):
                    raise
                raise AgentError("agent_unavailable", 503) from None
            finally:
                if conn is not None:
                    conn.close()

    def _raw_run(self, conn, run_id):
        try:
            run_id = TypeAdapter(CanonicalId).validate_python(run_id, strict=True)
        except Exception:
            raise AgentError() from None
        return self._record(conn.execute("SELECT * FROM agent_runs WHERE id=?", (run_id,)).fetchone())

    def _status(self, conn, run):
        rows = conn.execute("SELECT * FROM agent_steps WHERE run_id=? ORDER BY seq", (run.id,)).fetchmany(33)
        if len(rows) > 32:
            raise AgentError("agent_status_unavailable", 503)
        steps = tuple(self._step(row) for row in rows)
        reason, candidate = None, None
        if steps and isinstance(steps[-1].action, StopIntent):
            result = checked_model(StopResult, steps[-1].resultJson)
            if run.state != result.state:
                raise AgentError("agent_status_unavailable", 503)
            reason = result.reason
        elif run.state in {"failed", "cancelled"}:
            raise AgentError("agent_status_unavailable", 503)
        elif run.state in {"awaiting_review", "needs_human"}:
            if not steps or not isinstance(steps[-1].action, FinishAction) or steps[-1].state != "completed":
                raise AgentError("agent_status_unavailable", 503)
            result = checked_model(FinishRecord, steps[-1].resultJson)
            if result.runId != run.id or result.state != run.state:
                raise AgentError("agent_status_unavailable", 503)
            candidate = result.candidateId
        return checked_model(AgentStatus, AgentStatus(id=run.id, state=run.state, rowVersion=run.rowVersion,
            modelAttemptsUsed=run.checkpoint.modelAttemptsUsed, toolAttemptsUsed=run.checkpoint.toolAttemptsUsed,
            deadlineAt=run.checkpoint.deadlineAt, reason=reason, candidateId=candidate,
            steps=tuple(StepSummary(seq=s.seq, action=s.action.action, state=s.state,
                tool=s.action.tool if s.action.action == "tool" else None) for s in steps)))

    def read_status(self, run_id):
        with self._transaction(write=False) as conn:
            return self._status(conn, self._raw_run(conn, run_id))

    def _write_stop(self, conn, run, intent):
        now = self._now()
        if now < run.updatedAt or run.rowVersion == 9223372036854775807:
            raise AgentError("agent_run_conflict", 409)
        seq = conn.execute("SELECT coalesce(max(seq),-1)+1 FROM agent_steps WHERE run_id=?", (run.id,)).fetchone()[0]
        identity = ExecutionIdentity(runId=run.id, seq=seq, operationKey=str(uuid4()),
            leaseToken=run.leaseToken or str(uuid4()))
        result = StopResult(runId=run.id, state=intent.state, reason=intent.reason)
        conn.execute("INSERT INTO agent_steps(run_id,seq,operation_key,action_json,result_json,state,created_at) "
            "VALUES(?,?,?,?,?,'completed',?)", (run.id, seq, identity.operationKey,
                baselines.canonical_json(intent.model_dump(mode="json")),
                baselines.canonical_json(result.model_dump(mode="json")), now))
        changed = conn.execute("UPDATE agent_runs SET state=?,lease_token=NULL,lease_expires_at=NULL,updated_at=?,"
            "row_version=row_version+1 WHERE id=? AND row_version=?", (intent.state, now, run.id, run.rowVersion))
        if changed.rowcount != 1:
            raise AgentError("agent_run_conflict", 409)
        stopped = self._raw_run(conn, run.id)
        self._audit(conn, stopped, intent.state, now, identity=identity, payload=result.model_dump(mode="json"))
        return self._status(conn, stopped)

    def stop(self, run_id, *, lease_token, state, reason):
        if type(state) is not str or state not in {"failed", "needs_human"}:
            raise AgentError()
        try:
            token = TypeAdapter(CanonicalId).validate_python(lease_token, strict=True)
        except Exception:
            raise AgentError() from None
        intent = checked_model(StopIntent, dict(state=state, reason=reason,
            ownerDigest=baselines.digest(dict(lease=token))))
        with self._terminal_stop_transaction() as conn:
            run = self._raw_run(conn, run_id)
            if run.state != "running":
                row = conn.execute("SELECT * FROM agent_steps WHERE run_id=? ORDER BY seq DESC LIMIT 1", (run.id,)).fetchone()
                if row is None or self._step(row).action != intent or run.state != state:
                    raise AgentError("agent_run_conflict", 409)
                return self._status(conn, run)
            # An expired owner may only remove its still-current authority;
            # takeover changes the token and denies even this terminal write.
            if run.leaseToken != token:
                raise AgentError("agent_lease_expired", 409)
            return self._write_stop(conn, run, intent)

    def cancel(self, run_id, *, expected_row_version):
        with self._terminal_stop_transaction() as conn:
            run = self._raw_run(conn, run_id)
            version = TypeAdapter(RowVersion).validate_python(expected_row_version, strict=True)
            if run.rowVersion != version or run.state not in {"queued", "running", "cancelled"}:
                raise AgentError("agent_run_conflict", 409)
            if run.state == "cancelled":
                return self._status(conn, run)
            return self._write_stop(conn, run, StopIntent(state="cancelled", reason="cancellation", ownerDigest=None))

    def handoff_stale_queued(self, run_id, *, expected_row_version):
        """Server-only removal of permanently stale, never-started queue work.

        CAS protects concurrent cancel/claim. No lease, deadline, attempt or
        restored model permission is created; transient storage failures retry.
        """
        with self._terminal_stop_transaction() as conn:
            run = self._raw_run(conn, run_id)
            version = TypeAdapter(RowVersion).validate_python(expected_row_version, strict=True)
            if run.rowVersion != version or run.state != "queued":
                raise AgentError("agent_run_conflict", 409)
            try:
                self._load(conn, run.id)
            except FeedbackError as error:
                if error.status not in (400, 401, 403, 404, 409, 422):
                    raise
            except AgentError as error:
                if error.code not in {"agent_context_stale", "agent_source_reload_required",
                    "agent_suite_changed", "agent_traffic_mismatch"}:
                    raise
            else:
                # The earlier refusal is not authority to stop fresh work.
                raise AgentError("agent_run_conflict", 409)
            return self._write_stop(conn, run, StopIntent(state="needs_human",
                reason="source_changed", ownerDigest=None))

    def _cas_lease(self, conn, run, *, now, token, expires, checkpoint):
        if run.rowVersion == 9223372036854775807 or now < run.updatedAt:
            raise AgentError("agent_run_conflict", 409)
        changed = conn.execute("UPDATE agent_runs SET state='running',checkpoint_json=?,lease_token=?,lease_expires_at=?,"
            "updated_at=?,row_version=row_version+1 WHERE id=? AND row_version=?", (
                checkpoint.model_dump_json(warnings="error"), token, expires, now, run.id, run.rowVersion))
        if changed.rowcount != 1:
            raise AgentError("agent_run_conflict", 409)
        return self._load(conn, run.id)

    def claim(self, run_id, *, expected_row_version):
        # Claim/take over by row-version CAS. Recovery keeps the checkpoint's
        # spent budgets and original 180-second deadline; it grants no fresh run.
        with self._transaction() as conn:
            run, now = self._load(conn, run_id), self._now()
            expected = TypeAdapter(RowVersion).validate_python(expected_row_version, strict=True)
            if (expected != run.rowVersion or run.state not in {"queued", "running"}
                or (run.state == "running" and run.leaseExpiresAt > now)):
                raise AgentError("agent_run_conflict", 409)
            checkpoint = run.checkpoint
            if checkpoint.firstStartedAt is None:
                checkpoint = AgentCheckpoint(firstStartedAt=now, deadlineAt=now + 180.0)
            if now >= checkpoint.deadlineAt:
                raise AgentError("agent_deadline_exhausted", 409)
            run = self._cas_lease(conn, run, now=now, token=str(uuid4()),
                expires=min(now + self.lease_seconds, checkpoint.deadlineAt), checkpoint=checkpoint)
            self._audit(conn, run, "claimed", now)
            return run

    def heartbeat(self, run_id, lease_token):
        # Only the current live owner may extend its lease, capped at the
        # original task deadline. Renewal never refreshes the execution budget.
        with self._transaction() as conn:
            run, now = self._load(conn, run_id), self._now()
            token = TypeAdapter(CanonicalId).validate_python(lease_token, strict=True)
            if (run.state != "running" or token != run.leaseToken or now >= run.leaseExpiresAt
                or now >= run.checkpoint.deadlineAt):
                raise AgentError("agent_lease_expired", 409)
            run = self._cas_lease(conn, run, now=now, token=token,
                expires=min(now + self.lease_seconds, run.checkpoint.deadlineAt), checkpoint=run.checkpoint)
            self._audit(conn, run, "heartbeat", now)
            return run

    def _guard(self, conn, identity):
        identity = checked_model(ExecutionIdentity, identity)
        self._check_execution(identity)
        run, now = self._load(conn, identity.runId), self._now()
        if (run.state != "running" or run.leaseToken != identity.leaseToken
            or now >= run.leaseExpiresAt or now >= run.checkpoint.deadlineAt):
            raise AgentError("agent_lease_expired", 409)
        return identity, run, now

    def _step(self, row):
        return checked_model(StepRecord, dict(runId=row["run_id"], seq=row["seq"], operationKey=row["operation_key"],
            action=baselines.strict_json(row["action_json"]), resultJson=row["result_json"],
            state=row["state"], createdAt=row["created_at"]), max_bytes=131072)

    def plan_step(self, identity, action):
        """Reserve one attempted tool before computation, without executing it.

        Planned replay is explicitly uncertain. The future worker must not
        interpret it as successful or refund a failed/interrupted attempt.
        """
        return self.reserve_step(identity, action).step

    def reserve_decision(self, identity, *, prompt_digest, input_digest, correction_of=None):
        intent = checked_model(DecisionIntent, dict(promptDigest=prompt_digest, inputDigest=input_digest,
            correctionOf=correction_of))
        raw = baselines.canonical_json(intent.model_dump(mode="json"))
        with self._transaction() as conn:
            identity, run, now = self._guard(conn, identity)
            old = conn.execute("SELECT * FROM agent_steps WHERE operation_key=?", (identity.operationKey,)).fetchone()
            if old is not None:
                step = self._step(old)
                if step.runId != run.id or step.seq != identity.seq or old["action_json"] != raw:
                    raise AgentError("agent_step_conflict", 409)
                return StepReservation(step, False)
            next_seq = conn.execute("SELECT coalesce(max(seq),-1)+1 FROM agent_steps WHERE run_id=?", (run.id,)).fetchone()[0]
            if identity.seq != next_seq:
                raise AgentError("agent_step_conflict", 409)
            checkpoint = run.checkpoint
            if checkpoint.modelAttemptsUsed >= checkpoint.modelAttemptLimit:
                raise AgentError("agent_model_budget_exhausted", 409)
            retries = checkpoint.retryCounts
            if correction_of is not None:
                parent_row = conn.execute("SELECT * FROM agent_steps WHERE operation_key=? AND run_id=?",
                    (correction_of, run.id)).fetchone()
                if parent_row is None:
                    raise AgentError("agent_correction_invalid", 409)
                parent = self._step(parent_row)
                if (not isinstance(parent.action, DecisionIntent) or parent.action.correctionOf is not None
                    or (parent.state == "completed" and checked_model(DecisionResult, parent.resultJson).status != "invalid")):
                    raise AgentError("agent_correction_invalid", 409)
                key = baselines.digest(dict(decisionEpisode=parent.operationKey))
                if any(r.kind == "model" and r.keyDigest == key for r in retries):
                    raise AgentError("agent_retry_exhausted", 409)
                from .contracts import RetryCount
                retries = (*retries, RetryCount(kind="model", keyDigest=key, used=1))
            checkpoint = checked_model(AgentCheckpoint, checkpoint.model_copy(update={
                "modelAttemptsUsed": checkpoint.modelAttemptsUsed + 1, "retryCounts": retries}), max_bytes=262144)
            conn.execute("INSERT INTO agent_steps(run_id,seq,operation_key,action_json,state,created_at) "
                "VALUES(?,?,?,?,'planned',?)", (run.id, identity.seq, identity.operationKey, raw, now))
            run = self._cas_lease(conn, run, now=now, token=run.leaseToken,
                expires=run.leaseExpiresAt, checkpoint=checkpoint)
            self._audit(conn, run, "step_planned", now, identity=identity, payload=intent.model_dump(mode="json"))
            return StepReservation(self._step(conn.execute(
                "SELECT * FROM agent_steps WHERE operation_key=?", (identity.operationKey,)).fetchone()), True)

    def complete_decision(self, identity, result):
        result = checked_model(DecisionResult, result)
        raw = baselines.canonical_json(result.model_dump(mode="json"))
        with self._transaction() as conn:
            identity, run, now = self._guard(conn, identity)
            row = conn.execute("SELECT * FROM agent_steps WHERE operation_key=?", (identity.operationKey,)).fetchone()
            if row is None:
                raise AgentError("agent_step_not_found", 404)
            step = self._step(row)
            if (step.runId != run.id or step.seq != identity.seq or not isinstance(step.action, DecisionIntent)
                or step.action.promptDigest != result.promptDigest or step.action.inputDigest != result.inputDigest):
                raise AgentError("agent_step_conflict", 409)
            if self._complete(conn, identity, step, raw):
                run = self._cas_lease(conn, run, now=now, token=run.leaseToken,
                    expires=run.leaseExpiresAt, checkpoint=run.checkpoint)
                self._audit(conn, run, "step_completed", now, identity=identity, payload=result.model_dump(mode="json"))
            return self._step(conn.execute("SELECT * FROM agent_steps WHERE operation_key=?", (identity.operationKey,)).fetchone())

    def reserve_step(self, identity, action, *, retry_of=None):
        """Return freshness from the same transaction that reserves the intent.

        Only the caller that inserted it may execute. Reading a planned row
        first and reserving it later would let concurrent callers both execute.
        """
        action = parse_tool_action(action)
        if retry_of is not None:
            try:
                retry_of = TypeAdapter(CanonicalId).validate_python(retry_of, strict=True)
            except Exception:
                raise AgentError() from None
        with self._transaction() as conn:
            identity, run, now = self._guard(conn, identity)
            context, args = run.manifest.context, action.arguments
            if action.tool not in context.allowedTools:
                raise AgentError("agent_tool_forbidden", 409)
            if action.tool == "get_turn_trace" and args.turnId != context.turnId:
                raise AgentError("agent_scope_invalid", 409)
            if action.tool == "retrieve_truth" and (args.soupId != context.soupId
                or args.puzzleVersion != context.observedPuzzleVersion):
                raise AgentError("agent_scope_invalid", 409)
            if action.tool in {"find_rule_conflicts", "run_regression", "save_candidate_rule"}:
                draft = args.draft
                if (draft.soupId != context.soupId or draft.puzzleVersion != context.observedPuzzleVersion
                    or draft.baseRuleVersion != context.baseRuleVersion
                    or not set(draft.factIds) <= {f.id for f in context.factScope}
                    or (action.tool == "find_rule_conflicts" and args.baseRuleVersion != context.baseRuleVersion)):
                    raise AgentError("agent_scope_invalid", 409)
            raw = baselines.canonical_json(action.model_dump(mode="json"))
            old = conn.execute("SELECT * FROM agent_steps WHERE operation_key=?", (identity.operationKey,)).fetchone()
            if old is not None:
                step = self._step(old)
                if step.runId != run.id or step.seq != identity.seq or old["action_json"] != raw:
                    raise AgentError("agent_step_conflict", 409)
                return StepReservation(step, False)
            next_seq = conn.execute("SELECT coalesce(max(seq),-1)+1 FROM agent_steps WHERE run_id=?", (run.id,)).fetchone()[0]
            if identity.seq != next_seq:
                raise AgentError("agent_step_conflict", 409)
            if run.checkpoint.toolAttemptsUsed >= run.checkpoint.toolAttemptLimit:
                raise AgentError("agent_tool_budget_exhausted", 409)
            retries = run.checkpoint.retryCounts
            if retry_of is not None:
                parent_row = conn.execute("SELECT * FROM agent_steps WHERE operation_key=? AND run_id=?",
                    (retry_of, run.id)).fetchone()
                if parent_row is None:
                    raise AgentError("agent_retry_invalid", 409)
                parent = self._step(parent_row)
                if (parent.action.action != "tool" or parent.state not in {"planned", "failed"}
                    or parent_row["action_json"] != raw):
                    raise AgentError("agent_retry_invalid", 409)
                key = baselines.digest(action.model_dump(mode="json"))
                if any(r.kind == "tool" and r.keyDigest == key for r in retries):
                    raise AgentError("agent_retry_exhausted", 409)
                from .contracts import RetryCount
                retries = (*retries, RetryCount(kind="tool", keyDigest=key, used=1))
            checkpoint = checked_model(AgentCheckpoint, run.checkpoint.model_copy(update={
                "toolAttemptsUsed": run.checkpoint.toolAttemptsUsed + 1, "retryCounts": retries}), max_bytes=262144)
            conn.execute("INSERT INTO agent_steps(run_id,seq,operation_key,action_json,state,created_at) "
                "VALUES(?,?,?,?,'planned',?)", (run.id, identity.seq, identity.operationKey, raw, now))
            run = self._cas_lease(conn, run, now=now, token=run.leaseToken,
                expires=run.leaseExpiresAt, checkpoint=checkpoint)
            self._audit(conn, run, "step_planned", now, identity=identity, payload=action.model_dump(mode="json"))
            return StepReservation(self._step(conn.execute(
                "SELECT * FROM agent_steps WHERE operation_key=?", (identity.operationKey,)).fetchone()), True)

    def _owned_step(self, conn, identity, *, tool):
        row = conn.execute("SELECT * FROM agent_steps WHERE operation_key=?", (identity.operationKey,)).fetchone()
        if row is None:
            raise AgentError("agent_step_not_found", 404)
        step = self._step(row)
        if (step.runId != identity.runId or step.seq != identity.seq or step.action.action != "tool"
            or step.action.tool != tool):
            raise AgentError("agent_step_conflict", 409)
        return step

    def _complete(self, conn, identity, step, raw, *, state="completed"):
        if step.state != "planned":
            if step.state != state or step.resultJson != raw:
                raise AgentError("agent_step_conflict", 409)
            return False
        changed = conn.execute("UPDATE agent_steps SET state=?,result_json=? "
            "WHERE operation_key=? AND run_id=? AND seq=? AND state='planned'", (
                state, raw, identity.operationKey, identity.runId, identity.seq))
        if changed.rowcount != 1:
            raise AgentError("agent_step_conflict", 409)
        return True

    def fail_step(self, identity, code):
        failure = checked_model(ToolFailure, dict(code=code))
        raw = baselines.canonical_json(failure.model_dump(mode="json"))
        with self._transaction() as conn:
            identity, run, now = self._guard(conn, identity)
            row = conn.execute("SELECT * FROM agent_steps WHERE operation_key=?", (identity.operationKey,)).fetchone()
            if row is None:
                raise AgentError("agent_step_not_found", 404)
            step = self._step(row)
            if step.runId != run.id or step.seq != identity.seq or step.action.action != "tool":
                raise AgentError("agent_step_conflict", 409)
            if self._complete(conn, identity, step, raw, state="failed"):
                run = self._cas_lease(conn, run, now=now, token=run.leaseToken,
                    expires=run.leaseExpiresAt, checkpoint=run.checkpoint)
                self._audit(conn, run, "step_failed", now, identity=identity, payload=failure.model_dump(mode="json"))
            return self._owned_step(conn, identity, tool=step.action.tool)

    def complete_tool(self, identity, result):
        """Three typed read/proof successes. Other results have dedicated paths."""
        from .tool_contracts import (ConflictToolResult, TraceResult, TruthResult,
            checked_tool_success, trace_result, truth_result)
        result = checked_tool_success(result)
        with self._transaction() as conn:
            identity, run, now = self._guard(conn, identity)
            step = self._owned_step(conn, identity, tool=result.tool)
            context = run.manifest.context
            if isinstance(result, TraceResult):
                expected = trace_result(context)
            else:
                soup = baselines.session_soup(conn, context.observedPuzzleVersion)
                if isinstance(result, TruthResult):
                    expected = truth_result(soup, context, step.action.arguments.query)
                elif isinstance(result, ConflictToolResult):
                    from ..rule_contract import read_rule_snapshot
                    from .validation import validate_candidate
                    rules = read_rule_snapshot(conn, context.observedPuzzleVersion, context.baseRuleVersion)
                    expected = ConflictToolResult(conflict=validate_candidate(step.action.arguments.draft,
                        context=context, soup=soup, rule_snapshot=rules))
                else:
                    raise AgentError("agent_result_invalid", 422)
            if result != expected:
                raise AgentError("agent_result_mismatch", 409)
            raw = baselines.canonical_json(result.model_dump(mode="json"))
            if self._complete(conn, identity, step, raw):
                run = self._cas_lease(conn, run, now=now, token=run.leaseToken,
                    expires=run.leaseExpiresAt, checkpoint=run.checkpoint)
                self._audit(conn, run, "step_completed", now, identity=identity, payload=result.model_dump(mode="json"))
            return self._owned_step(conn, identity, tool=result.tool)

    def _report_binding(self, run, step, report):
        draft = step.action.arguments.draft
        if (report.reportId != step.operationKey or report.runId != run.id
            or report.draftDigest != draft_digest(draft) or report.contextDigest != run.manifest.contextDigest
            or report.puzzleVersion != run.manifest.context.observedPuzzleVersion
            or report.baseRuleVersion != run.manifest.context.baseRuleVersion
            or (run.manifest.suiteManifestDigest is not None and report.suiteManifestDigest != run.manifest.suiteManifestDigest)
            or (run.manifest.suiteManifestDigest is None and report.status == "complete")
            or (report.evidenceKind == "synthetic_fixture" and run.manifest.trafficClass != "test")):
            raise AgentError("agent_report_mismatch", 409)

    def complete_regression(self, identity, report):
        """Trusted fixed executor result; model JSON cannot call this method."""
        report = checked_model(RegressionReport, report)
        raw = baselines.canonical_json(report.model_dump(mode="json"))
        with self._transaction() as conn:
            identity, run, now = self._guard(conn, identity)
            step = self._owned_step(conn, identity, tool="run_regression")
            self._report_binding(run, step, report)
            if self._complete(conn, identity, step, raw):
                run = self._cas_lease(conn, run, now=now, token=run.leaseToken,
                    expires=run.leaseExpiresAt, checkpoint=run.checkpoint)
                self._audit(conn, run, "step_completed", now, identity=identity, payload=report.model_dump(mode="json"))
            return self._owned_step(conn, identity, tool="run_regression")

    def save_candidate(self, identity, draft, regression_report_id):
        draft = checked_draft(draft)
        with self._transaction() as conn:
            identity, run, now = self._guard(conn, identity)
            step = self._owned_step(conn, identity, tool="save_candidate_rule")
            args = step.action.arguments
            if args.draft != draft or args.regressionReportId != regression_report_id:
                raise AgentError("agent_step_conflict", 409)
            report_id = TypeAdapter(CanonicalId).validate_python(regression_report_id, strict=True)
            row = conn.execute("SELECT * FROM agent_steps WHERE operation_key=? AND run_id=?", (report_id, run.id)).fetchone()
            if row is None:
                raise AgentError("agent_report_unavailable", 409)
            source = self._step(row)
            if (source.state != "completed" or source.action.action != "tool"
                or source.action.tool != "run_regression" or source.action.arguments.draft != draft):
                raise AgentError("agent_report_unavailable", 409)
            report = checked_model(RegressionReport, source.resultJson)
            self._report_binding(run, source, report)
            if report.status != "complete" or run.manifest.suiteManifestDigest is None:
                raise AgentError("agent_report_incomplete", 409)
            # Valid fact identity/green mechanical checks are not a semantic
            # certificate. Only store a pending proposal after pure conflicts.
            from ..rule_contract import read_rule_snapshot
            from .validation import validate_candidate
            soup = baselines.session_soup(conn, draft.puzzleVersion)
            snapshot = read_rule_snapshot(conn, draft.puzzleVersion, draft.baseRuleVersion)
            conflict = validate_candidate(draft, context=run.manifest.context, soup=soup, rule_snapshot=snapshot)
            if conflict.status not in {"no_known_conflict", "reviewable_replace"}:
                raise AgentError("agent_candidate_conflict", 409)
            proof = baselines.digest(report.model_dump(mode="json"))
            digest = candidate_digest(draft, run_id=run.id, report_id=report_id, report_digest=proof)
            old = conn.execute("SELECT * FROM rule_candidates WHERE run_id=?", (run.id,)).fetchone()
            if old is not None:
                candidate = checked_model(CandidateRecord, old["candidate_json"])
                if (old["candidate_digest"] != digest or candidate.candidateDigest != digest
                    or candidate.runId != run.id or candidate.draft != draft or old["status"] != "pending"
                    or old["soup_id"] != draft.soupId or old["base_rule_version"] != draft.baseRuleVersion
                    or old["regression_json"] != baselines.canonical_json(report.model_dump(mode="json"))):
                    raise AgentError("agent_candidate_conflict", 409)
            else:
                candidate = CandidateRecord(id=str(uuid4()), runId=run.id, draft=draft, regressionReportId=report_id,
                    reportDigest=proof, candidateDigest=digest, createdAt=now)
                conn.execute("INSERT INTO rule_candidates(id,run_id,soup_id,base_rule_version,candidate_json,candidate_digest,"
                    "regression_json,status,created_at) VALUES(?,?,?,?,?,?,?,'pending',?)", (candidate.id, run.id,
                        draft.soupId, draft.baseRuleVersion, candidate.model_dump_json(warnings="error"), digest,
                        baselines.canonical_json(report.model_dump(mode="json")), now))
            raw = baselines.canonical_json(candidate.model_dump(mode="json"))
            if self._complete(conn, identity, step, raw):
                run = self._cas_lease(conn, run, now=now, token=run.leaseToken,
                    expires=run.leaseExpiresAt, checkpoint=run.checkpoint)
                self._audit(conn, run, "candidate_saved", now, identity=identity, candidate=candidate,
                    payload=candidate.model_dump(mode="json"))
            return candidate

    def _reviewable_candidate(self, conn, run, candidate_id):
        row = conn.execute("SELECT * FROM rule_candidates WHERE id=? AND run_id=?", (candidate_id, run.id)).fetchone()
        if row is None or row["status"] != "pending":
            raise AgentError("agent_candidate_unavailable", 409)
        candidate = checked_model(CandidateRecord, row["candidate_json"])
        if (candidate.id != row["id"] or candidate.runId != run.id or candidate.createdAt != row["created_at"]
            or candidate.draft.soupId != row["soup_id"] or candidate.draft.baseRuleVersion != row["base_rule_version"]
            or candidate.candidateDigest != row["candidate_digest"]):
            raise AgentError("agent_candidate_conflict", 409)
        report_row = conn.execute("SELECT * FROM agent_steps WHERE operation_key=? AND run_id=?", (
            candidate.regressionReportId, run.id)).fetchone()
        if report_row is None:
            raise AgentError("agent_report_unavailable", 409)
        source = self._step(report_row)
        if (source.state != "completed" or source.action.action != "tool"
            or source.action.tool != "run_regression" or source.action.arguments.draft != candidate.draft):
            raise AgentError("agent_report_unavailable", 409)
        report = checked_model(RegressionReport, source.resultJson)
        self._report_binding(run, source, report)
        if (report.status != "complete" or candidate.reportDigest != baselines.digest(report.model_dump(mode="json"))
            or row["regression_json"] != baselines.canonical_json(report.model_dump(mode="json"))):
            raise AgentError("agent_report_unavailable", 409)
        return candidate

    def finish(self, identity, action):
        """Stop, never approve. Finish retry is an authorized immutable replay."""
        identity = checked_model(ExecutionIdentity, identity)
        action = parse_agent_action(action)
        if not isinstance(action, FinishAction):
            raise AgentError("agent_finish_invalid", 422)
        raw_action = baselines.canonical_json(action.model_dump(mode="json"))
        outcome = FinishRecord(runId=identity.runId, candidateId=action.candidateId,
            state="awaiting_review" if action.candidateId is not None else "needs_human",
            executionDigest=baselines.digest(identity.model_dump(mode="json")))
        raw_result = baselines.canonical_json(outcome.model_dump(mode="json"))
        with self._transaction() as conn:
            # Replays still re-freeze live permission/base. They are reads, not
            # new work with the cleared terminal lease or a refreshed deadline.
            run = self._load(conn, identity.runId)
            old = conn.execute("SELECT * FROM agent_steps WHERE operation_key=?", (identity.operationKey,)).fetchone()
            if old is not None:
                step = self._step(old)
                if (step.runId != run.id or step.seq != identity.seq or not isinstance(step.action, FinishAction)
                    or old["action_json"] != raw_action or step.state != "completed" or step.resultJson != raw_result
                    or run.state != outcome.state):
                    raise AgentError("agent_step_conflict", 409)
                checked_model(FinishRecord, step.resultJson)
                return run
            identity, run, now = self._guard(conn, identity)
            next_seq = conn.execute("SELECT coalesce(max(seq),-1)+1 FROM agent_steps WHERE run_id=?", (run.id,)).fetchone()[0]
            if identity.seq != next_seq or run.rowVersion == 9223372036854775807 or now < run.updatedAt:
                raise AgentError("agent_run_conflict", 409)
            candidate = None if action.candidateId is None else self._reviewable_candidate(conn, run, action.candidateId)
            conn.execute("INSERT INTO agent_steps(run_id,seq,operation_key,action_json,result_json,state,created_at) "
                "VALUES(?,?,?,?,?,'completed',?)", (run.id, identity.seq, identity.operationKey, raw_action, raw_result, now))
            changed = conn.execute("UPDATE agent_runs SET state=?,lease_token=NULL,lease_expires_at=NULL,updated_at=?,"
                "row_version=row_version+1 WHERE id=? AND row_version=?", (outcome.state, now, run.id, run.rowVersion))
            if changed.rowcount != 1:
                raise AgentError("agent_run_conflict", 409)
            run = self._load(conn, run.id)
            self._audit(conn, run, outcome.state, now, identity=identity, candidate=candidate,
                payload=outcome.model_dump(mode="json"))
            return run
