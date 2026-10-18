"""Verify actual publication history before observing its immutable rule version."""
from dataclasses import dataclass

from pydantic import TypeAdapter

from . import baselines, migrations
from .agents.contracts import checked_model
from .audit_events import AuditEvent, CandidatePublicationDetails, CanonicalId, RuleBusinessDetails
from .candidate_review import CandidateReviewStore
from .post_publication_contracts import PostPublicationError
from .rule_contract import RuleVersion, rule_suspension_state
from .runtime import runtime_context
from .task_context import _freeze


@dataclass(frozen=True)
class PublishedSource:
    candidateId: str
    publicationOperationKey: str
    publicationProofDigest: str
    soupId: str
    puzzleVersion: str
    publishedRuleVersion: str
    publishedAt: float
    trafficClass: str


class PostPublicationSourceResolver:
    """Read verified history, not the mutable pointer or a passing preview.

    Original candidate/report/approval validation stays in its existing owner;
    this narrow projection adds necessary publication audits and fresh privacy.
    No current corpus, model, agent execution or candidate re-signing occurs.
    """
    def __init__(self, runtime):
        self.runtime = runtime
        self.review = CandidateReviewStore(runtime)

    @staticmethod
    def _audits(conn, operation_key):
        rows = conn.execute("SELECT * FROM audit_events WHERE event_type IN ('candidate_published','rule_published') "
            "AND json_extract(CASE WHEN json_valid(details_json) THEN details_json ELSE '{}' END, "
            "'$.details.operationKey')=? LIMIT 3", (operation_key,)).fetchall()
        if len(rows) != 2:
            raise ValueError('Missing or ambiguous necessary audits')
        events = {}
        for row in rows:
            event = checked_model(AuditEvent, row['details_json'])
            if (row['details_json'] != baselines.canonical_json(event.model_dump(mode='json'))
                or row['event_type'] in events
                or tuple(row[name] for name in ('id', 'request_id', 'session_id', 'turn_id', 'run_id', 'event_type', 'created_at'))
                    != (event.eventId, event.requestId, event.sessionId, event.turnId, event.runId, event.eventType, event.createdAt)):
                raise ValueError('Necessary audit projection mismatch')
            events[event.eventType] = event
        if set(events) != {'candidate_published', 'rule_published'}:
            raise ValueError('Necessary audit types missing')
        return events

    def load(self, conn, candidate_id, rule_version):
        try:
            candidate_id = TypeAdapter(CanonicalId).validate_python(candidate_id, strict=True)
            rule_version = TypeAdapter(RuleVersion).validate_python(rule_version, strict=True)
            if self.runtime.closed:
                raise ValueError('Runtime closed')
            with runtime_context(self.runtime):
                migrations.verify_schema(conn, required_version=3)
                row, candidate, report, run, _ = self.review._immutable(conn, candidate_id)
                state, review_version, _ = self.review._review_state(conn, row, candidate, run)
                if (state is None or state.status != 'published' or state.publishedRuleVersion != rule_version
                    or rule_suspension_state(conn, rule_version)):
                    raise ValueError('No usable publication of requested version')
                context = run.manifest.context
                fresh = _freeze(conn, context.feedbackId, context.sourceFeedbackVersion, context.allowedTools)
                if fresh.model_copy(update={'baseRuleVersion': context.baseRuleVersion}) != context:
                    raise ValueError('Original private source or permission changed')
                operation = self.review._operation(conn, state.lastOperationKey)
                if operation is None or operation.intent.action != 'published':
                    raise ValueError('No actual published operation')
                release = conn.execute('SELECT created_at FROM rule_releases WHERE id=?', (rule_version,)).fetchone()
                if release is None:
                    raise ValueError('Missing actual immutable release')
                events = self._audits(conn, state.lastOperationKey)
                traffic = run.manifest.trafficClass
                expected_candidate = CandidatePublicationDetails(candidateId=candidate.id, runId=run.id,
                    operationKey=state.lastOperationKey, approvalOperationKey=state.approvalOperationKey,
                    reviewVersion=review_version, candidateDigest=candidate.candidateDigest,
                    reportDigest=candidate.reportDigest, proofDigest=state.proofDigest,
                    fromRuleVersion=candidate.draft.baseRuleVersion, toRuleVersion=rule_version,
                    pointerVersion=operation.intent.request.expectedPointerVersion + 1, trafficClass=traffic)
                expected_rule = RuleBusinessDetails(operationKey=state.lastOperationKey, action='published',
                    fromRuleVersion=candidate.draft.baseRuleVersion, toRuleVersion=rule_version,
                    pointerVersion=operation.intent.request.expectedPointerVersion + 1, soupId=candidate.draft.soupId,
                    **state.reviewReceipt.model_dump(exclude={'puzzleVersion', 'baseRuleVersion', 'status'}),
                    trafficClass=traffic)
                if (events['candidate_published'].details != expected_candidate
                    or events['candidate_published'].createdAt != state.reviewedAt
                    or events['candidate_published'].runId != run.id
                    or events['candidate_published'].requestId != state.lastOperationKey
                    or events['rule_published'].details != expected_rule
                    or events['rule_published'].createdAt != release['created_at']):
                    raise ValueError('Publication audits differ from actual operation')
                proof = baselines.digest(dict(operation=operation.model_dump(mode='json'),
                    audits={kind: event.model_dump(mode='json') for kind, event in events.items()},
                    publishedAt=release['created_at'], privateSourceDigest=baselines.digest(context.model_dump(mode='json'))))
                if self.runtime.closed:
                    raise ValueError('Runtime closed during source verification')
                return PublishedSource(candidate.id, state.lastOperationKey, proof, candidate.draft.soupId,
                    candidate.draft.puzzleVersion, rule_version, release['created_at'], traffic)
        except Exception:
            raise PostPublicationError('post_publication_source_invalid', 409) from None
