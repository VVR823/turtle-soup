"""Private SQLite aggregates, not user identity or semantic-repair accuracy.

fixed window -> indexed source cohorts + necessary audit provenance
             -> one short read snapshot -> closed summary/public group page
             -> process audit status (not a historical window loss count)
"""
import sqlite3
import time

from . import baselines, migrations
from .post_publication_metrics import observation_summary
from .metrics_contracts import (
    MetricsCandidateStates, MetricsCounts, MetricsCoverage, MetricsError, MetricsExcluded,
    MetricsGroup, MetricsGroupKey, MetricsPage, MetricsProcessAudit, MetricsPublication,
    MetricsQuery, MetricsSummary, MetricsTaskStates, _checked, decode_metrics_cursor,
    encode_metrics_cursor, export_projection,
)

_COUNTS = tuple(MetricsCounts.model_fields)
_TRAFFIC = ("test", "synthetic", "legacy", "unknown")


class _DeadlineConnection(sqlite3.Connection):
    """Schema validation and every subsequent statement share one budget."""
    deadline = None

    def execute(self, sql, parameters=()):
        if self.deadline is not None:
            remaining = self.deadline - time.monotonic()
            if remaining <= 0:
                raise MetricsError("metrics_busy", 503)
            # Use native execute to avoid recursion. This includes the verifier's
            # own statements, not only the two aggregate statements below.
            super().execute(f"PRAGMA busy_timeout={min(500, int(remaining * 1000))}")
        return super().execute(sql, parameters)


def _json(expression):
    # SQLite accepts repeated object keys and json_extract picks only one.
    # Preserve counts as unknown instead of assigning ambiguous provenance.
    # CASE short-circuits invalid JSON before walking it; array indices are
    # integers and do not participate in object-key uniqueness.
    return f"""CASE WHEN NOT json_valid({expression}) THEN '{{}}'
        WHEN EXISTS(SELECT 1 FROM json_tree({expression})
            WHERE typeof(key)='text' GROUP BY parent,key HAVING count(*)>1) THEN '{{}}'
        ELSE {expression} END"""


def _dimensions(soup, puzzle, rule):
    # Source identifiers are public only when registered. Never reflect an
    # arbitrary free-text metadata value as a version or a public soup ID.
    soup_value = f"CASE WHEN {soup} IN (SELECT soup_id FROM puzzle_versions) THEN {soup} END"
    puzzle_ok = f"""typeof({puzzle})='text' AND length({puzzle})=67 AND substr({puzzle},1,3)='p1:'
        AND substr({puzzle},4) NOT GLOB '*[^0-9a-f]*'
        AND EXISTS(SELECT 1 FROM puzzle_versions pv WHERE pv.id={puzzle}
            AND ({soup} IS NULL OR pv.soup_id={soup}))"""
    rule_ok = f"""typeof({rule})='text' AND length({rule})=67 AND substr({rule},1,3)='r1:'
        AND substr({rule},4) NOT GLOB '*[^0-9a-f]*'
        AND EXISTS(SELECT 1 FROM rule_releases rr WHERE rr.id={rule}
            AND ({puzzle} IS NULL OR EXISTS(SELECT 1 FROM json_each({_json('rr.manifest_json')},'$.puzzleVersions') rv
                WHERE rv.value={puzzle} AND ({soup} IS NULL OR rv.key={soup}))))"""
    return f"{soup_value} AS soup, CASE WHEN {puzzle_ok} THEN {puzzle} END AS puzzle, CASE WHEN {rule_ok} THEN {rule} END AS rule"


def _verify_public_catalog(conn):
    """Validate catalog integrity, not player/feedback/run rows or their text.

    Schema verification checks the active baseline only. Table membership is a
    public allowlist only after inactive content-addressed snapshots and every
    release binding have also passed the existing baseline validators. All SQL
    shares this reader's deadline and read snapshot; corrupt catalogs fail closed.
    """
    catalog = {}
    for row in conn.execute('SELECT id FROM puzzle_versions'):
        soup = baselines.session_soup(conn, row['id'])
        payload = soup.model_dump(mode='json')
        catalog[row['id']] = (soup.id, {name: payload[name] for name in baselines.RULE_FIELDS})
    for row in conn.execute('SELECT id FROM rule_releases'):
        rules, manifest = baselines._rule_release(conn, row['id'])
        for soup_id, version in manifest['puzzleVersions'].items():
            verified = catalog.get(version)
            if verified is None or verified[0] != soup_id or rules['rulesBySoup'].get(soup_id) != verified[1]:
                raise baselines.SnapshotError('Invalid public catalog binding')


