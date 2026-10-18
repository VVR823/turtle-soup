"""Production statistics on declared synthetic, real-tagged SQLite fixtures.

Counts must come from unique charged turns, not messages or HTTP retries.
Creating fixture data through the actual game store keeps replay semantics real;
changing synthetic session classification exercises the production filter only.
"""
from contextlib import closing
from importlib import import_module
from uuid import uuid4
import json
import sqlite3
from types import SimpleNamespace

import pytest

from app import audit_store, baselines, db, migrations
from app.audit_events import AuditEvent, AttemptDetails
from app.schemas import HostVersions
from .test_migrations import puzzle
from .test_turn_failure_recovery import result
from .test_rule_snapshots import rule_storage


@pytest.fixture
def metrics_runtime(runtime):
    runtime.soups = [puzzle()]
    db.initialize()
    with closing(db._connect()) as conn, conn:
        migrations.migrate(conn, runtime.soups, target_version=4)
    runtime.audit_store = audit_store.AuditStore(runtime.settings.DATA_DIR, connect=db._connect)
    return runtime


def reader_api():
    try:
        return import_module("app.metrics"), import_module("app.metrics_contracts")
    except ModuleNotFoundError as error:
        if error.name in {"app.metrics", "app.metrics_contracts"}:
            pytest.fail("TS16 production aggregation reader/contract is not implemented")
        raise


def test_successful_turns_not_messages_or_http_replays(metrics_runtime):
    first, second = [db.create_game_once("synthetic", "tianyi", str(uuid4())) for _ in range(2)]
    session_id = first["sessionId"]
    owners = []
    saved_answer = None
    for index, kind in enumerate(("answer", "reminder", "system_error", "win")):
        owner = db.reserve_turn(session_id, str(uuid4()), f"Synthetic metrics {kind}?", now=1001 + index * 2)
        owners.append(owner)
        saved = db.finish_turn(owner, result(owner, kind), now=1002 + index * 2)
        if kind == "answer":
            saved_answer = saved
            assert db.finish_turn(owner, result(owner), now=1003) == saved
            assert db.get_turn_response(session_id, owner.requestId, now=1004) == saved
    assert db.get_turn_response(session_id, owners[0].requestId, now=1010) == saved_answer
    with closing(db._connect()) as conn, conn:
        conn.execute("UPDATE sessions SET traffic_class='real',created_at=1000 WHERE id IN (?,?)",
            (session_id, second["sessionId"]))
        assert conn.execute("SELECT count(*) FROM messages WHERE session_id=?", (session_id,)).fetchone()[0] == 8
        assert conn.execute("SELECT questions_asked FROM sessions WHERE id=?", (session_id,)).fetchone()[0] == 2
    versions = HostVersions(puzzleVersion=owners[0].puzzleVersion, ruleVersion=owners[0].ruleVersion)
    for index in range(4):
        recorded = metrics_runtime.audit_store.record_attempt(AuditEvent(eventId=str(uuid4()), eventType="http_attempt",
            requestId=owners[0].requestId, sessionId=session_id, turnId=owners[0].turnId,
            createdAt=float(1011 + index), details=AttemptDetails(method="POST", routeTemplate="/api/chat",
                statusCode=200, durationMs=1.0, outcome="success", responseStarted=True, disconnected=False,
                replayed=index > 0, trafficClass="real", versions=versions)))
        assert recorded.persisted and recorded.storage == "db"
    metrics, contracts = reader_api()
    query = contracts.parse_metrics_query([("start", "1000"), ("end", "1100")], now=1100.0)
    page = metrics.query_metrics(metrics_runtime, query)
    assert page.summary.counts.sessionsCreated == 2
    assert page.summary.counts.successfulChargedTurns == 2
    assert page.summary.counts.httpAttempts == 4
    assert page.summary.counts.feedbackSubmitted == 0
    assert page.summary.counts.tasksCreated == 0
    assert page.summary.taskPublication.denominator == 0
    assert page.summary.taskPublication.ratio is None
    assert page.query.limit == 50 and len(page.groups) == 1
    assert page.groups[0].counts.successfulChargedTurns == 2
    assert page.consistency == "fixed_window_live_snapshot"


def query(active, **changes):
    metrics, contracts = reader_api()
    values = {"start": "1000", "end": "1100", **{key: str(value) for key, value in changes.items()}}
    return metrics.query_metrics(active, contracts.parse_metrics_query(list(values.items()), now=1100.0))


def test_sessions_classification_is_explicit_and_half_open(metrics_runtime):
    for traffic, stamp in (("real", 1000), ("test", 1001), ("synthetic", 1002), ("legacy", 1003),
        ("real", 999), ("real", 1100)):
        saved = db.create_game_once("synthetic", "tianyi", str(uuid4()))
        with closing(db._connect()) as conn, conn:
            conn.execute("UPDATE sessions SET traffic_class=?,created_at=? WHERE id=?", (traffic, stamp, saved["sessionId"]))
    page = query(metrics_runtime)
    assert page.summary.counts.sessionsCreated == 1
    assert page.summary.excluded.test.sessionsCreated == 1
    assert page.summary.excluded.synthetic.sessionsCreated == 1
    assert page.summary.excluded.legacy.sessionsCreated == 1
    assert page.summary.excluded.unknown.sessionsCreated == 0


