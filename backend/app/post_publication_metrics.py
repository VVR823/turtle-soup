"""Birth-verified ledger aggregates in the caller's bounded read snapshot.

No current corpus, provider, private candidate draft/report or player context is
read here. Historical counts are not permission to execute a new observation.
"""
import time

from . import baselines
from .agents.contracts import checked_model
from .audit_events import AuditEvent, CandidatePublicationDetails, RuleBusinessDetails
from .candidate_review_contracts import CandidateOperationReceipt
from .metrics_contracts import (MetricsError, MetricsObservationCounts, MetricsObservationExcluded,
    MetricsObservedRegression, MetricsPostPublicationRegression)
from .post_publication_store import PostPublicationStore
from .rule_contract import ChangeDraft, PublicationRequest, PublishedExactRule, RulePublicationResult


def _source(candidate_json, operation_json, operation_version, rule_json, rule_version,
            rules_json, manifest_json, published_at, parent, audits_json):
    """One verification per publication, not an N+1 private-source lookup."""
    candidate = baselines.strict_json(candidate_json)
    operation = checked_model(CandidateOperationReceipt, operation_json, max_bytes=65536)
    state, intent, result = operation.state, operation.intent, operation.result
    receipt, request = state.reviewReceipt, intent.request
    if (operation_version != 0 or intent.action != 'published'
        or operation_json != baselines.canonical_json(operation.model_dump(mode='json'))
        or candidate['id'] != intent.candidateId or candidate['status'] != 'published'
        or candidate['candidate_digest'] != state.candidateDigest
        or candidate['published_release_id'] != result.publishedRuleVersion
        or candidate['reviewed_at'] != state.reviewedAt or receipt is None
        or candidate['base_rule_version'] != request.expectedRuleVersion
        or parent != request.expectedRuleVersion):
        raise ValueError('Publication metadata mismatch')
    rules, manifest = baselines.strict_json(rules_json), baselines.strict_json(manifest_json)
    soup = candidate['soup_id']
    if (manifest['puzzleVersions'].get(soup) != receipt.puzzleVersion
        or 'r1:' + baselines.digest(dict(rules=rules, manifest=manifest)) != result.publishedRuleVersion):
        raise ValueError('Publication snapshot mismatch')
    exact = [checked_model(PublishedExactRule, raw) for raw in rules['exactQaBySoup'][soup]
        if raw.get('candidateDigest') == state.candidateDigest]
    if len(exact) != 1 or exact[0].reviewReceipt != receipt:
        raise ValueError('Published exact rule missing or ambiguous')
    draft = ChangeDraft(**{name: getattr(exact[0], name) for name in ChangeDraft.model_fields})
    publication = PublicationRequest(operationKey=request.operationKey,
        expectedRuleVersion=request.expectedRuleVersion, expectedPointerVersion=request.expectedPointerVersion,
        changeDraft=draft, regressionReportId=state.reportId, candidateDigest=state.candidateDigest)
    body = baselines.strict_json(rule_json)
    actual = checked_model(RulePublicationResult, body['result'])
    payload = baselines.digest(dict(action='publish', request=publication.model_dump(mode='json'),
        review=receipt.model_dump(mode='json')))
    if (set(body) != {'schemaVersion', 'payloadDigest', 'result'} or type(body['schemaVersion']) is not int
        or body['schemaVersion'] != 1 or rule_version != 0 or body['payloadDigest'] != payload
        or rule_json != baselines.canonical_json(body) or actual.operationKey != request.operationKey
        or actual.ruleVersion != result.publishedRuleVersion
        or actual.pointerVersion != request.expectedPointerVersion + 1 or actual.markerVersion is not None):
        raise ValueError('Committed rule operation mismatch')
    rows = baselines.strict_json(audits_json)
    if len(rows) != 2:
        raise ValueError('Missing or ambiguous necessary audits')
    events = {}
    for row in rows:
        event = checked_model(AuditEvent, row['details_json'], max_bytes=65536)
        if (row['details_json'] != baselines.canonical_json(event.model_dump(mode='json'))
            or event.eventType in events
            or tuple(row[name] for name in ('id', 'request_id', 'session_id', 'turn_id', 'run_id', 'event_type', 'created_at'))
                != (event.eventId, event.requestId, event.sessionId, event.turnId, event.runId, event.eventType, event.createdAt)):
            raise ValueError('Necessary audit projection mismatch')
        events[event.eventType] = event
    if set(events) != {'candidate_published', 'rule_published'}:
        raise ValueError('Necessary audit types missing')
    traffic = events['candidate_published'].details.trafficClass
    expected_candidate = CandidatePublicationDetails(candidateId=candidate['id'], runId=candidate['run_id'],
        operationKey=request.operationKey, approvalOperationKey=state.approvalOperationKey,
        reviewVersion=result.reviewVersion, candidateDigest=state.candidateDigest, reportDigest=state.reportDigest,
        proofDigest=state.proofDigest, fromRuleVersion=request.expectedRuleVersion,
        toRuleVersion=result.publishedRuleVersion, pointerVersion=actual.pointerVersion, trafficClass=traffic)
    expected_rule = RuleBusinessDetails(operationKey=request.operationKey, action='published',
        fromRuleVersion=request.expectedRuleVersion, toRuleVersion=result.publishedRuleVersion,
        pointerVersion=actual.pointerVersion, soupId=soup,
        **receipt.model_dump(exclude={'puzzleVersion', 'baseRuleVersion', 'status'}), trafficClass=traffic)
    if (events['candidate_published'].details != expected_candidate
        or events['candidate_published'].requestId != request.operationKey
        or events['candidate_published'].runId != candidate['run_id']
        or events['candidate_published'].createdAt != state.reviewedAt
        or events['rule_published'].details != expected_rule
        or events['rule_published'].createdAt != published_at):
        raise ValueError('Publication audits differ from actual operation')
    proof = baselines.digest(dict(operation=operation.model_dump(mode='json'),
        audits={kind: event.model_dump(mode='json') for kind, event in events.items()},
        publishedAt=published_at, privateSourceDigest=state.contextDigest))
    return baselines.canonical_json(dict(proof=proof, candidate=candidate['id'], operation=request.operationKey,
        soup=soup, puzzle=receipt.puzzleVersion, rule=result.publishedRuleVersion, publishedAt=published_at, traffic=traffic))