_SESSION_SCOPE = _dimensions("s.soup_id", "s.puzzle_version", "s.rule_version")
_TURN_SCOPE = _dimensions("s.soup_id", "t.puzzle_version", "t.rule_version")
_RUN_SCOPE = _dimensions("json_extract(r.j,'$.context.soupId')",
    "json_extract(r.j,'$.context.observedPuzzleVersion')", "json_extract(r.j,'$.context.observedRuleVersion')")
_HTTP_SCOPE = _dimensions("s.soup_id", "json_extract(a.j,'$.details.versions.puzzleVersion')",
    "json_extract(a.j,'$.details.versions.ruleVersion')")
_FEEDBACK_PUZZLE = "CASE WHEN json_extract(f.j,'$.state')='linked' AND json_extract(f.j,'$.turnId')=t.id AND json_extract(f.j,'$.sessionId')=s.id AND f.soup_id=s.soup_id AND json_extract(f.j,'$.puzzleVersion')=t.puzzle_version AND t.puzzle_version=s.puzzle_version THEN t.puzzle_version END"
_FEEDBACK_RULE = "CASE WHEN json_extract(f.j,'$.state')='linked' AND json_extract(f.j,'$.turnId')=t.id AND json_extract(f.j,'$.sessionId')=s.id AND f.soup_id=s.soup_id AND json_extract(f.j,'$.ruleVersion')=t.rule_version AND t.rule_version=s.rule_version THEN t.rule_version END"
_FEEDBACK_SCOPE = _dimensions("f.soup_id", _FEEDBACK_PUZZLE, _FEEDBACK_RULE)