def test_unknown_http_metadata_and_unscoped_real_are_not_current_versions(metrics_runtime):
    event = AuditEvent(eventId=str(uuid4()), eventType="http_attempt", createdAt=1001.0,
        details=AttemptDetails(method="GET", routeTemplate="/health", statusCode=200, durationMs=1.0,
            outcome="success", responseStarted=True, disconnected=False, trafficClass="real"))
    assert metrics_runtime.audit_store.record_attempt(event).storage == "db"
    with closing(db._connect()) as conn, conn:
        conn.execute("INSERT INTO audit_events(id,event_type,details_json,created_at) VALUES(?,'http_attempt','{invalid',1002)", (str(uuid4()),))
        versions = baselines.active_manifest(conn)
    page = query(metrics_runtime)
    assert page.summary.counts.httpAttempts == 1
    assert page.summary.excluded.unknown.httpAttempts == 1
    assert page.summary.unscopedReal.httpAttempts == 1
    assert page.groups[0].soupId is None and page.groups[0].ruleVersion is None
    filtered = query(metrics_runtime, ruleVersion=versions["ruleVersion"])
    assert filtered.summary.counts.httpAttempts == 0 and filtered.groups == ()
    assert filtered.summary.unscopedReal.httpAttempts == 1


def test_feedback_provenance_is_batch_bound_and_unknown_explicit(metrics_runtime):
    from app.feedback_store import submit_feedback
    from .test_feedback_storage import body
    items = [submit_feedback(body()) for _ in range(3)]
    with closing(db._connect()) as conn, conn:
        for index, item in enumerate(items):
            original = conn.execute("SELECT id,details_json FROM audit_events WHERE event_type='feedback_submitted' AND json_extract(details_json,'$.details.feedbackId')=?", (item.id,)).fetchone()
            event = json.loads(original["details_json"])
            event["createdAt"] = float(1001 + index)
            event["details"]["trafficClass"] = "real"
            conn.execute("UPDATE feedback_items SET created_at=? WHERE id=?", (1001 + index, item.id))
            conn.execute("UPDATE audit_events SET created_at=?,details_json=? WHERE id=?",
                (1001 + index, baselines.canonical_json(event), original["id"]))
            if index == 2:
                conn.execute("DELETE FROM audit_events WHERE id=?", (original["id"],))
                continue
            duplicate = {**event, "eventId": str(uuid4()), "details": dict(event["details"])}
            if index == 1: duplicate["details"]["trafficClass"] = "test"
            checked = AuditEvent.model_validate_json(baselines.canonical_json(duplicate))
            conn.execute("INSERT INTO audit_events(id,event_type,details_json,created_at) VALUES(?,'feedback_submitted',?,?)",
                (checked.eventId, checked.model_dump_json(), checked.createdAt))
    page = query(metrics_runtime)
    assert page.summary.counts.feedbackSubmitted == 1  # Unlinked manual feedback is retained.
    assert page.summary.excluded.unknown.feedbackSubmitted == 2  # conflicting/missing provenance
    assert page.summary.unscopedReal.feedbackSubmitted == 1
    assert page.groups[0].soupId == "synthetic" and page.groups[0].puzzleVersion is None
    assert "PRIVATE synthetic claim" not in page.model_dump_json()


@pytest.mark.parametrize('field,missing', [('soupId', True), ('soupId', False), ('sourceState', True), ('sourceState', False)])
def test_submission_duplicate_missing_provenance_cannot_be_hidden_by_valid_event(metrics_runtime, field, missing):
    from app.feedback_store import submit_feedback
    from .test_feedback_storage import body
    item = submit_feedback(body())
    with closing(db._connect()) as conn, conn:
        original = conn.execute("SELECT id,details_json FROM audit_events WHERE event_type='feedback_submitted' AND json_extract(details_json,'$.details.feedbackId')=?", (item.id,)).fetchone()
        valid = json.loads(original['details_json'])
        valid['createdAt'] = 1001.0
        valid['details']['trafficClass'] = 'real'
        conn.execute('UPDATE feedback_items SET created_at=1001 WHERE id=?', (item.id,))
        conn.execute('UPDATE audit_events SET created_at=1001,details_json=? WHERE id=?',
            (baselines.canonical_json(valid), original['id']))
        invalid = {**valid, 'eventId': str(uuid4()), 'details': dict(valid['details'])}
        if missing:
            invalid['details'].pop(field)
        else:
            invalid['details'][field] = None
        # Deliberately corrupt stored metadata; normal typed writers reject it.
        conn.execute("INSERT INTO audit_events(id,event_type,details_json,created_at) VALUES(?,'feedback_submitted',?,1001)",
            (invalid['eventId'], baselines.canonical_json(invalid)))
    page = query(metrics_runtime)
    assert page.summary.counts.feedbackSubmitted == 0
    assert page.summary.excluded.unknown.feedbackSubmitted == 1
    assert page.summary.unscopedReal.feedbackSubmitted == 0


@pytest.mark.parametrize('duplicate_source', ['same', 'missing', 'other'])
def test_linked_feedback_provenance_must_match_each_submission_turn(metrics_runtime, duplicate_source):
    from app.feedback_store import submit_feedback
    from .test_feedback_storage import body
    turns = []
    for _ in range(2):
        game = db.create_game_once('synthetic', 'tianyi', str(uuid4()))
        turn = db.reserve_turn(game['sessionId'], str(uuid4()), 'Synthetic linked question?', now=1000)
        host = result(turn)
        db.finish_turn(turn, host, now=1001)
        turns.append((turn, host))
    turn, host = turns[0]
    item = submit_feedback(body(question='Synthetic linked question?', hostAnswer=host.reply, turnId=turn.turnId))
    with closing(db._connect()) as conn, conn:
        row = conn.execute("SELECT id,details_json FROM audit_events WHERE event_type='feedback_submitted' AND json_extract(details_json,'$.details.feedbackId')=?", (item.id,)).fetchone()
        event = json.loads(row['details_json'])
        event['createdAt'] = 1001.0
        event['details']['trafficClass'] = 'real'
        conn.execute('UPDATE feedback_items SET created_at=1001 WHERE id=?', (item.id,))
        conn.execute('UPDATE audit_events SET created_at=1001,details_json=? WHERE id=?', (baselines.canonical_json(event), row['id']))
        duplicate = {**event, 'eventId': str(uuid4())}
        duplicate['turnId'] = turn.turnId if duplicate_source == 'same' else (None if duplicate_source == 'missing' else turns[1][0].turnId)
        checked = AuditEvent.model_validate_json(baselines.canonical_json(duplicate))
        conn.execute("INSERT INTO audit_events(id,event_type,turn_id,details_json,created_at) VALUES(?,'feedback_submitted',?,?,1001)",
            (checked.eventId, checked.turnId, checked.model_dump_json()))
    page = query(metrics_runtime)
    assert page.summary.counts.feedbackSubmitted == (1 if duplicate_source == 'same' else 0)
    assert page.summary.excluded.unknown.feedbackSubmitted == (0 if duplicate_source == 'same' else 1)