_ROW_FIELDS = ('id', 'operation_key', 'payload_digest', 'candidate_id', 'publication_operation_key',
    'soup_id', 'puzzle_version', 'published_rule_version', 'published_at', 'started_at', 'deadline_at',
    'traffic_class', 'evidence_kind', 'plan_json', 'plan_digest', 'planned_case_count', 'state',
    'attempted_case_count', 'passed_case_count', 'counterexample_case_count', 'error_case_count',
    'unsupported_case_count', 'result_json', 'result_digest', 'finished_at')

def _real_sql(expression):
    # json_object's native REAL rendering rounds timestamp fractions. Preserve
    # round-trip doubles before comparing them with immutable canonical JSON.
    return f"CASE WHEN {expression} IS NULL THEN NULL ELSE json(printf('%!.17g',{expression})) END"


_STAMPS = {'published_at', 'started_at', 'deadline_at', 'finished_at'}
_ROW_JSON = 'json_object(' + ','.join(f"'{name}'," + (
    _real_sql('o.' + name) if name in _STAMPS else 'o.' + name) for name in _ROW_FIELDS) + ')'
_AUDIT_JSON = "json_object('id',id,'request_id',request_id,'session_id',session_id,'turn_id',turn_id," \
    "'run_id',run_id,'event_type',event_type,'created_at'," + _real_sql('created_at') + \
    ",'details_json',CASE WHEN length(CAST(details_json AS BLOB))<=65536 THEN details_json END)"

