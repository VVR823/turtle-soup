"""Pure source-scoped candidate validation, no database/model/publication side effects."""


from typing import Annotated, Literal

from pydantic import Field

from .. import baselines
from ..host_evidence import build_evidence_catalog
from ..host_rules import decide_deterministic, question_has_static_scope
from ..rule_contract import Digest, ExactTarget, FactId, RuleSnapshot, exact_targets_from_source
from ..schemas import HostVersions, Soup
from ..task_context import TaskContext
from .contracts import AgentError, StrictAgentModel, checked_draft, checked_model, draft_digest


class ConflictResult(StrictAgentModel):
    status: Literal["duplicate", "conflict", "reviewable_replace", "needs_human", "no_known_conflict"]
    draftDigest: Digest
    canonicalQuestionKey: Annotated[str, Field(min_length=1, max_length=500)]
    targets: Annotated[tuple[ExactTarget, ...], Field(max_length=32)] = ()
    reason: Literal["context_unproven", "target_unproven", "priority_unproven", "existing_answer",
        "existing_conflict", "unique_target", "answer_unproven"]
    answerSupported: None = None
    contextIndependentConfirmed: None = None
    conflictingFactIds: Annotated[tuple[FactId, ...], Field(max_length=32)] = ()
    conflictingSourcesTruncated: bool = False


def validate_candidate(draft, *, context, soup, rule_snapshot):
    """Pure source/conflict proof only; no DB authorizer or semantic approval.

    Reuses the offline catalog's *pure* complete release proof, not its runner,
    CLI, datasets, settings or models. Store operations must additionally
    re-freeze actual feedback permission in their own transaction.
    """
    try:
        draft = checked_draft(draft)
        context = checked_model(TaskContext, context, max_bytes=262144)
        soup = checked_model(Soup, soup, max_bytes=2097152)
        snapshot = checked_model(RuleSnapshot, rule_snapshot, max_bytes=4194304)
        from eval.catalog import validate_catalog
        from eval.contracts import EvalPuzzle
        # Both packages live under backend on the service's import path.
        # Importing this pure module never selects a runtime.
        validate_catalog((EvalPuzzle(soupId=soup.id, puzzleVersion=draft.puzzleVersion,
            soupJson=baselines.canonical_json(soup.model_dump(mode="json")), ruleSnapshot=snapshot),))
        if (draft.soupId != context.soupId or soup.id != context.soupId
            or draft.puzzleVersion != context.observedPuzzleVersion
            or draft.baseRuleVersion != context.baseRuleVersion
            or snapshot.ruleVersion != context.baseRuleVersion):
            raise ValueError("Foreign candidate scope")
        catalog = {f.id: dict(id=f.id, soupId=f.soupId, puzzleVersion=f.puzzleVersion,
            sourcePath=f.sourcePath, category=f.category, payload=f.payload)
            for f in build_evidence_catalog(soup, draft.puzzleVersion)}
        if (len({f.id for f in context.factScope}) != len(context.factScope)
            or any(catalog.get(f.id) != f.model_dump(mode="json") for f in context.factScope)
            or not set(draft.factIds) <= {f.id for f in context.factScope}):
            raise ValueError("Evidence differs from actual source")
        rules = baselines.strict_json(snapshot.releaseRulesJson)
        targets = exact_targets_from_source(soup, draft.puzzleVersion, draft.baseRuleVersion, rules, draft.question)
        if len(targets) > 32:
            raise ValueError("Ambiguous target bound")
        identity = dict(draftDigest=draft_digest(draft), canonicalQuestionKey=draft.canonicalQuestionKey,
            targets=targets)

        def result(status, reason):
            return ConflictResult(status=status, reason=reason, **identity)

        if not question_has_static_scope(soup, draft.question):
            return result("needs_human", "context_unproven")
        # These flows precede every exact rule in the online host. An offline
        # patch must not pretend to override them; arbitrary authored win regex
        # also cannot be run as bounded Agent validation. Keep the live game
        # untouched and leave special-flow changes to explicit human review.
        if soup.always_yes or soup.win_condition:
            return result("needs_human", "priority_unproven")
        ambiguous_paths = []
        decision = decide_deterministic(soup, draft.question, [], versions=HostVersions(
            puzzleVersion=draft.puzzleVersion, ruleVersion=draft.baseRuleVersion), conflict_observer=ambiguous_paths.extend)
        if ambiguous_paths:
            paths = set(ambiguous_paths)
            available = tuple(sorted({f.id for f in context.factScope if f.sourcePath in paths}))
            return ConflictResult(status="needs_human", reason="existing_conflict", **identity,
                conflictingFactIds=available[:32], conflictingSourcesTruncated=len(available) > 32
                    or not paths <= {f.sourcePath for f in context.factScope})
        overlay = next((r for r in snapshot.exactRules if r.canonicalQuestionKey == draft.canonicalQuestionKey), None)
        if draft.operation == "add":
            if len(targets) > 1:
                return result("needs_human", "target_unproven")
            answer = overlay.answer if overlay is not None else decision.answer if decision is not None else None
            if answer is not None:
                return result("duplicate", "existing_answer") if answer == draft.answer else result("conflict", "existing_conflict")
            if targets:
                return result("needs_human", "priority_unproven")
            return result("no_known_conflict", "answer_unproven")
        if len(targets) != 1 or targets[0].targetRuleDigest != draft.targetRuleDigest:
            return result("needs_human", "target_unproven")
        if decision is not None and decision.scope == "metadata":
            return result("needs_human", "priority_unproven")
        if targets[0].type == "confusion":
            expected = {f.id for f in context.factScope if f.sourcePath == targets[0].sourcePath}
            if decision is None or set(decision.evidenceIds) != expected:
                return result("needs_human", "priority_unproven")
        return result("reviewable_replace", "unique_target")
    except AgentError:
        raise
    except Exception:
        raise AgentError("agent_scope_invalid", 409) from None
