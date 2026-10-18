"""Actual model-selected bounded loop over durable intents and outcomes."""
from threading import Event
from uuid import uuid4

from ..model_gateway import ModelFailure, ModelGateway
from .agent_prompt import build_decision_messages
from .contracts import AgentError, ExecutionIdentity, FinishAction, checked_model
from .decision_contracts import DecisionIntent, DecisionResult
from .store import AgentStore
from .tools import ToolExecutor


class RepairAgent:
    def __init__(self, store, executor, gateway):
        if (not isinstance(store, AgentStore) or not isinstance(executor, ToolExecutor)
            or executor.store is not store or not isinstance(gateway, ModelGateway)
            or store.runtime.model_gateway is not gateway):
            raise TypeError("Explicit owned store, executor and shared gateway required")
        self.store, self.executor, self.gateway = store, executor, gateway

    @staticmethod
    def _identity(run, steps):
        return ExecutionIdentity(runId=run.id, leaseToken=run.leaseToken,
            operationKey=str(uuid4()), seq=len(steps))

    def _handoff(self, run_id, token, reason):
        try:
            return self.store.stop(run_id, lease_token=token, state="needs_human", reason=reason)
        except AgentError:
            # A cancelled task/new owner cannot be overwritten by this owner.
            # Return its minimal ACTUAL status, not a fabricated terminal state.
            return self.store.read_status(run_id)

    def drive(self, run_id, lease_token, cancelled):
        if not isinstance(cancelled, Event):
            raise TypeError("An owned cancellation event is required")
        with self.store.execution_scope(run_id, lease_token, cancelled):
            return self._drive(run_id, lease_token, cancelled)

    def _drive(self, run_id, lease_token, cancelled):
        while True:
            try:
                if self.store.runtime.closed:
                    return self._handoff(run_id, lease_token, "shutting_down")
                run = self.store.read(run_id)
                if run.state != "running" or run.leaseToken != lease_token:
                    return self.store.read_status(run_id)
                remaining = run.checkpoint.deadlineAt - self.store._now()
                if remaining <= 0:
                    return self._handoff(run_id, lease_token, "deadline")
                if cancelled.is_set():
                    return self._handoff(run_id, lease_token, "model_unavailable")
                steps = self.store.steps(run_id)
                last = steps[-1] if steps else None
                action, correction, retry = None, None, None
                if last is not None and isinstance(last.action, DecisionIntent):
                    if last.state == "planned":
                        if last.action.correctionOf is not None:
                            return self._handoff(run_id, lease_token, "model_unavailable")
                        correction = last.operationKey
                    else:
                        result = checked_model(DecisionResult, last.resultJson)
                        if result.status == "valid":
                            action = result.action
                        elif result.status == "invalid":
                            if last.action.correctionOf is not None:
                                return self._handoff(run_id, lease_token, "model_output_invalid")
                            correction = last.operationKey
                        else:
                            return self._handoff(run_id, lease_token, "model_unavailable")
                elif last is not None and last.action.action == "tool" and last.state in {"planned", "failed"}:
                    # A genuinely new reservation spends the remaining budget;
                    # the old unknown/failed intent is never re-executed free.
                    action, retry = last.action, last.operationKey
                if action is not None:
                    execution = self._identity(run, steps)
                    if isinstance(action, FinishAction):
                        self.store.finish(execution, action)
                        return self.store.read_status(run_id)
                    if run.checkpoint.toolAttemptsUsed >= run.checkpoint.toolAttemptLimit:
                        return self._handoff(run_id, lease_token, "budget_exhausted")
                    try:
                        self.executor.execute(execution, action, retry_of=retry)
                    except AgentError as error:
                        if error.code != "agent_tool_failed":
                            raise
                        # Executor persists a failed intent then raises. The
                        # next live guard reads that outcome and applies the
                        # one durable retry; withdrawal still denies all work.
                    continue
                # Limits only block NEW calls. A last stored valid decision
                # can still dispatch its remaining tool or finish at 10-used.
                if run.checkpoint.modelAttemptsUsed >= run.checkpoint.modelAttemptLimit:
                    return self._handoff(run_id, lease_token, "budget_exhausted")
                state = self.gateway.snapshot()
                if state["closed"] or state["active_agent"] or state["cleanup_failed"]:
                    return self._handoff(run_id, lease_token, "model_unavailable")
                prompt = build_decision_messages(run, steps)
                execution = self._identity(run, steps)
                reservation = self.store.reserve_decision(execution, prompt_digest=prompt.promptDigest,
                    input_digest=prompt.inputDigest, correction_of=correction)
                if not reservation.newly_created:
                    raise AgentError("agent_step_uncertain", 409)

                def before_attempt(_attempt, _deadline):
                    # Adapter construction/admission may wait after reservation.
                    # Recheck this already-spent intent at the actual dispatch
                    # boundary; refusal cannot refund or reserve another call.
                    with self.store._transaction(write=False) as conn:
                        self.store._guard(conn, execution)
                        row = conn.execute("SELECT * FROM agent_steps WHERE operation_key=?",
                            (execution.operationKey,)).fetchone()
                        if row is None or self.store._step(row) != reservation.step:
                            raise AgentError("agent_step_conflict", 409)
                try:
                    selected = self.gateway.invoke(prompt.messages,
                        deadline=self.gateway._clock() + min(45.0, max(0.0,
                            run.checkpoint.deadlineAt - self.store._now())),
                        max_attempts=1, cancelled=cancelled, before_attempt=before_attempt,
                        traffic_class="agent", response_contract="repair_action")
                    result = DecisionResult(status="valid", action=selected, errorCode=None,
                        promptDigest=prompt.promptDigest, inputDigest=prompt.inputDigest)
                except ModelFailure as error:
                    status = "invalid" if error.code == "model_output_invalid" else "cancelled" \
                        if error.code == "model_cancelled" else "unavailable"
                    result = DecisionResult(status=status, action=None, errorCode=error.code,
                        promptDigest=prompt.promptDigest, inputDigest=prompt.inputDigest)
                self.store.complete_decision(execution, result)
            except AgentError as error:
                expired = False
                if not self.store.runtime.closed and error.code == "agent_execution_cancelled":
                    try:
                        self.store.read(run_id)
                    except AgentError as current_error:
                        # Cancellation removes write authority, not the more
                        # specific reason from the current safe source guard.
                        error = current_error
                if not self.store.runtime.closed and error.code in {"agent_lease_expired", "agent_execution_cancelled"}:
                    try:
                        deadline = self.store.read_status(run_id).deadlineAt
                        expired = deadline is not None and self.store._now() >= deadline
                    except AgentError:
                        pass  # Unknown status is not invented deadline proof.
                # Closing can race a blocked model/result commit. Only the
                # terminal stop path remains authorized; do not mislabel the
                # rejected late write as a tool computation failure.
                reason = "shutting_down" if self.store.runtime.closed else \
                    "deadline" if expired else \
                    "model_unavailable" if error.code == "agent_execution_cancelled" else \
                    "budget_exhausted" if error.code in {"agent_model_budget_exhausted", "agent_tool_budget_exhausted"} \
                    else "context_too_large" if error.code == "agent_context_too_large" \
                    else "source_changed" if error.code in {"agent_context_stale", "agent_source_reload_required", "agent_suite_changed"} \
                    else "deadline" if expired or error.code == "agent_deadline_exhausted" else "tool_failed"
                return self._handoff(run_id, lease_token, reason)
