"""Pure unapproved exact override of an already computed original host result.

The fixed regression executor supplies the real baseline decision first, with
actual prior context. This is not a RuleSnapshot, receipt or published release.
"""
from ..question_normalization import normalize_exact_question
from ..schemas import HostResult, HostVersions
from .contracts import AgentError, checked_draft, checked_model
from .validation import validate_candidate


class CandidatePreview:
    def __init__(self, draft, *, context, soup, rule_snapshot):
        draft = checked_draft(draft)
        conflict = validate_candidate(draft, context=context, soup=soup, rule_snapshot=rule_snapshot)
        if conflict.status not in {"no_known_conflict", "reviewable_replace"}:
            raise AgentError("agent_candidate_conflict", 409)
        self._draft = draft
        self._versions = HostVersions(puzzleVersion=draft.puzzleVersion, ruleVersion=draft.baseRuleVersion)

    def apply(self, question, baseline_result):
        original = checked_model(HostResult, baseline_result)
        if original.versions != self._versions:
            raise AgentError("agent_preview_version_mismatch", 409)
        if type(question) is not str or not 1 <= len(question) <= 500:
            raise AgentError("agent_input_invalid", 422)
        # A proposed exact rule cannot turn an earlier reminder, win or model
        # failure into an ordinary charged answer. The original host owns flow.
        if original.kind != "answer":
            return original
        try:
            key = normalize_exact_question(question)
        except ValueError:
            return original
        if key != self._draft.canonicalQuestionKey:
            return original
        return HostResult(kind="answer", answer=self._draft.answer, reply=self._draft.answer,
            chargeable=True, source="deterministic", versions=original.versions,
            evidenceIds=self._draft.factIds, contextIndependent=False, cacheHit=False,
            matchedCheckpoint="candidate_preview")