@pytest.mark.parametrize('first', ['real', 'test'])
def test_duplicate_object_keys_in_raw_http_audit_are_unknown(metrics_runtime, first):
    second = 'test' if first == 'real' else 'real'
    event = AuditEvent(eventId=str(uuid4()), eventType='http_attempt', createdAt=1001.0,
        details=AttemptDetails(method='GET', routeTemplate='/health', statusCode=200, durationMs=1.0,
            outcome='success', responseStarted=True, disconnected=False, trafficClass=first))
    raw = event.model_dump_json().replace(f'"trafficClass":"{first}"',
        f'"trafficClass":"{first}","trafficClass":"{second}"')
    # Native SQLite accepts this raw JSON, but its interpretation is ambiguous.
    with closing(db._connect()) as conn, conn:
        assert conn.execute('SELECT json_valid(?)', (raw,)).fetchone()[0] == 1
        conn.execute("INSERT INTO audit_events(id,event_type,details_json,created_at) VALUES(?,'http_attempt',?,1001)",
            (event.eventId, raw))
    page = query(metrics_runtime)
    assert page.summary.counts.httpAttempts == 0
    assert page.summary.excluded.unknown.httpAttempts == 1
    assert page.summary.excluded.test.httpAttempts == 0
    assert page.groups == ()


@pytest.mark.parametrize('field,first', [('trafficClass', 'real'), ('trafficClass', 'test'),
    ('soupId', 'synthetic'), ('soupId', 'PRIVATE_AMBIGUOUS_CATALOG')])
def test_duplicate_object_keys_in_raw_run_manifest_are_unknown(metrics_runtime, field, first):
    from .test_agent_store import create
    _, item, original = create(metrics_runtime)
    data = original.manifest.model_dump(mode='json')
    data['trafficClass'] = 'real'
    target = data if field == 'trafficClass' else data['context']
    target[field] = first
    second = ('test' if first == 'real' else 'real') if field == 'trafficClass' else (
        'PRIVATE_AMBIGUOUS_CATALOG' if first == 'synthetic' else 'synthetic')
    raw = baselines.canonical_json(data).replace(f'"{field}":"{first}"',
        f'"{field}":"{first}","{field}":"{second}"')
    with closing(db._connect()) as conn, conn:
        assert conn.execute('SELECT json_valid(?)', (raw,)).fetchone()[0] == 1
        conn.execute("INSERT INTO agent_runs(id,request_id,feedback_id,state,checkpoint_json,manifest_json,created_at,updated_at) VALUES(?,?,?,'queued',?,?,1001,1001)",
            (str(uuid4()), str(uuid4()), item.id, original.checkpoint.model_dump_json(), raw))
    page = query(metrics_runtime)
    assert page.summary.counts.tasksCreated == 0
    assert page.summary.excluded.unknown.tasksCreated == 1
    assert page.summary.excluded.test.tasksCreated == 0
    assert page.groups == ()
    assert 'PRIVATE_AMBIGUOUS_CATALOG' not in page.model_dump_json()


def test_all_task_states_are_in_denominator_source_version_not_repair_base(metrics_runtime):
    from .test_agent_store import create
    _, item, original = create(metrics_runtime)
    context = original.manifest.context.model_copy(update={"baseRuleVersion": "r1:" + "c" * 64})
    manifest = original.manifest.model_copy(update={"trafficClass": "real", "context": context,
        "contextDigest": baselines.digest(context.model_dump(mode="json"))})
    # Declared synthetic volume/status records, not actual successful Agent or
    # human-review evidence. The original manifest/checkpoint came from real create.
    with closing(db._connect()) as conn, conn:
        for state in ("queued", "running", "awaiting_review", "needs_human", "failed", "cancelled"):
            conn.execute("INSERT INTO agent_runs(id,request_id,feedback_id,state,checkpoint_json,manifest_json,created_at,updated_at) VALUES(?,?,?,?,?,?,1001,1001)",
                (str(uuid4()), str(uuid4()), item.id, state, original.checkpoint.model_dump_json(), manifest.model_dump_json()))
    page = query(metrics_runtime, ruleVersion=context.observedRuleVersion)
    assert page.summary.counts.tasksCreated == 6
    assert page.summary.taskStates.model_dump() == dict(queued=1, running=1, awaiting_review=1, needs_human=1, failed=1, cancelled=1)
    assert (page.summary.taskPublication.numerator, page.summary.taskPublication.denominator, page.summary.taskPublication.ratio) == (0, 6, 0.0)
    assert query(metrics_runtime, ruleVersion=context.baseRuleVersion).summary.counts.tasksCreated == 0
    assert metrics_runtime.model.calls == []


def test_query_never_initializes_schema(runtime):
    metrics, contracts = reader_api()
    before = sorted(path.name for path in runtime.settings.DATA_DIR.iterdir())
    with pytest.raises(contracts.MetricsError) as caught:
        metrics.query_metrics(runtime, contracts.MetricsQuery(start=1000.0, end=1100.0))
    assert (caught.value.code, caught.value.status) == ("metrics_unavailable", 503)
    assert sorted(path.name for path in runtime.settings.DATA_DIR.iterdir()) == before