# All data rows stay in SQLite. Python receives aggregate counts or at most
# limit+1 public groups, never problem text, manifests or candidate reports.
# Materialize sanitized windows once: inlining j at every json_extract would
# repeat its structural JSON walk many times per row and exhaust the deadline.
_EVENTS_SQL = f"""WITH
audit_window AS MATERIALIZED (
    SELECT id,event_type,request_id,session_id,turn_id,run_id,created_at,{_json('details_json')} AS j
    FROM audit_events WHERE created_at>=:start AND created_at<:end
        AND event_type IN ('http_attempt','feedback_submitted','candidate_reviewed','candidate_published')
),
audit_source AS (
    SELECT a.*,CASE WHEN json_type(a.j,'$.schemaVersion')='integer' AND json_extract(a.j,'$.schemaVersion')=1
        AND json_extract(a.j,'$.eventId')=a.id AND json_extract(a.j,'$.eventType')=a.event_type
        AND json_type(a.j,'$.createdAt') IN ('integer','real') AND json_extract(a.j,'$.createdAt')=a.created_at
        AND json_extract(a.j,'$.requestId') IS a.request_id AND json_extract(a.j,'$.sessionId') IS a.session_id
        AND json_extract(a.j,'$.turnId') IS a.turn_id AND json_extract(a.j,'$.runId') IS a.run_id
        AND json_type(a.j,'$.details')='object'
        AND json_extract(a.j,'$.details.trafficClass') IN ('real','test','synthetic','legacy')
        THEN json_extract(a.j,'$.details.trafficClass') ELSE 'unknown' END AS traffic
    FROM audit_window a
),
feedback_provenance AS (
    SELECT json_extract(j,'$.details.feedbackId') AS fid,created_at,
        CASE WHEN min(traffic)=max(traffic) THEN min(traffic) ELSE 'unknown' END AS traffic,
        CASE WHEN count(json_extract(j,'$.details.soupId'))=count(*)
            AND min(json_extract(j,'$.details.soupId'))=max(json_extract(j,'$.details.soupId'))
            THEN min(json_extract(j,'$.details.soupId')) END AS soup,
        CASE WHEN count(json_extract(j,'$.details.sourceState'))=count(*)
            AND min(json_extract(j,'$.details.sourceState'))=max(json_extract(j,'$.details.sourceState'))
            THEN min(json_extract(j,'$.details.sourceState')) END AS source_state,
        min(turn_id) AS turn_id,
        CASE WHEN count(turn_id)=0 OR (count(turn_id)=count(*) AND min(turn_id)=max(turn_id))
            THEN 1 ELSE 0 END AS turn_consistent
    FROM audit_source WHERE event_type='feedback_submitted'
        AND json_extract(j,'$.details.action') IN ('submitted','imported')
    GROUP BY json_extract(j,'$.details.feedbackId'),created_at
),
feedback_window AS MATERIALIZED (
    SELECT id,soup_id,turn_id,created_at,{_json('source_json')} AS j
    FROM feedback_items WHERE created_at>=:start AND created_at<:end
),
run_ids AS (
    SELECT id FROM agent_runs WHERE created_at>=:start AND created_at<:end
    UNION SELECT run_id FROM rule_candidates WHERE created_at>=:start AND created_at<:end
    UNION SELECT run_id FROM audit_source WHERE event_type IN ('candidate_reviewed','candidate_published') AND run_id IS NOT NULL
),
run_window AS MATERIALIZED (
    SELECT r.id,r.state,r.created_at,{_json('r.manifest_json')} AS j,c.status='published' AS published
    FROM agent_runs r JOIN run_ids i ON i.id=r.id LEFT JOIN rule_candidates c ON c.run_id=r.id
),
run_source AS (
    SELECT r.id,r.state,r.created_at,coalesce(r.published,0) AS published,{_RUN_SCOPE},
        CASE WHEN json_type(r.j,'$.schemaVersion')='integer' AND json_extract(r.j,'$.schemaVersion')=1
            AND json_extract(r.j,'$.policyVersion')='repair-tools-v1' AND json_type(r.j,'$.context')='object'
            AND json_type(r.j,'$.context.schemaVersion')='integer' AND json_extract(r.j,'$.context.schemaVersion')=1
            AND json_extract(r.j,'$.trafficClass') IN ('real','test','synthetic')
            THEN json_extract(r.j,'$.trafficClass') ELSE 'unknown' END AS traffic
    FROM run_window r
),
metric_events AS (
    SELECT 'sessionsCreated' AS metric,s.created_at AS stamp,s.traffic_class AS traffic,{_SESSION_SCOPE},NULL AS state,0 AS published
    FROM sessions s WHERE s.created_at>=:start AND s.created_at<:end
    UNION ALL
    SELECT 'successfulChargedTurns',t.completed_at,s.traffic_class,{_TURN_SCOPE},NULL,0
    FROM turns t JOIN sessions s ON s.id=t.session_id
    WHERE t.completed_at>=:start AND t.completed_at<:end AND t.state='completed' AND t.charged=1 AND t.kind IN ('answer','win')
    UNION ALL
    SELECT 'feedbackSubmitted',f.created_at,
        CASE WHEN p.traffic IS NOT NULL AND p.soup=f.soup_id AND p.source_state=json_extract(f.j,'$.state')
            AND p.turn_consistent=1 AND p.turn_id IS f.turn_id THEN p.traffic
            WHEN p.traffic IS NULL AND json_extract(f.j,'$.state')='legacy' THEN 'legacy' ELSE 'unknown' END,
        {_FEEDBACK_SCOPE},NULL,0
    FROM feedback_window f LEFT JOIN feedback_provenance p ON p.fid=f.id AND p.created_at=f.created_at
        LEFT JOIN turns t ON t.id=f.turn_id LEFT JOIN sessions s ON s.id=t.session_id
    UNION ALL
    SELECT 'tasksCreated',created_at,traffic,soup,puzzle,rule,state,published FROM run_source
    WHERE created_at>=:start AND created_at<:end
    UNION ALL
    SELECT 'candidatesCreated',c.created_at,coalesce(r.traffic,'unknown'),r.soup,r.puzzle,r.rule,c.status,0
    FROM rule_candidates c LEFT JOIN run_source r ON r.id=c.run_id WHERE c.created_at>=:start AND c.created_at<:end
    UNION ALL
    SELECT 'httpAttempts',a.created_at,a.traffic,{_HTTP_SCOPE},NULL,0
    FROM audit_source a LEFT JOIN sessions s ON s.id=a.session_id
    WHERE a.event_type='http_attempt'
    UNION ALL
    SELECT CASE WHEN a.event_type='candidate_published' THEN 'candidatePublicationEvents'
            WHEN json_extract(a.j,'$.details.action')='approved' THEN 'reviewApproved' ELSE 'reviewRejected' END,
        a.created_at,CASE WHEN a.traffic=r.traffic AND json_extract(a.j,'$.details.runId')=a.run_id
            AND json_extract(a.j,'$.details.candidateId')=c.id THEN a.traffic ELSE 'unknown' END,
        r.soup,r.puzzle,r.rule,NULL,0
    FROM audit_source a LEFT JOIN run_source r ON r.id=a.run_id LEFT JOIN rule_candidates c ON c.run_id=a.run_id
    WHERE a.event_type='candidate_published' OR a.event_type='candidate_reviewed'
        AND json_extract(a.j,'$.details.action') IN ('approved','rejected')
),
events AS (
    SELECT *,(:soup IS NULL OR soup=:soup) AND (:puzzle IS NULL OR puzzle=:puzzle)
        AND (:rule IS NULL OR rule=:rule) AS matches FROM metric_events
)
"""

