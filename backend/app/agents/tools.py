"""Closed server-side dispatch; model JSON cannot select Python or resources."""
from .. import baselines
from ..rule_contract import read_rule_snapshot
from .contracts import AgentError, CandidateRecord, RegressionReport, checked_model, parse_tool_action
from .store import AgentStore, ToolFailure
from .tool_contracts import ConflictToolResult, checked_tool_success, trace_result, truth_result
from .validation import validate_candidate


class ToolExecutor:
    def __init__(self, store: AgentStore, *, regression=None):
        if not isinstance(store, AgentStore):
            raise TypeError("An explicit AgentStore is required")
        self.store = store
        if regression is not None:
            from .regression import FixedRegression
            if type(regression) is not FixedRegression or regression.runtime is not store.runtime:
                raise TypeError("Only an owned fixed regression executor is allowed")
        self.regression = regression

    @staticmethod
    def _replay(step):
        if step.state == "failed":
            return checked_model(ToolFailure, step.resultJson)
        if step.action.tool == "run_regression":
            return checked_model(RegressionReport, step.resultJson)
        if step.action.tool == "save_candidate_rule":
            return checked_model(CandidateRecord, step.resultJson)
        return checked_tool_success(step.resultJson)

    def execute(self, identity, value, *, retry_of=None):
        action = parse_tool_action(value)
        reservation = self.store.reserve_step(identity, action, retry_of=retry_of)
        if reservation.step.state != "planned":
            # Reservation has already checked live scope/lease/permission.
            return self._replay(reservation.step)
        if not reservation.newly_created:
            raise AgentError("agent_step_uncertain", 409)
        try:
            # Read frozen inputs in a short transaction, never hold a lock
            # around computation or an owned regression gateway invocation.
            with self.store._transaction(write=False) as conn:
                identity, run, _ = self.store._guard(conn, identity)
                context = run.manifest.context
                soup = baselines.session_soup(conn, context.observedPuzzleVersion)
                rules = read_rule_snapshot(conn, context.observedPuzzleVersion, context.baseRuleVersion)
            args = action.arguments
            if action.tool == "get_turn_trace":
                result = trace_result(context)
            elif action.tool == "retrieve_truth":
                result = truth_result(soup, context, args.query)
            elif action.tool == "find_rule_conflicts":
                result = ConflictToolResult(conflict=validate_candidate(args.draft,
                    context=context, soup=soup, rule_snapshot=rules))
            elif action.tool == "run_regression":
                from .regression import FixedRegression
                executor = self.regression or FixedRegression(self.store.runtime)
                result = executor.run(args.draft, run=run, identity=identity,
                    soup=soup, rule_snapshot=rules)
                self.store.complete_regression(identity, result)
                return result
            elif action.tool == "save_candidate_rule":
                return self.store.save_candidate(identity, args.draft, args.regressionReportId)
            else:
                raise AgentError("agent_tool_forbidden", 409)
            self.store.complete_tool(identity, result)
            return result
        except Exception:
            # Neither raw exceptions nor private inputs become tool outputs.
            # If permission/lease was withdrawn, even this write is refused:
            # the reserved planned attempt remains uncertain, not refunded.
            try:
                self.store.fail_step(identity, "agent_tool_failed")
            except AgentError:
                pass
            raise AgentError("agent_tool_failed", 409) from None