@pytest.mark.parametrize("phase", [1, 2, 3])
def test_query_old_schema_is_not_migrated(runtime, phase):
    runtime.soups = [puzzle()]
    with closing(sqlite3.connect(runtime.settings.DATA_DIR / "sessions.db")) as conn, conn:
        migrations.migrate(conn, runtime.soups, target_version=phase)
        before = "\n".join(conn.iterdump())
    metrics, contracts = reader_api()
    with pytest.raises(contracts.MetricsError) as caught:
        metrics.query_metrics(runtime, contracts.MetricsQuery(start=1000.0, end=1100.0))
    assert caught.value.status == 503
    with closing(sqlite3.connect(runtime.settings.DATA_DIR / "sessions.db")) as conn, conn:
        assert "\n".join(conn.iterdump()) == before


def test_elapsed_deadline_never_starts_the_next_sql_query(metrics_runtime, monkeypatch):
    metrics, contracts = reader_api()
    observed = []
    now = [0.0]
    real_connect, real_summary = sqlite3.connect, metrics._summary

    def connect(*args, **kwargs):
        conn = real_connect(*args, **kwargs)
        conn.set_trace_callback(observed.append)
        return conn

    def summary(*args, **kwargs):
        value = real_summary(*args, **kwargs)  # Actual native aggregation runs.
        now[0] = 4.0  # Declared controlled clock, beyond the3-second deadline.
        return value

    monkeypatch.setattr(sqlite3, "connect", connect)
    monkeypatch.setattr(metrics, "time", SimpleNamespace(monotonic=lambda: now[0], time=lambda: 1100.0))
    monkeypatch.setattr(metrics, "_summary", summary)
    with pytest.raises(contracts.MetricsError) as caught:
        query(metrics_runtime)
    assert (caught.value.code, caught.value.status) == ("metrics_busy", 503)
    assert not any("SELECT * FROM groups" in statement for statement in observed)


def test_busy_timeout_shrinks_to_the_remaining_deadline(metrics_runtime, monkeypatch):
    metrics, _ = reader_api()
    observed, now = [], [0.0]
    real_connect, real_summary = sqlite3.connect, metrics._summary

    def connect(*args, **kwargs):
        conn = real_connect(*args, **kwargs)
        conn.set_trace_callback(observed.append)
        return conn

    def summary(*args, **kwargs):
        value = real_summary(*args, **kwargs)
        now[0] = 2.8
        return value

    monkeypatch.setattr(sqlite3, "connect", connect)
    monkeypatch.setattr(metrics, "time", SimpleNamespace(monotonic=lambda: now[0], time=lambda: 1100.0))
    monkeypatch.setattr(metrics, "_summary", summary)
    query(metrics_runtime)
    limits = [int(statement.rsplit("=", 1)[1]) for statement in observed if statement.startswith("PRAGMA busy_timeout=")]
    assert limits and limits[-1] <= 200  # Native busy wait cannot borrow a fresh500ms.


def test_summary_and_groups_share_a_snapshot_while_wal_writer_can_commit(metrics_runtime, monkeypatch):
    metrics, _ = reader_api()
    session = db.create_game_once("synthetic", "tianyi", str(uuid4()))
    with closing(db._connect()) as conn, conn:
        conn.execute("UPDATE sessions SET traffic_class='real',created_at=1001 WHERE id=?", (session["sessionId"],))
    real_summary = metrics._summary
    committed = []

    def summary(*args, **kwargs):
        value = real_summary(*args, **kwargs)
        with closing(sqlite3.connect(metrics_runtime.settings.DATA_DIR / "sessions.db", timeout=0.5)) as writer, writer:
            writer.execute("UPDATE sessions SET traffic_class='test' WHERE id=?", (session["sessionId"],))
        committed.append(True)
        return value

    monkeypatch.setattr(metrics, "_summary", summary)
    page = query(metrics_runtime)
    assert committed == [True]
    assert page.summary.counts.sessionsCreated == 1 and page.groups[0].counts.sessionsCreated == 1
    monkeypatch.setattr(metrics, "_summary", real_summary)
    next_page = query(metrics_runtime)
    assert next_page.summary.counts.sessionsCreated == 0 and next_page.summary.excluded.test.sessionsCreated == 1


def test_unknown_process_coverage_and_pre_audit_history_are_not_complete(metrics_runtime):
    session = db.create_game_once("synthetic", "tianyi", str(uuid4()))
    with closing(db._connect()) as conn, conn:
        conn.execute("UPDATE sessions SET traffic_class='real',created_at=1001 WHERE id=?", (session["sessionId"],))
    page = query(metrics_runtime)
    assert page.coverage.windowStartsBeforeAudit is True and page.coverage.windowStartsBeforeAgent is True
    assert page.coverage.state == "partial" and page.summary.counts.sessionsCreated == 1
    metrics_runtime.audit_store = None
    page = query(metrics_runtime)
    assert page.coverage.processAudit is None and page.coverage.state != "complete"
    assert page.summary.counts.sessionsCreated == 1


def test_private_session_id_cannot_be_reflected_as_an_export_filter(metrics_runtime):
    metrics, contracts = reader_api()
    session_id = db.create_game_once("synthetic", "tianyi", str(uuid4()))["sessionId"]
    with pytest.raises(contracts.MetricsError) as caught:
        metrics.export_metrics(metrics_runtime, contracts.MetricsQuery(start=1000.0, end=1100.0, soupId=session_id))
    assert (caught.value.code, caught.value.status) == ("metrics_query_invalid", 422)
    assert session_id not in str(caught.value)