_SUMMARY_SQL = _EVENTS_SQL + """SELECT metric,traffic,state,published,sum(CASE WHEN matches THEN 1 ELSE 0 END) AS n,
    sum(CASE WHEN soup IS NULL OR puzzle IS NULL OR rule IS NULL THEN 1 ELSE 0 END) AS unscoped
    FROM events GROUP BY metric,traffic,state,published"""
_GROUP_SELECT = ",".join(f"sum(CASE WHEN metric='{name}' THEN 1 ELSE 0 END) AS {name}" for name in _COUNTS)
_GROUP_SQL = _EVENTS_SQL + f""",groups AS (
    SELECT strftime('%Y-%m-%d',stamp,'unixepoch') AS day,soup,puzzle,rule,{_GROUP_SELECT}
    FROM events WHERE traffic='real' AND matches GROUP BY day,soup,puzzle,rule
)
SELECT * FROM groups WHERE :day IS NULL OR (day,coalesce(soup,''),coalesce(puzzle,''),coalesce(rule,'')) >
    (:day,:key_soup,:key_puzzle,:key_rule)
ORDER BY day,soup,puzzle,rule LIMIT :page_limit"""


def _summary(conn, parameters):
    counts = {name: 0 for name in _COUNTS}
    excluded = {traffic: {name: 0 for name in _COUNTS} for traffic in _TRAFFIC}
    unscoped = dict(counts)
    tasks = {name: 0 for name in MetricsTaskStates.model_fields}
    candidates = {name: 0 for name in MetricsCandidateStates.model_fields}
    numerator = 0
    for row in conn.execute(_SUMMARY_SQL, parameters):
        metric, traffic, n = row["metric"], row["traffic"], row["n"]
        if traffic == "real":
            counts[metric] += n
            unscoped[metric] += row["unscoped"]
            if metric == "tasksCreated":
                tasks[row["state"]] += n
                numerator += n if row["published"] else 0
            elif metric == "candidatesCreated":
                candidates[row["state"]] += n
        else:
            excluded[traffic if traffic in _TRAFFIC else "unknown"][metric] += n
    denominator = counts["tasksCreated"]
    return MetricsSummary(counts=MetricsCounts(**counts), excluded=MetricsExcluded(**{
        traffic: MetricsCounts(**values) for traffic, values in excluded.items()}),
        unscopedReal=MetricsCounts(**unscoped), taskStates=MetricsTaskStates(**tasks),
        candidateStates=MetricsCandidateStates(**candidates), taskPublication=MetricsPublication(
            numerator=numerator, denominator=denominator, ratio=numerator / denominator if denominator else None))


def _coverage_epochs(conn):
    audit = conn.execute("SELECT json_extract(value_json,'$.startedAt') FROM runtime_meta WHERE key='audit_coverage_start'").fetchone()
    agent = conn.execute("SELECT json_extract(value_json,'$.phase003.coverageStart') FROM runtime_meta WHERE key='migration_003_report'").fetchone()
    return audit[0] if audit else None, agent[0] if agent else None


def _coverage(runtime, query, epochs):
    audit, agent = epochs
    process = None
    try:
        status = runtime.audit_store.status() if runtime.audit_store is not None else None
        if status is not None and status.coverageStart is not None and status.coverageStart.get("startedAt") == audit:
            process = MetricsProcessAudit(**{name: getattr(status, name) for name in MetricsProcessAudit.model_fields})
    except Exception:
        pass  # Process status unknown stays unknown; persisted counts stay intact.
    before_audit = None if audit is None else query.start < audit
    before_agent = None if agent is None else query.start < agent
    state = "unknown" if audit is None or agent is None or process is None else "complete"
    if before_audit or before_agent or process is not None and not process.complete:
        state = "partial"
    return MetricsCoverage(auditStartedAt=audit, agentStartedAt=agent, windowStartsBeforeAudit=before_audit,
        windowStartsBeforeAgent=before_agent, processAudit=process, state=state)


