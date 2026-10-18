"""Observed production reader plans/pages over declared synthetic volume only."""
from contextlib import closing
import sqlite3
from uuid import uuid4

import pytest

from app import audit_store, baselines, db, migrations
from app.audit_events import AuditEvent, AttemptDetails
from .test_metrics_queries import reader_api
from .test_migrations import puzzle


@pytest.fixture
def volume_runtime(runtime):
    runtime.soups = [puzzle().model_copy(update={"id": f"synthetic-{index}"}) for index in range(4)]
    db.initialize()
    with closing(db._connect()) as conn, conn:
        migrations.migrate(conn, runtime.soups, target_version=4)
    runtime.audit_store = audit_store.AuditStore(runtime.settings.DATA_DIR, connect=db._connect)
    return runtime


def seed_sessions(active, count):
    with closing(db._connect()) as conn, conn:
        versions = baselines.active_manifest(conn)
        # Synthetic statistical volume, not actual players or requests. All
        # identities and source versions refer only to this newly owned fixture.
        conn.executemany("INSERT INTO sessions(id,soup_id,created_at,puzzle_version,rule_version,compat_state,traffic_class) VALUES(?,?,?,?,?,'compatible','real')",
            [(str(uuid4()), f"synthetic-{index % 4}", (index // 4 % 27) * 86400 + 100,
                versions["puzzleVersions"][f"synthetic-{index % 4}"], versions["ruleVersion"]) for index in range(count)])


def volume_query(**changes):
    _, contracts = reader_api()
    return contracts.MetricsQuery(start=0.0, end=31 * 86400.0, **changes)


def test_real_group_pagination_default_fifty_and_cursor_bound_window(volume_runtime):
    metrics, contracts = reader_api()
    seed_sessions(volume_runtime, 105)
    first = metrics.query_metrics(volume_runtime, volume_query())
    assert first.summary.counts.sessionsCreated == 105
    assert len(first.groups) == 50 and first.nextCursor is not None
    groups = list(first.groups)
    cursor = first.nextCursor
    while cursor is not None:
        query = contracts.parse_metrics_query([("cursor", cursor)], now=9_000_000.0)
        page = metrics.query_metrics(volume_runtime, query)
        assert (page.query.start, page.query.end, page.query.limit) == (0.0, 2678400.0, 50)
        groups.extend(page.groups)
        cursor = page.nextCursor
    assert len(groups) == 105
    keys = [(group.day, group.soupId, group.puzzleVersion, group.ruleVersion) for group in groups]
    assert keys == sorted(set(keys))
    assert sum(group.counts.sessionsCreated for group in groups) == 105


def test_hundred_groups_export_is_complete_but_one_hundred_one_refuses(volume_runtime):
    metrics, contracts = reader_api()
    seed_sessions(volume_runtime, 100)
    complete = metrics.export_metrics(volume_runtime, volume_query())
    assert complete.complete is True and len(complete.groups) == 100
    assert complete.summary.counts.sessionsCreated == 100
    assert sum(group.counts.sessionsCreated for group in complete.groups) == 100
    with closing(db._connect()) as conn, conn:
        versions = baselines.active_manifest(conn)
        conn.execute("INSERT INTO sessions(id,soup_id,created_at,puzzle_version,rule_version,compat_state,traffic_class) VALUES(?,'synthetic-0',?,?,?,?, 'real')",
            (str(uuid4()), 26 * 86400 + 100, versions["puzzleVersions"]["synthetic-0"], versions["ruleVersion"], "compatible"))
    page = metrics.query_metrics(volume_runtime, volume_query(limit=100))
    assert len(page.groups) == 100 and page.nextCursor is not None
    with pytest.raises(contracts.MetricsError) as caught:
        metrics.export_metrics(volume_runtime, volume_query())
    assert (caught.value.code, caught.value.status) == ("metrics_export_too_large", 409)


def test_actual_reader_explain_uses_time_indexes_and_bounded_group_sql(volume_runtime, monkeypatch):
    metrics, contracts = reader_api()
    seed_sessions(volume_runtime, 200)
    with closing(db._connect()) as conn, conn:
        values = []
        for index in range(5000):
            item = AuditEvent(eventId=str(uuid4()), eventType="http_attempt", createdAt=1000.0 + index,
                details=AttemptDetails(method="GET", routeTemplate="/health", statusCode=200, durationMs=1.0,
                    outcome="success", responseStarted=True, disconnected=False, trafficClass="synthetic"))
            values.append((item.eventId, item.model_dump_json(), item.createdAt))
        conn.executemany("INSERT INTO audit_events(id,event_type,details_json,created_at) VALUES(?,'http_attempt',?,?)", values)
    real_connect = sqlite3.connect
    observed, plans = [], []

    class ObservedConnection(metrics._DeadlineConnection):
        def execute(self, sql, parameters=()):
            if sql in {metrics._SUMMARY_SQL, metrics._GROUP_SQL}:
                observed.append((sql, dict(parameters)))
                plans.extend(tuple(row) for row in sqlite3.Connection.execute(self, "EXPLAIN QUERY PLAN " + sql, parameters))
            return super().execute(sql, parameters)

    def connect(*args, **kwargs):
        kwargs["factory"] = ObservedConnection
        return real_connect(*args, **kwargs)

    monkeypatch.setattr(sqlite3, "connect", connect)
    try:
        page = metrics.query_metrics(volume_runtime, volume_query(limit=3))
    except contracts.MetricsError as error:
        details = '\n'.join(str(row) for row in plans)
        pytest.fail(f'Actual volume reader failed: {error.code}; observed aggregates={len(observed)}; '
            f'JSON-tree plan scans={details.count("json_tree")}; '
            f'materialized audit windows={details.count("MATERIALIZE audit_window")}; '
            f'materialized run windows={details.count("MATERIALIZE run_window")}')
    assert page.summary.counts.sessionsCreated == 200 and len(page.groups) == 3
    assert page.summary.excluded.synthetic.httpAttempts == 5000
    assert len(observed) == 2 and observed[1][1]["page_limit"] == 4
    assert observed[1][0].rstrip().endswith("LIMIT :page_limit")
    plan_text = "\n".join(str(row) for row in plans)
    for name in ("idx_sessions_created", "idx_turns_completed", "idx_feedback_created",
        "idx_agent_runs_created", "idx_rule_candidates_created", "idx_audit_events_time"):
        assert name in plan_text, name
    assert all("rawQuestion" not in group.model_dump_json() for group in page.groups)


def test_catalog_integrity_does_not_reparse_whole_release_for_each_public_soup(volume_runtime, monkeypatch):
    metrics, _ = reader_api()
    seed_sessions(volume_runtime, 200)
    real_connect = sqlite3.connect
    rule_reads = []

    def observe(sql):
        if sql.startswith('SELECT rules_json,manifest_json,parent_id FROM rule_releases WHERE id='):
            rule_reads.append(True)  # Count actual SQLite reads, never echo private query values.

    def connect(*args, **kwargs):
        conn = real_connect(*args, **kwargs)
        conn.set_trace_callback(observe)
        return conn

    monkeypatch.setattr(metrics.sqlite3, 'connect', connect)
    page = metrics.query_metrics(volume_runtime, volume_query(limit=3))
    assert page.summary.counts.sessionsCreated == 200 and len(page.groups) == 3
    # One existing active-schema validation plus one complete catalog release
    # validation; not a full-release parse for each of its four public soups.
    assert len(rule_reads) <= 2