def test_actual_candidate_publication_counts_once_and_uses_observed_source(rule_storage):
    from app import metrics, metrics_contracts
    from .test_candidate_review_publication import approved
    with closing(db._connect()) as conn, conn:
        migrations.migrate(conn, rule_storage.soups, target_version=4)
    owner, run, candidate_id, publish_request = approved(rule_storage)
    publication = owner.publish(candidate_id, publish_request)
    assert owner.publish(candidate_id, publish_request) == publication  # Real receipt replay adds no event.
    with closing(db._connect()) as conn, conn:
        assert conn.execute("SELECT count(*) FROM audit_events WHERE event_type='candidate_published'").fetchone()[0] == 1
        assert conn.execute("SELECT count(*) FROM audit_events WHERE event_type='rule_published'").fetchone()[0] == 1
        published_at = conn.execute("SELECT created_at FROM audit_events WHERE event_type='candidate_published'").fetchone()[0]
        assert conn.execute("SELECT created_at FROM agent_runs WHERE id=?", (run.id,)).fetchone()[0] < published_at
        assert conn.execute("SELECT created_at FROM rule_candidates WHERE id=?", (candidate_id,)).fetchone()[0] < published_at
    gateway = rule_storage.model_gateway
    import time
    q = metrics_contracts.parse_metrics_query([("ruleVersion", run.manifest.context.observedRuleVersion)], now=time.time() + 1)
    page = metrics.query_metrics(rule_storage, q)
    excluded = page.summary.excluded.test
    assert (excluded.tasksCreated, excluded.candidatesCreated, excluded.reviewApproved, excluded.candidatePublicationEvents) == (1, 1, 1, 1)
    assert page.summary.counts.candidatePublicationEvents == 0  # Synthetic testing never becomes real traffic.
    new_version = metrics_contracts.parse_metrics_query([("ruleVersion", publication.publishedRuleVersion)], now=time.time() + 1)
    assert metrics.query_metrics(rule_storage, new_version).summary.excluded.test.candidatePublicationEvents == 0
    publication_window = metrics_contracts.MetricsQuery(start=published_at, end=published_at + 1,
        ruleVersion=run.manifest.context.observedRuleVersion)
    only_publication = metrics.query_metrics(rule_storage, publication_window)
    assert only_publication.summary.excluded.test.tasksCreated == only_publication.summary.excluded.test.candidatesCreated == 0
    assert only_publication.summary.excluded.test.candidatePublicationEvents == 1
    assert only_publication.summary.taskPublication.denominator == 0 and only_publication.summary.taskPublication.ratio is None
    assert rule_storage.model_gateway is gateway and rule_storage.model.calls == []


def test_candidate_states_use_sql_workflow_not_immutable_pending_json(rule_storage):
    from app import metrics, metrics_contracts
    from .test_candidate_review_store import proposal
    with closing(db._connect()) as conn, conn:
        migrations.migrate(conn, rule_storage.soups, target_version=4)
    _, original, original_candidate_id = proposal(rule_storage)
    manifest = original.manifest.model_copy(update={"trafficClass": "real"})
    with closing(db._connect()) as conn, conn:
        candidate = conn.execute("SELECT * FROM rule_candidates WHERE id=?", (original_candidate_id,)).fetchone()
        assert json.loads(candidate["candidate_json"])["status"] == "pending"
        # Only a declared synthetic status-volume fixture. Copies are NOT new
        # approval receipts, publishable candidates or real human-quality proof.
        # The immutable candidate/report body came from the genuine fake loop.
        for state in ("pending", "approved", "rejected", "published"):
            run_id, candidate_id = str(uuid4()), str(uuid4())
            conn.execute("INSERT INTO agent_runs(id,request_id,feedback_id,state,checkpoint_json,manifest_json,created_at,updated_at) VALUES(?,?,?,'awaiting_review',?,?,1001,1001)",
                (run_id, str(uuid4()), original.feedbackId, original.checkpoint.model_dump_json(), manifest.model_dump_json()))
            conn.execute("INSERT INTO rule_candidates(id,run_id,soup_id,base_rule_version,candidate_json,candidate_digest,regression_json,status,created_at) VALUES(?,?,?,?,?,?,?,?,1002)",
                (candidate_id, run_id, candidate["soup_id"], candidate["base_rule_version"], candidate["candidate_json"],
                    candidate["candidate_digest"], candidate["regression_json"], state))
    page = metrics.query_metrics(rule_storage, metrics_contracts.MetricsQuery(start=1000.0, end=1100.0))
    assert page.summary.counts.tasksCreated == 4 and page.summary.taskStates.awaiting_review == 4
    assert page.summary.counts.candidatesCreated == 4
    assert page.summary.candidateStates.model_dump() == dict(pending=1, approved=1, rejected=1, published=1)
    assert (page.summary.taskPublication.numerator, page.summary.taskPublication.denominator, page.summary.taskPublication.ratio) == (1, 4, 0.25)
    assert all(secret not in page.model_dump_json() for secret in (original_candidate_id, original.id, "PRIVATE", "evidenceSummary"))


def test_genuine_rejection_is_an_audit_action_not_a_successful_repair(rule_storage):
    import time
    from app import metrics, metrics_contracts
    from app.candidate_review_contracts import CandidateReject
    from .test_candidate_review_store import proposal
    with closing(db._connect()) as conn, conn:
        migrations.migrate(conn, rule_storage.soups, target_version=4)
    owner, run, candidate_id = proposal(rule_storage)
    request = CandidateReject(operationKey=str(uuid4()), expectedReviewVersion=0, reviewNote="Synthetic rejected claim")
    rejected = owner.reject(candidate_id, request)
    assert owner.reject(candidate_id, request) == rejected
    page = metrics.query_metrics(rule_storage, metrics_contracts.parse_metrics_query([], now=time.time() + 1))
    assert page.summary.excluded.test.reviewRejected == 1
    assert page.summary.excluded.test.reviewApproved == page.summary.excluded.test.candidatePublicationEvents == 0
    assert page.summary.taskPublication.ratio is None and rule_storage.model.calls == []