def query_metrics(runtime, query: MetricsQuery) -> MetricsPage:
    try:
        query = _checked(MetricsQuery, query)
        key = None
        if query.cursor is not None:
            bound, key = decode_metrics_cursor(query.cursor)
            if query.model_dump(exclude={"cursor"}) != bound.model_dump(exclude={"cursor"}):
                raise ValueError("Cursor query mismatch")
    except Exception:
        raise MetricsError() from None
    if runtime.closed:
        raise MetricsError("metrics_unavailable", 503)
    deadline = time.monotonic() + 3.0
    conn = None
    parameters = dict(start=query.start, end=query.end, soup=query.soupId, puzzle=query.puzzleVersion,
        rule=query.ruleVersion, day=None if key is None else key.day, key_soup="" if key is None else key.soupId or "",
        key_puzzle="" if key is None else key.puzzleVersion or "", key_rule="" if key is None else key.ruleVersion or "",
        page_limit=query.limit + 1)
    try:
        path = runtime.settings.DATA_DIR / "sessions.db"
        remaining = deadline - time.monotonic()
        if remaining <= 0:
            raise MetricsError("metrics_busy", 503)
        conn = sqlite3.connect(path.as_uri() + "?mode=rw", uri=True, timeout=min(0.5, remaining), factory=_DeadlineConnection)
        conn.deadline = deadline
        conn.row_factory = sqlite3.Row
        conn.set_progress_handler(lambda: int(time.monotonic() >= deadline), 1000)
        conn.execute("PRAGMA query_only=ON")
        conn.execute("BEGIN")
        migrations.verify_schema(conn, required_version=4)
        _verify_public_catalog(conn)
        if query.soupId is not None and conn.execute("SELECT 1 FROM puzzle_versions WHERE soup_id=? LIMIT 1", (query.soupId,)).fetchone() is None:
            raise MetricsError()  # A private row ID is not a public filter.
        summary = _summary(conn, parameters)
        observation = observation_summary(conn, parameters, deadline=deadline)
        summary = _checked(MetricsSummary, summary.model_copy(update={'postPublicationRegression': observation}))
        groups = tuple(MetricsGroup(day=row["day"], soupId=row["soup"], puzzleVersion=row["puzzle"],
            ruleVersion=row["rule"], counts=MetricsCounts(**{name: row[name] for name in _COUNTS}))
            for row in conn.execute(_GROUP_SQL, parameters))
        epochs = _coverage_epochs(conn)
        if time.monotonic() >= deadline:
            raise MetricsError("metrics_busy", 503)
    except MetricsError:
        raise
    except (sqlite3.Error, baselines.SnapshotError) as error:
        cause = error
        # Baseline validators deliberately wrap storage errors. Inspect only
        # that explicit, bounded cause chain, never diagnostic message text.
        for _ in range(8):
            if not isinstance(cause, baselines.SnapshotError):
                break
            cause = cause.__cause__
        code = (getattr(cause, "sqlite_errorcode", 0) & 0xff) if isinstance(cause, sqlite3.Error) else 0
        name = "metrics_busy" if (time.monotonic() >= deadline or code in {
            sqlite3.SQLITE_BUSY, sqlite3.SQLITE_LOCKED, sqlite3.SQLITE_INTERRUPT}) else "metrics_unavailable"
        raise MetricsError(name, 503) from None
    except Exception:
        raise MetricsError("metrics_unavailable", 503) from None
    finally:
        if conn is not None:
            cleanup_failed = False
            # Cleanup is outside the query's except block. Attempt every step,
            # including close if resetting the handler or rollback fails, and
            # never let SQLite's raw diagnostic text become a response error.
            for cleanup in (lambda: conn.set_progress_handler(None, 0), conn.rollback, conn.close):
                try:
                    cleanup()
                except sqlite3.Error:
                    cleanup_failed = True
            if cleanup_failed:
                raise MetricsError("metrics_unavailable", 503) from None
    more = len(groups) > query.limit
    visible = groups[:query.limit]
    cursor = encode_metrics_cursor(query, MetricsGroupKey(**{
        name: getattr(visible[-1], name) for name in MetricsGroupKey.model_fields})) if more else None
    return MetricsPage(query=query, summary=summary, coverage=_coverage(runtime, query, epochs),
        groups=visible, nextCursor=cursor)


def export_metrics(runtime, query: MetricsQuery):
    try:
        query = _checked(MetricsQuery, query)
        if query.cursor is not None:
            raise ValueError("Export cannot splice live pages")
        complete_query = MetricsQuery(**{**query.model_dump(), "limit": 100})
    except Exception:
        raise MetricsError() from None
    return export_projection(query_metrics(runtime, complete_query), generated_at=time.time())