# The indexed plan window is shared by source verification and aggregation.
# At most three necessary audits per publication cross the Python boundary;
# three is an ambiguity, not permission to select two convenient rows.
_BASE_SQL = """WITH observation_window AS MATERIALIZED (
    SELECT * FROM post_publication_runs WHERE started_at>=:start AND started_at<:end
), publications AS MATERIALIZED (
    SELECT DISTINCT publication_operation_key AS op,candidate_id AS candidate,published_rule_version AS rule
    FROM observation_window
), necessary_audits AS MATERIALIZED (
    SELECT p.op,a.*,row_number() OVER (PARTITION BY p.op ORDER BY a.id) AS position
    FROM publications p JOIN audit_events a ON a.event_type IN ('candidate_published','rule_published')
        AND (a.request_id=p.op OR json_extract(CASE WHEN json_valid(a.details_json)
            THEN a.details_json ELSE '{}' END,'$.details.operationKey')=p.op)
), audit_batches AS (
    SELECT op,json_group_array(""" + _AUDIT_JSON + """) AS body
    FROM necessary_audits WHERE position<=3 GROUP BY op
), sources AS MATERIALIZED (
    SELECT p.op,p.candidate,p.rule,observation_source(
        json_object('id',c.id,'run_id',c.run_id,'soup_id',c.soup_id,'base_rule_version',c.base_rule_version,
            'candidate_digest',c.candidate_digest,'status',c.status,'reviewed_at',""" + _real_sql('c.reviewed_at') + """,
            'published_release_id',c.published_release_id),
        CASE WHEN length(CAST(cm.value_json AS BLOB))<=65536 THEN cm.value_json END,cm.row_version,
        CASE WHEN length(CAST(rm.value_json AS BLOB))<=65536 THEN rm.value_json END,rm.row_version,
        CASE WHEN length(CAST(rr.rules_json AS BLOB))<=2097152 THEN rr.rules_json END,
        CASE WHEN length(CAST(rr.manifest_json AS BLOB))<=2097152 THEN rr.manifest_json END,
        rr.created_at,rr.parent_id,a.body) AS proof
    FROM publications p LEFT JOIN rule_candidates c ON c.id=p.candidate
        LEFT JOIN runtime_meta cm ON cm.key='candidate_operation:'||p.op
        LEFT JOIN runtime_meta rm ON rm.key='rule_operation:'||p.op
        LEFT JOIN rule_releases rr ON rr.id=p.rule LEFT JOIN audit_batches a ON a.op=p.op
), checked AS MATERIALIZED (
    SELECT o.*,observation_record(""" + _ROW_JSON + """,s.proof) AS valid,
        (:soup IS NULL OR o.soup_id=:soup) AND (:puzzle IS NULL OR o.puzzle_version=:puzzle)
            AND (:rule IS NULL OR o.published_rule_version=:rule) AS matches
    FROM observation_window o LEFT JOIN sources s ON s.op=o.publication_operation_key
        AND s.candidate=o.candidate_id AND s.rule=o.published_rule_version
)
"""
_EXPRESSIONS = dict(observedRuns='1', passedRuns="state='passed'", failedRuns="state='failed'",
    incompleteRuns="state='incomplete'", pendingRuns="state='running'",
    pendingExpiredRuns="state='running' AND deadline_at<:now", plannedCases='planned_case_count',
    attemptedCases='attempted_case_count', passedCases='passed_case_count', counterexampleCases='counterexample_case_count',
    errorCases='error_case_count', unsupportedCases='unsupported_case_count',
    notAttemptedCases='planned_case_count-attempted_case_count')
_SUMS = ','.join(f'sum(CASE WHEN matches THEN ({expression}) ELSE 0 END) AS {name}'
    for name, expression in _EXPRESSIONS.items())
_SUMMARY_SQL = _BASE_SQL + f'SELECT traffic_class,sum(1-valid) AS invalid,{_SUMS} FROM checked GROUP BY traffic_class'


def observation_summary(conn, parameters, *, deadline):
    phase = conn.execute("SELECT value_json FROM runtime_meta WHERE key='migration_005_report'").fetchone()
    if phase is None:
        return MetricsPostPublicationRegression(reason='schema_5_required')
    coverage = baselines.strict_json(phase[0])['phase005']['coverageStart']

    def budget():
        if time.monotonic() >= deadline:
            raise MetricsError('metrics_busy', 503)

    def verify_source(*values):
        budget()
        try:
            result = _source(*values)
        except Exception:
            result = None  # Never a trusted zero or a partial filtered cohort.
        budget()
        return result

    def verify_record(raw, source):
        budget()
        try:
            record = PostPublicationStore.checked_record(baselines.strict_json(raw), coverage)
            plan = record.plan
            proof = baselines.strict_json(source)
            if (plan.publicationProofDigest != proof['proof'] or plan.candidateId != proof['candidate']
                or plan.publicationOperationKey != proof['operation'] or plan.soupId != proof['soup']
                or plan.puzzleVersion != proof['puzzle'] or plan.publishedRuleVersion != proof['rule']
                or plan.publishedAt != proof['publishedAt']
                or plan.trafficClass not in (proof['traffic'], 'test', 'unknown')):
                raise ValueError('Observation source binding mismatch')
            valid = 1
        except Exception:
            valid = 0
        budget()
        return valid

    conn.create_function('observation_source', 10, verify_source)
    conn.create_function('observation_record', 2, verify_record)
    values = {traffic: dict.fromkeys(MetricsObservationCounts.model_fields, 0)
        for traffic in ('real', 'test', 'synthetic', 'unknown')}
    try:
        for row in conn.execute(_SUMMARY_SQL, dict(parameters, now=time.time())):
            if row['invalid']:
                return MetricsPostPublicationRegression(reason='source_unavailable')
            values[row['traffic_class']] = {name: row[name] for name in MetricsObservationCounts.model_fields}
    finally:
        conn.create_function('observation_source', 10, None)
        conn.create_function('observation_record', 2, None)
    budget()
    before = parameters['start'] < coverage
    return MetricsObservedRegression(**values['real'], state='partial' if before else 'observed',
        sourceCoverageStart=coverage, windowStartsBeforeCoverage=before,
        excluded=MetricsObservationExcluded(**{traffic: MetricsObservationCounts(**values[traffic])
            for traffic in ('test', 'synthetic', 'unknown')}))