def test_query_only_is_native_and_connection_is_closed_after_success(metrics_runtime, monkeypatch):
    metrics, _ = reader_api()
    real_connect, real_summary = sqlite3.connect, metrics._summary
    connections = []

    class TrackedConnection(metrics._DeadlineConnection):
        closed = False
        transaction_on_close = None
        def close(self):
            self.transaction_on_close = self.in_transaction
            super().close()
            self.closed = True

    def connect(*args, **kwargs):
        kwargs["factory"] = TrackedConnection
        conn = real_connect(*args, **kwargs)
        connections.append(conn)
        return conn

    def summary(conn, parameters):
        with pytest.raises(sqlite3.OperationalError, match="readonly"):
            sqlite3.Connection.execute(conn, "UPDATE sessions SET questions_asked=99")
        return real_summary(conn, parameters)

    monkeypatch.setattr(sqlite3, "connect", connect)
    monkeypatch.setattr(metrics, "_summary", summary)
    query(metrics_runtime)
    assert len(connections) == 1 and connections[0].closed
    assert connections[0].transaction_on_close is False


def test_native_exclusive_lock_returns_busy_without_private_database_path(runtime):
    metrics, contracts = reader_api()
    # Build this owned fixture in rollback-journal mode from the start; do not
    # attempt to change the WAL mode while other fixture readers are open.
    runtime.soups = [puzzle()]
    blocker = sqlite3.connect(runtime.settings.DATA_DIR / "sessions.db", timeout=0.1)
    try:
        migrations.migrate(blocker, runtime.soups, target_version=4)
        blocker.execute("BEGIN EXCLUSIVE")
        with pytest.raises(contracts.MetricsError) as caught:
            query(runtime)
        assert (caught.value.code, caught.value.status) == ("metrics_busy", 503)
        assert str(runtime.settings.DATA_DIR) not in str(caught.value)
    finally:
        blocker.rollback()
        blocker.close()
    assert query(runtime).summary.counts.sessionsCreated == 0


def test_permanent_audit_gap_keeps_known_counts_and_reports_global_gap(metrics_runtime):
    session = db.create_game_once("synthetic", "tianyi", str(uuid4()))
    with closing(db._connect()) as conn, conn:
        conn.execute("UPDATE sessions SET traffic_class='real',created_at=1001 WHERE id=?", (session["sessionId"],))
    metrics_runtime.audit_store.note_failure(str(uuid4()))
    page = query(metrics_runtime)
    assert page.summary.counts.sessionsCreated == 1
    assert page.coverage.state == "partial"
    assert page.coverage.processAudit.permanentGap is True and page.coverage.processAudit.dropped == 1
    assert page.coverage.processAudit.complete is False


@pytest.mark.parametrize("mutation", ["unregistered_soup", "private_rule", "private_puzzle"])
def test_unknown_scope_never_exports_untrusted_identifiers(metrics_runtime, mutation):
    metrics, contracts = reader_api()
    saved = db.create_game_once("synthetic", "tianyi", str(uuid4()))
    canary = "PRIVATE_SOURCE_TEXT_MUST_NOT_ESCAPE"
    column = {"unregistered_soup": "soup_id", "private_rule": "rule_version", "private_puzzle": "puzzle_version"}[mutation]
    with closing(db._connect()) as conn, conn:
        conn.execute(f"UPDATE sessions SET {column}=?,traffic_class='real',created_at=1001 WHERE id=?", (canary, saved["sessionId"]))
    page = query(metrics_runtime)
    assert page.summary.counts.sessionsCreated == 1 and page.summary.unscopedReal.sessionsCreated == 1
    assert getattr(page.groups[0], {"unregistered_soup": "soupId", "private_rule": "ruleVersion", "private_puzzle": "puzzleVersion"}[mutation]) is None
    exported = metrics.export_metrics(metrics_runtime, contracts.MetricsQuery(start=1000.0, end=1100.0))
    assert canary not in page.model_dump_json() and canary not in exported.model_dump_json()
    assert saved["sessionId"] not in exported.model_dump_json()


def historical_metrics_catalog(conn, mutation=None):
    """Declared synthetic inactive snapshots, with genuine content-addressed IDs."""
    soup = puzzle().model_copy(update={'id': 'synthetic-history'})
    payload = {'schemaVersion': 1, 'soup': soup.model_dump(mode='json')}
    puzzle_version = 'p1:' + baselines.digest(payload)
    rules = {'schemaVersion': 1, 'rulesBySoup': {soup.id: {
        name: payload['soup'][name] for name in baselines.RULE_FIELDS}}}
    manifest = {'schemaVersion': 1, 'puzzleVersions': {soup.id: puzzle_version}, 'origin': 'legacy-baseline'}
    if mutation == 'rule_binding':
        manifest['puzzleVersions'][soup.id] = baselines.active_manifest(conn)['puzzleVersions']['synthetic']
    rule_version = 'r1:' + baselines.digest({'rules': rules, 'manifest': manifest})
    soup_id = 'PRIVATE_INACTIVE_CATALOG_CANARY' if mutation == 'puzzle_identity' else soup.id
    payload_json = '{}' if mutation == 'puzzle_digest' else baselines.canonical_json(payload)
    rules_json = '{}' if mutation == 'rule_digest' else baselines.canonical_json(rules)
    conn.execute('INSERT INTO puzzle_versions(id,soup_id,payload_json,created_at) VALUES(?,?,?,100)',
        (puzzle_version, soup_id, payload_json))
    conn.execute('INSERT INTO rule_releases(id,parent_id,rules_json,manifest_json,created_at) VALUES(?,NULL,?,?,100)',
        (rule_version, rules_json, baselines.canonical_json(manifest)))
    return soup_id, puzzle_version, rule_version, rules, manifest


def test_verified_inactive_history_remains_a_public_filter_and_export_scope(metrics_runtime):
    metrics, contracts = reader_api()
    with closing(db._connect()) as conn, conn:
        soup_id, puzzle_version, rule_version, _, _ = historical_metrics_catalog(conn)
        conn.execute("INSERT INTO sessions(id,soup_id,created_at,puzzle_version,rule_version,compat_state,traffic_class) VALUES(?,?,1001,?,?,'compatible','real')",
            (str(uuid4()), soup_id, puzzle_version, rule_version))
    page = query(metrics_runtime, soupId=soup_id, puzzleVersion=puzzle_version, ruleVersion=rule_version)
    assert page.summary.counts.sessionsCreated == 1
    assert (page.groups[0].soupId, page.groups[0].puzzleVersion, page.groups[0].ruleVersion) == (
        soup_id, puzzle_version, rule_version)
    exported = metrics.export_metrics(metrics_runtime, contracts.MetricsQuery(start=1000.0, end=1100.0,
        soupId=soup_id, puzzleVersion=puzzle_version, ruleVersion=rule_version))
    assert exported.complete and exported.groups[0].soupId == soup_id


@pytest.mark.parametrize('mutation', ['puzzle_digest', 'puzzle_identity', 'rule_digest', 'rule_binding'])
def test_inactive_registered_corrupt_snapshot_cannot_grant_public_dimensions(metrics_runtime, mutation):
    metrics, contracts = reader_api()
    canary = 'PRIVATE_INACTIVE_CATALOG_CANARY'
    with closing(db._connect()) as conn, conn:
        active = baselines.active_manifest(conn)
        # Insert corrupt inactive rows at the storage boundary; immutable-row
        # triggers remain intact and are not bypassed by the fixture.
        soup_id, puzzle_version, rule_version, _, _ = historical_metrics_catalog(conn, mutation)
        assert baselines.active_manifest(conn) == active  # Prior active-only verification misses this row.
        conn.execute("INSERT INTO sessions(id,soup_id,created_at,puzzle_version,rule_version,compat_state,traffic_class) VALUES(?,?,1001,?,?,'compatible','real')",
            (str(uuid4()), soup_id, puzzle_version, rule_version))
    for read in (lambda: query(metrics_runtime), lambda: metrics.export_metrics(metrics_runtime,
            contracts.MetricsQuery(start=1000.0, end=1100.0, soupId=soup_id))):
        with pytest.raises(contracts.MetricsError) as caught:
            read()
        assert (caught.value.code, caught.value.status) == ('metrics_unavailable', 503)
        assert canary not in str(caught.value)


@pytest.mark.parametrize("mutation", ["id", "type", "boolean_schema", "boolean_stamp"])
def test_audit_envelope_contradictions_are_unknown_not_real(metrics_runtime, mutation):
    event = AuditEvent(eventId=str(uuid4()), eventType="http_attempt", createdAt=1001.0,
        details=AttemptDetails(method="GET", routeTemplate="/health", statusCode=200, durationMs=1.0,
            outcome="success", responseStarted=True, disconnected=False, trafficClass="real"))
    data = event.model_dump(mode="json")
    if mutation == "id": data["eventId"] = str(uuid4())
    elif mutation == "type": data["eventType"] = "turn_committed"
    elif mutation == "boolean_schema": data["schemaVersion"] = True
    elif mutation == "boolean_stamp": data["createdAt"] = True
    with closing(db._connect()) as conn, conn:
        conn.execute("INSERT INTO audit_events(id,event_type,details_json,created_at) VALUES(?,'http_attempt',?,1001)",
            (event.eventId, baselines.canonical_json(data)))
    page = query(metrics_runtime)
    assert page.summary.counts.httpAttempts == 0
    assert page.summary.excluded.unknown.httpAttempts == 1


def test_traffic_classification_conflict_with_run_is_unknown(rule_storage):
    import time
    from app import metrics, metrics_contracts
    from .test_candidate_review_publication import approved
    with closing(db._connect()) as conn, conn:
        migrations.migrate(conn, rule_storage.soups, target_version=4)
    owner, run, candidate_id, request = approved(rule_storage)
    owner.publish(candidate_id, request)
    with closing(db._connect()) as conn, conn:
        row = conn.execute("SELECT id,details_json FROM audit_events WHERE event_type='candidate_published'").fetchone()
        raw = baselines.strict_json(row["details_json"])
        assert raw["details"]["trafficClass"] == run.manifest.trafficClass == "test"
        raw["details"]["trafficClass"] = "real"
        checked = AuditEvent.model_validate_json(baselines.canonical_json(raw))
        conn.execute("UPDATE audit_events SET details_json=? WHERE id=?", (checked.model_dump_json(), row["id"]))
    page = metrics.query_metrics(rule_storage, metrics_contracts.parse_metrics_query([], now=time.time() + 1))
    assert page.summary.counts.candidatePublicationEvents == 0
    assert page.summary.excluded.unknown.candidatePublicationEvents == 1


@pytest.mark.parametrize("failure", ["summary", "deadline", "clear_handler", "rollback", "close"])
def test_snapshot_cleanup_on_failure_is_closed_and_never_exposes_raw_error(metrics_runtime, monkeypatch, failure):
    metrics, contracts = reader_api()
    real_connect = sqlite3.connect
    connections = []
    canary = "PRIVATE_DATABASE_FAILURE_MUST_NOT_ESCAPE"

    class FaultConnection(metrics._DeadlineConnection):
        closed = False
        cleanup_calls = None

        def set_progress_handler(self, callback, n):
            if callback is None:
                self.cleanup_calls.append("clear_handler")
                if failure == "clear_handler":
                    raise sqlite3.OperationalError(canary)
            return super().set_progress_handler(callback, n)

        def rollback(self):
            self.cleanup_calls.append("rollback")
            super().rollback()
            if failure == "rollback":
                raise sqlite3.OperationalError(canary)

        def close(self):
            self.cleanup_calls.append("close")
            super().close()
            self.closed = True
            if failure == "close":
                raise sqlite3.OperationalError(canary)

    def connect(*args, **kwargs):
        kwargs["factory"] = FaultConnection
        conn = real_connect(*args, **kwargs)
        conn.cleanup_calls = []
        connections.append(conn)
        return conn

    monkeypatch.setattr(sqlite3, "connect", connect)
    if failure in {"summary", "deadline"}:
        def fail_summary(conn, parameters):
            if failure == "deadline":
                raise contracts.MetricsError("metrics_busy", 503)
            raise sqlite3.OperationalError(canary)
        monkeypatch.setattr(metrics, "_summary", fail_summary)
    with pytest.raises(contracts.MetricsError) as caught:
        query(metrics_runtime)
    assert caught.value.status == 503 and canary not in str(caught.value)
    assert caught.value.code == ("metrics_busy" if failure == "deadline" else "metrics_unavailable")
    assert len(connections) == 1 and connections[0].closed
    assert connections[0].cleanup_calls == ["clear_handler", "rollback", "close"]
    with pytest.raises(sqlite3.ProgrammingError, match="closed"):
        sqlite3.Connection.execute(connections[0], "SELECT 1")


@pytest.mark.parametrize("mutated_version", [None, "puzzleVersion", "ruleVersion"])
def test_genuine_linked_feedback_uses_source_even_when_turn_is_outside_window(metrics_runtime, mutated_version):
    from app.feedback_store import submit_feedback
    from .test_feedback_storage import body, completed_turn
    owner = completed_turn()
    item = submit_feedback(body(turnId=owner.turnId))
    assert item.sourceState == "linked"
    with closing(db._connect()) as conn, conn:
        row = conn.execute("SELECT id,details_json FROM audit_events WHERE event_type='feedback_submitted'").fetchone()
        event = AuditEvent.model_validate_json(row["details_json"]).model_copy(update={"createdAt": 1001.0})
        raw = event.model_dump(mode="json")
        raw["details"]["trafficClass"] = "real"  # Declared synthetic production-filter fixture.
        checked = AuditEvent.model_validate_json(baselines.canonical_json(raw))
        conn.execute("UPDATE audit_events SET created_at=1001,details_json=? WHERE id=?", (checked.model_dump_json(), row["id"]))
        conn.execute("UPDATE feedback_items SET created_at=1001 WHERE id=?", (item.id,))
        if mutated_version:
            source = json.loads(conn.execute("SELECT source_json FROM feedback_items WHERE id=?", (item.id,)).fetchone()[0])
            source[mutated_version] = "PRIVATE_INVALID_SOURCE_VERSION"
            conn.execute("UPDATE feedback_items SET source_json=? WHERE id=?", (baselines.canonical_json(source), item.id))
    page = query(metrics_runtime)
    assert page.summary.counts.feedbackSubmitted == 1
    assert page.summary.counts.successfulChargedTurns == 0  # Completion was not in this feedback window.
    assert page.groups[0].soupId == "synthetic"
    expected = dict(puzzleVersion=owner.puzzleVersion, ruleVersion=owner.ruleVersion)
    if mutated_version:
        expected[mutated_version] = None
    assert all(getattr(page.groups[0], name) == value for name, value in expected.items())
    assert page.summary.unscopedReal.feedbackSubmitted == int(mutated_version is not None)
    assert all(secret not in page.model_dump_json() for secret in (owner.sessionId, owner.turnId, item.id, "PRIVATE_INVALID_SOURCE_VERSION"))


def test_turn_is_counted_at_completion_not_session_or_reservation_time(metrics_runtime):
    session_id = db.create_game_once("synthetic", "tianyi", str(uuid4()))["sessionId"]
    owner = db.reserve_turn(session_id, str(uuid4()), "Synthetic boundary?", now=1099)
    db.finish_turn(owner, result(owner), now=1100)
    with closing(db._connect()) as conn, conn:
        conn.execute("UPDATE sessions SET traffic_class='real',created_at=900 WHERE id=?", (session_id,))
    earlier = query(metrics_runtime)
    later = query(metrics_runtime, start=1100, end=1200)
    assert earlier.summary.counts.sessionsCreated == earlier.summary.counts.successfulChargedTurns == 0
    assert later.summary.counts.sessionsCreated == 0 and later.summary.counts.successfulChargedTurns == 1


def test_pending_native_audit_fallback_is_gap_not_zero_until_recovered(metrics_runtime, monkeypatch):
    import asyncio
    original_connect = metrics_runtime.audit_store.connect
    def fail_database():
        raise sqlite3.OperationalError("PRIVATE_SYNTHETIC_DATABASE_DIAGNOSTIC")
    monkeypatch.setattr(metrics_runtime.audit_store, "connect", fail_database)
    event = AuditEvent(eventId=str(uuid4()), eventType="http_attempt", createdAt=1001.0,
        details=AttemptDetails(method="GET", routeTemplate="/health", statusCode=200, durationMs=1.0,
            outcome="success", responseStarted=True, disconnected=False, trafficClass="real"))
    assert metrics_runtime.audit_store.record_attempt(event).storage == "fallback"
    page = query(metrics_runtime)
    assert page.summary.counts.httpAttempts == 0
    assert page.coverage.processAudit.fallbackCount == 1 and page.coverage.processAudit.complete is False
    assert page.coverage.state == "partial"
    monkeypatch.setattr(metrics_runtime.audit_store, "connect", original_connect)
    assert asyncio.run(metrics_runtime.audit_store.recover(wait_ms=500)) is not None
    recovered = query(metrics_runtime)
    assert recovered.summary.counts.httpAttempts == 1
    assert recovered.coverage.processAudit.fallbackCount == 0 and recovered.coverage.processAudit.complete is True
