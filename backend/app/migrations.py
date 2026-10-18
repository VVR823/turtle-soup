"""Explicit phased SQLite migrations. Default remains the released 001 phase.

Never use executescript for production migrations: it can commit an open
transaction. All schema, backfill and ledger writes share BEGIN IMMEDIATE.
"""
import sqlite3
import time
import math
import re
import uuid

from . import baselines
from .schemas import Soup
from .post_publication_schema import CHECKSUM_005, POST_PUBLICATION_OBJECTS, POST_PUBLICATION_SQL


class MigrationError(RuntimeError):
    pass


class MigrationRequired(MigrationError):
    pass


BASE_SQL = (
    """CREATE TABLE sessions (id TEXT PRIMARY KEY,soup_id TEXT NOT NULL,
        status TEXT NOT NULL DEFAULT 'playing',questions_asked INTEGER NOT NULL DEFAULT 0,
        question_limit INTEGER,created_at REAL NOT NULL,solved_at REAL,given_up_at REAL)""",
    """CREATE TABLE messages (id INTEGER PRIMARY KEY AUTOINCREMENT,session_id TEXT NOT NULL,
        role TEXT NOT NULL,content TEXT NOT NULL,timestamp REAL NOT NULL,
        is_free_reminder INTEGER NOT NULL DEFAULT 0,FOREIGN KEY(session_id) REFERENCES sessions(id))""",
)
CORE_SQL = (
    "CREATE TABLE schema_migrations (version INTEGER PRIMARY KEY,checksum TEXT NOT NULL,applied_at REAL NOT NULL)",
    "ALTER TABLE sessions ADD COLUMN row_version INTEGER NOT NULL DEFAULT 0",
    "ALTER TABLE sessions ADD COLUMN puzzle_version TEXT",
    "ALTER TABLE sessions ADD COLUMN rule_version TEXT",
    "ALTER TABLE sessions ADD COLUMN compat_state TEXT NOT NULL DEFAULT 'legacy'",
    "ALTER TABLE sessions ADD COLUMN last_activity_at REAL",
    """ALTER TABLE sessions ADD COLUMN traffic_class TEXT NOT NULL DEFAULT 'legacy'
        CHECK(traffic_class IN ('legacy','real','synthetic','test'))""",
    """CREATE TABLE puzzle_versions (id TEXT PRIMARY KEY,soup_id TEXT NOT NULL,
        payload_json TEXT NOT NULL,created_at REAL NOT NULL)""",
    """CREATE TABLE rule_releases (id TEXT PRIMARY KEY,parent_id TEXT REFERENCES rule_releases(id),
        rules_json TEXT NOT NULL,manifest_json TEXT NOT NULL,created_at REAL NOT NULL)""",
    "CREATE TABLE runtime_meta (key TEXT PRIMARY KEY,value_json TEXT NOT NULL,row_version INTEGER NOT NULL DEFAULT 0)",
    """CREATE TABLE creation_requests (request_id TEXT PRIMARY KEY,payload_hash TEXT NOT NULL,
        session_id TEXT NOT NULL UNIQUE REFERENCES sessions(id),response_json TEXT NOT NULL,created_at REAL NOT NULL)""",
    """CREATE TABLE turns (id TEXT PRIMARY KEY,session_id TEXT NOT NULL REFERENCES sessions(id),
        request_id TEXT NOT NULL,payload_hash TEXT NOT NULL,question TEXT NOT NULL,
        state TEXT NOT NULL CHECK(state IN ('reserved','completed','failed','expired')),
        kind TEXT CHECK(kind IN ('answer','reminder','system_error','win')),
        charged INTEGER NOT NULL DEFAULT 0 CHECK(charged IN (0,1)),response_json TEXT,result_json TEXT,
        lease_token TEXT,lease_expires_at REAL,puzzle_version TEXT NOT NULL,rule_version TEXT NOT NULL,
        engine_version TEXT NOT NULL,created_at REAL NOT NULL,completed_at REAL,UNIQUE(session_id,request_id))""",
    "CREATE UNIQUE INDEX idx_turns_active ON turns(session_id) WHERE state='reserved'",
    "ALTER TABLE messages ADD COLUMN turn_id TEXT REFERENCES turns(id)",
    "CREATE INDEX idx_messages_session_id ON messages(session_id,id)",
    """CREATE TABLE evaluations (session_id TEXT PRIMARY KEY REFERENCES sessions(id),
        response_json TEXT NOT NULL,basis_hash TEXT NOT NULL,created_at REAL NOT NULL)""",
    *tuple(f"""CREATE TRIGGER {table}_no_{operation.lower()} BEFORE {operation} ON {table}
        BEGIN SELECT RAISE(ABORT,'immutable baseline'); END"""
           for table in ("puzzle_versions", "rule_releases") for operation in ("UPDATE", "DELETE")),
)
# Changes to procedural snapshot/backfill semantics require a new migration,
# not editing an already-released checksum. This phase is not released yet.
CHECKSUM_001 = baselines.digest({"version": 1, "sql": BASE_SQL + CORE_SQL, "backfillContract": "legacy-v2"})
CORE_TABLES = {"sessions", "messages", "schema_migrations", "puzzle_versions", "rule_releases",
               "runtime_meta", "creation_requests", "turns", "evaluations"}

# Append-only registration: never edit BASE_SQL/CORE_SQL/CHECKSUM_001.
AUDIT_SQL = (
    """CREATE TABLE feedback_items (
        id TEXT PRIMARY KEY,soup_id TEXT NOT NULL,turn_id TEXT REFERENCES turns(id),
        payload_json TEXT NOT NULL,source_json TEXT NOT NULL,
        status TEXT NOT NULL CHECK(status IN ('pending','approved','rejected')),
        safe_for_model INTEGER NOT NULL DEFAULT 0 CHECK(safe_for_model IN (0,1)),
        row_version INTEGER NOT NULL DEFAULT 0,created_at REAL NOT NULL,reviewed_at REAL)""",
    """CREATE TABLE audit_events (
        id TEXT PRIMARY KEY,request_id TEXT,session_id TEXT,turn_id TEXT,run_id TEXT,
        event_type TEXT NOT NULL,details_json TEXT NOT NULL,created_at REAL NOT NULL)""",
    "CREATE INDEX idx_audit_events_time ON audit_events(created_at,event_type)",
    "CREATE INDEX idx_feedback_status ON feedback_items(status,created_at)",
)
CHECKSUM_002 = baselines.digest({"version": 2, "sql": AUDIT_SQL, "coverageContract": "http-attempt-v1"})

# 003 is append-only and explicitly offline. Never change either prior SQL tuple.
AGENT_SQL = (
    """CREATE TABLE agent_runs (
        id TEXT PRIMARY KEY,request_id TEXT NOT NULL UNIQUE,
        feedback_id TEXT NOT NULL REFERENCES feedback_items(id),
        state TEXT NOT NULL CHECK(state IN ('queued','running','awaiting_review','needs_human','failed','cancelled')),
        checkpoint_json TEXT NOT NULL CHECK(length(checkpoint_json) BETWEEN 1 AND 262144),
        manifest_json TEXT NOT NULL CHECK(length(manifest_json) BETWEEN 1 AND 524288),
        lease_token TEXT,lease_expires_at REAL,
        row_version INTEGER NOT NULL DEFAULT 0 CHECK(typeof(row_version)='integer' AND row_version>=0),
        created_at REAL NOT NULL,updated_at REAL NOT NULL,
        CHECK((lease_token IS NULL)=(lease_expires_at IS NULL)))""",
    """CREATE TABLE agent_steps (
        run_id TEXT NOT NULL REFERENCES agent_runs(id),
        seq INTEGER NOT NULL CHECK(typeof(seq)='integer' AND seq>=0),
        operation_key TEXT NOT NULL UNIQUE,
        action_json TEXT NOT NULL CHECK(length(action_json) BETWEEN 1 AND 32768),
        result_json TEXT CHECK(result_json IS NULL OR length(result_json) BETWEEN 1 AND 32768),
        state TEXT NOT NULL CHECK(state IN ('planned','completed','failed')),
        created_at REAL NOT NULL,PRIMARY KEY(run_id,seq))""",
    """CREATE TABLE rule_candidates (
        id TEXT PRIMARY KEY,run_id TEXT NOT NULL UNIQUE REFERENCES agent_runs(id),
        soup_id TEXT NOT NULL,base_rule_version TEXT NOT NULL,
        candidate_json TEXT NOT NULL CHECK(length(candidate_json) BETWEEN 1 AND 32768),
        candidate_digest TEXT NOT NULL CHECK(length(candidate_digest)=64 AND candidate_digest NOT GLOB '*[^0-9a-f]*'),
        regression_json TEXT NOT NULL CHECK(length(regression_json) BETWEEN 1 AND 32768),
        status TEXT NOT NULL CHECK(status IN ('pending','approved','rejected','published')),
        created_at REAL NOT NULL,reviewed_at REAL,
        published_release_id TEXT REFERENCES rule_releases(id))""",
    "CREATE INDEX idx_agent_runs_state ON agent_runs(state,updated_at)",
    """CREATE TRIGGER agent_runs_manifest_immutable BEFORE UPDATE ON agent_runs
        WHEN NEW.id IS NOT OLD.id OR NEW.request_id IS NOT OLD.request_id
        OR NEW.feedback_id IS NOT OLD.feedback_id OR NEW.manifest_json IS NOT OLD.manifest_json
        OR NEW.created_at IS NOT OLD.created_at
        BEGIN SELECT RAISE(ABORT,'immutable agent manifest'); END""",
    """CREATE TRIGGER agent_steps_action_immutable BEFORE UPDATE ON agent_steps
        WHEN NEW.run_id IS NOT OLD.run_id OR NEW.seq IS NOT OLD.seq
        OR NEW.operation_key IS NOT OLD.operation_key OR NEW.action_json IS NOT OLD.action_json
        OR NEW.created_at IS NOT OLD.created_at
        BEGIN SELECT RAISE(ABORT,'immutable agent action'); END""",
    """CREATE TRIGGER agent_steps_result_immutable BEFORE UPDATE ON agent_steps
        WHEN OLD.state!='planned'
        BEGIN SELECT RAISE(ABORT,'immutable completed agent step'); END""",
    """CREATE TRIGGER agent_steps_no_delete BEFORE DELETE ON agent_steps
        BEGIN SELECT RAISE(ABORT,'immutable agent step history'); END""",
    """CREATE TRIGGER rule_candidates_body_immutable BEFORE UPDATE ON rule_candidates
        WHEN NEW.id IS NOT OLD.id OR NEW.run_id IS NOT OLD.run_id OR NEW.soup_id IS NOT OLD.soup_id
        OR NEW.base_rule_version IS NOT OLD.base_rule_version OR NEW.candidate_json IS NOT OLD.candidate_json
        OR NEW.candidate_digest IS NOT OLD.candidate_digest OR NEW.regression_json IS NOT OLD.regression_json
        OR NEW.created_at IS NOT OLD.created_at
        BEGIN SELECT RAISE(ABORT,'immutable candidate body'); END""",
    """CREATE TRIGGER rule_candidates_no_delete BEFORE DELETE ON rule_candidates
        BEGIN SELECT RAISE(ABORT,'immutable candidate history'); END""",
)
CHECKSUM_003 = baselines.digest({"version": 3, "sql": AGENT_SQL, "coverageContract": "no-historical-agent-v1"})


# 004 only adds range indexes. The released SQL/checksums above stay intact.
METRICS_SQL = (
    "CREATE INDEX idx_sessions_created ON sessions(created_at,id)",
    "CREATE INDEX idx_turns_completed ON turns(completed_at,id)",
    "CREATE INDEX idx_feedback_created ON feedback_items(created_at,id)",
    "CREATE INDEX idx_agent_runs_created ON agent_runs(created_at,id)",
    "CREATE INDEX idx_rule_candidates_created ON rule_candidates(created_at,id)",
)
CHECKSUM_004 = baselines.digest({"version": 4, "sql": METRICS_SQL, "coverageContract": "metrics-indexes-v1"})
_METRICS_INDEX_NAMES = [re.match(r"CREATE INDEX ([a-z_]+)", sql).group(1) for sql in METRICS_SQL]


def _registered_sql(sql):
    # Normalize syntax only. Case/whitespace in SQL string literals changes
    # CHECK semantics and must retain exactly the registered bytes.
    return "".join(part if part.startswith("'") else " ".join(part.split()).lower()
        for part in re.findall(r"'(?:''|[^'])*'|[^']+", sql))


def _verify_audit_schema(conn):
    # Names alone do not prove the index columns, FK, defaults or CHECK clauses.
    for kind, name, sql in zip(
        ("table", "table", "index", "index"),
        ("feedback_items", "audit_events", "idx_audit_events_time", "idx_feedback_status"),
        AUDIT_SQL,
    ):
        row = conn.execute("SELECT sql FROM sqlite_master WHERE type=? AND name=?", (kind, name)).fetchone()
        if row is None or not isinstance(row[0], str) or _registered_sql(row[0]) != _registered_sql(sql):
            raise MigrationError("Registered audit schema is missing or drifted")
    try:
        coverage_row = conn.execute("SELECT value_json FROM runtime_meta WHERE key='audit_coverage_start'").fetchone()
        report_row = conn.execute("SELECT value_json FROM runtime_meta WHERE key='migration_002_report'").fetchone()
        coverage = baselines.strict_json(coverage_row[0]) if coverage_row else None
        report = baselines.strict_json(report_row[0]) if report_row else None
        if (not isinstance(coverage, dict) or coverage.get("schemaVersion") != 1
            or coverage.get("historicalAttemptsBackfilled") is not False or not _valid_time(coverage.get("startedAt"))
            or not isinstance(report, dict) or report.get("migrationVersion") != 2
            or report.get("phase002") != {"checksum": CHECKSUM_002, "coverageStart": coverage["startedAt"]}):
            raise MigrationError("Audit migration coverage report is missing or invalid")
    except (ValueError, TypeError) as error:
        raise MigrationError("Audit migration coverage report is invalid") from error


def _verify_agent_schema(conn):
    for statement in AGENT_SQL:
        kind, name = re.match(r"CREATE (TABLE|INDEX|TRIGGER) ([a-z_]+)", statement).groups()
        row = conn.execute("SELECT sql FROM sqlite_master WHERE type=? AND name=?", (kind.lower(), name)).fetchone()
        if row is None or not isinstance(row[0], str) or _registered_sql(row[0]) != _registered_sql(statement):
            raise MigrationError("Registered agent schema is missing or drifted")
    if conn.execute("PRAGMA foreign_key_check").fetchone() is not None:
        raise MigrationError("Agent phase database contains orphan references")
    try:
        row = conn.execute("SELECT value_json FROM runtime_meta WHERE key='migration_003_report'").fetchone()
        prior = conn.execute("SELECT value_json FROM runtime_meta WHERE key='migration_002_report'").fetchone()
        report = baselines.strict_json(row[0]) if row else None
        old = baselines.strict_json(prior[0]) if prior else None
        phase = report.get("phase003") if isinstance(report, dict) else None
        if (not isinstance(report, dict) or type(report.get("migrationVersion")) is not int or report["migrationVersion"] != 3
            or not isinstance(old, dict) or not isinstance(phase, dict)
            or set(phase) != {"checksum", "coverageStart", "historicalRunsBackfilled"}
            or phase["checksum"] != CHECKSUM_003 or phase["historicalRunsBackfilled"] is not False
            or not _valid_time(phase["coverageStart"])
            or {k: v for k, v in report.items() if k not in {"migrationVersion", "phase003"}}
                != {k: v for k, v in old.items() if k != "migrationVersion"}):
            raise MigrationError("Agent migration coverage report is missing or invalid")
    except (ValueError, TypeError) as error:
        raise MigrationError("Agent migration coverage report is invalid") from error


def table_names(conn) -> set[str]:
    return {row[0] for row in conn.execute("SELECT name FROM sqlite_master WHERE type='table'")}


def _verify_metrics_schema(conn):
    for name, statement in zip(_METRICS_INDEX_NAMES, METRICS_SQL):
        row = conn.execute("SELECT sql FROM sqlite_master WHERE type='index' AND name=?", (name,)).fetchone()
        if row is None or not isinstance(row[0], str) or _registered_sql(row[0]) != _registered_sql(statement):
            raise MigrationError("Registered metrics indexes are missing or drifted")
    try:
        row = conn.execute("SELECT value_json FROM runtime_meta WHERE key='migration_004_report'").fetchone()
        prior = conn.execute("SELECT value_json FROM runtime_meta WHERE key='migration_003_report'").fetchone()
        report = baselines.strict_json(row[0]) if row else None
        old = baselines.strict_json(prior[0]) if prior else None
        phase = report.get("phase004") if isinstance(report, dict) else None
        if (not isinstance(report, dict) or type(report.get("migrationVersion")) is not int or report["migrationVersion"] != 4
            or not isinstance(old, dict) or not isinstance(phase, dict)
            or set(phase) != {"checksum", "indexNames", "noHistoricalBackfill"}
            or phase["checksum"] != CHECKSUM_004 or phase["indexNames"] != _METRICS_INDEX_NAMES
            or phase["noHistoricalBackfill"] is not True
            or {k: v for k, v in report.items() if k not in {"migrationVersion", "phase004"}}
                != {k: v for k, v in old.items() if k != "migrationVersion"}):
            raise MigrationError("Metrics migration report is missing or invalid")
    except (ValueError, TypeError) as error:
        raise MigrationError("Metrics migration report is invalid") from error


def _verify_post_publication_schema(conn):
    for (kind, name), statement in zip(POST_PUBLICATION_OBJECTS, POST_PUBLICATION_SQL):
        row = conn.execute('SELECT sql FROM sqlite_master WHERE type=? AND name=?', (kind, name)).fetchone()
        if row is None or not isinstance(row[0], str) or _registered_sql(row[0]) != _registered_sql(statement):
            raise MigrationError('Registered post-publication schema is missing or drifted')
    try:
        row = conn.execute("SELECT value_json FROM runtime_meta WHERE key='migration_005_report'").fetchone()
        prior = conn.execute("SELECT value_json FROM runtime_meta WHERE key='migration_004_report'").fetchone()
        report = baselines.strict_json(row[0]) if row else None
        old = baselines.strict_json(prior[0]) if prior else None
        phase = report.get('phase005') if isinstance(report, dict) else None
        if (not isinstance(report, dict) or type(report.get('migrationVersion')) is not int or report['migrationVersion'] != 5
            or not isinstance(old, dict) or not isinstance(phase, dict)
            or set(phase) != {'checksum', 'coverageStart', 'noHistoricalBackfill'}
            or phase['checksum'] != CHECKSUM_005 or phase['noHistoricalBackfill'] is not True
            or not _valid_time(phase['coverageStart'])
            or {k: v for k, v in report.items() if k not in {'migrationVersion', 'phase005'}}
                != {k: v for k, v in old.items() if k != 'migrationVersion'}):
            raise MigrationError('Post-publication migration report is missing or invalid')
    except (ValueError, TypeError) as error:
        raise MigrationError('Post-publication migration report is invalid') from error


def _validate_base(conn):
    for table, required in (
        ("sessions", {"id", "soup_id", "status", "questions_asked", "question_limit", "created_at", "solved_at", "given_up_at"}),
        ("messages", {"id", "session_id", "role", "content", "timestamp", "is_free_reminder"}),
    ):
        actual = {row[1] for row in conn.execute(f"PRAGMA table_info({table})")}
        if not required <= actual:
            raise MigrationError("Unknown legacy database schema")
    for table, identity, expected_type in (("sessions", "id", "TEXT"), ("messages", "id", "INTEGER")):
        columns = list(conn.execute(f"PRAGMA table_info({table})"))
        primary = [row for row in columns if row[5]]
        if len(primary) != 1 or primary[0][1] != identity or primary[0][2].upper() != expected_type:
            raise MigrationError("Unknown legacy identity constraint")
    foreign_keys = list(conn.execute("PRAGMA foreign_key_list(messages)"))
    if not any(row[2] == "sessions" and row[3] == "session_id" and row[4] == "id" for row in foreign_keys):
        raise MigrationError("Legacy messages require a session foreign key")
    if conn.execute("""SELECT 1 FROM messages m LEFT JOIN sessions s ON s.id=m.session_id
                       WHERE s.id IS NULL LIMIT 1""").fetchone():
        raise MigrationError("Legacy messages contain an orphan session reference")


def verify_schema(conn, *, required_version: int = 1) -> None:
    if type(required_version) is not int or required_version not in (1, 2, 3, 4, 5):
        raise MigrationError("Unregistered required migration version")
    if "schema_migrations" not in table_names(conn):
        raise MigrationRequired("Existing database requires explicit offline migration")
    rows = [tuple(row) for row in conn.execute("SELECT version,checksum FROM schema_migrations ORDER BY version")]
    expected = [(1, CHECKSUM_001), (2, CHECKSUM_002), (3, CHECKSUM_003), (4, CHECKSUM_004), (5, CHECKSUM_005)]
    if len(rows) not in (1, 2, 3, 4, 5) or rows != expected[:len(rows)]:
        raise MigrationError("Unknown migration version or checksum mismatch")
    if not CORE_TABLES <= table_names(conn):
        raise MigrationError("Migrated database is missing core tables")
    _validate_base(conn)
    if not {"row_version", "puzzle_version", "rule_version", "compat_state", "last_activity_at", "traffic_class"} <= {
        row[1] for row in conn.execute("PRAGMA table_info(sessions)")
    } or "turn_id" not in {row[1] for row in conn.execute("PRAGMA table_info(messages)")}:
        raise MigrationError("Migrated database is missing core columns")
    names = {row[0] for row in conn.execute("SELECT name FROM sqlite_master WHERE type IN ('index','trigger')")}
    required = {"idx_messages_session_id", "idx_turns_active", "puzzle_versions_no_update", "puzzle_versions_no_delete",
                "rule_releases_no_update", "rule_releases_no_delete"}
    if not required <= names:
        raise MigrationError("Migrated database is missing integrity protections")
    baselines.active_manifest(conn)
    if len(rows) >= 2:
        _verify_audit_schema(conn)
    elif required_version >= 2:
        raise MigrationRequired("Audit features require explicit offline migration 002")
    if len(rows) >= 3:
        _verify_agent_schema(conn)
    elif required_version >= 3:
        raise MigrationRequired("Agent features require explicit offline migration 003")
    if len(rows) >= 4:
        _verify_metrics_schema(conn)
    elif required_version >= 4:
        raise MigrationRequired("Metrics features require explicit offline migration 004")
    if len(rows) == 5:
        _verify_post_publication_schema(conn)
    elif required_version == 5:
        raise MigrationRequired('Post-publication features require explicit offline migration 005')


def _original_rows(conn):
    return (
        [tuple(r) for r in conn.execute("SELECT id,soup_id,status,questions_asked,question_limit,created_at,solved_at,given_up_at FROM sessions ORDER BY id")],
        [tuple(r) for r in conn.execute("SELECT id,session_id,role,content,timestamp,is_free_reminder FROM messages ORDER BY id")],
    )


def _valid_time(value) -> bool:
    return isinstance(value, (int, float)) and not isinstance(value, bool) and math.isfinite(value) and value >= 0


def _legacy_backfill(conn, baseline: dict) -> dict:
    issues, compatible = [], 0
    for session in conn.execute("SELECT * FROM sessions ORDER BY id").fetchall():
        messages = conn.execute("SELECT * FROM messages WHERE session_id=? ORDER BY id", (session["id"],)).fetchall()
        codes = []
        version = baseline["puzzleVersions"].get(session["soup_id"])
        if version is None:
            codes.append("missing_puzzle")
        if (not session["id"] or session["status"] not in {"playing", "solved", "given_up"}
            or type(session["questions_asked"]) is not int or session["questions_asked"] < 0
            or (session["question_limit"] is not None and (type(session["question_limit"]) is not int or session["question_limit"] < 0))
            or not _valid_time(session["created_at"])):
            codes.append("invalid_session")
        solved, given_up = session["solved_at"], session["given_up_at"]
        if (session["status"] == "playing" and (solved is not None or given_up is not None)
            or session["status"] == "solved" and (not _valid_time(solved) or given_up is not None)
            or session["status"] == "given_up" and (not _valid_time(given_up) or solved is not None)):
            codes.append("terminal_conflict")
        if len(messages) % 2 or any(m["role"] != ("user" if i % 2 == 0 else "host") for i, m in enumerate(messages)):
            codes.append("unpaired_messages")
        if any(not isinstance(m["content"], str) or not _valid_time(m["timestamp"]) or m["is_free_reminder"] not in (0, 1) for m in messages):
            codes.append("invalid_message")
        pairs = list(zip(messages[::2], messages[1::2]))
        if any(user["is_free_reminder"] != host["is_free_reminder"] for user, host in pairs):
            codes.append("reminder_mismatch")
        if session["questions_asked"] != sum(m["role"] == "user" and m["is_free_reminder"] == 0 for m in messages):
            codes.append("count_mismatch")
        ref = baselines.digest({"sessionId": session["id"]})
        for code in codes:
            issues.append({"code": code, "sessionRef": ref})
        last_activity = max([session["created_at"]] + [m["timestamp"] for m in messages if _valid_time(m["timestamp"])]) if _valid_time(session["created_at"]) else None
        conn.execute("UPDATE sessions SET puzzle_version=?,rule_version=?,compat_state=?,last_activity_at=? WHERE id=?",
                     (version, baseline["ruleVersion"], "incompatible" if codes else "compatible", last_activity, session["id"]))
        if codes:
            continue  # Preserve all original messages, no made-up pairing or repaired count.
        compatible += 1
        for user, host in pairs:
            turn_id = str(uuid.uuid5(uuid.NAMESPACE_URL, f"turtle-soup:legacy:{ref}:{user['id']}:{host['id']}"))
            free = bool(user["is_free_reminder"])
            conn.execute("""INSERT INTO turns
                (id,session_id,request_id,payload_hash,question,state,kind,charged,result_json,
                 puzzle_version,rule_version,engine_version,created_at,completed_at)
                VALUES (?,?,?,?,?,'completed',?,?,?,?,?,'legacy-unversioned',?,?)""",
                (turn_id, session["id"], turn_id, baselines.digest({"question": user["content"]}), user["content"],
                 "reminder" if free else "answer", 0 if free else 1,
                 baselines.canonical_json({"schemaVersion": 1, "source": "legacy", "answerVerified": False}),
                 version, baseline["ruleVersion"], user["timestamp"], host["timestamp"]))
            conn.execute("UPDATE messages SET turn_id=? WHERE id IN (?,?)", (turn_id, user["id"], host["id"]))
    return {"compatibleSessions": compatible, "incompatibleSessions": conn.execute("SELECT count(*) FROM sessions").fetchone()[0] - compatible,
            "issues": issues}


def _migrate_001(conn: sqlite3.Connection, soups: list[Soup], *, legacy_records: list | None = None) -> dict:
    if conn.in_transaction:
        raise MigrationError("Migration requires an idle dedicated connection")
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA foreign_keys=ON")
    names = table_names(conn)
    if "schema_migrations" in names:
        verify_schema(conn)
        row = conn.execute("SELECT value_json FROM runtime_meta WHERE key='migration_001_report'").fetchone()
        if row is None:
            raise MigrationError("Migration report is missing")
        return baselines.strict_json(row[0])
    if names - {"sqlite_sequence"} and not {"sessions", "messages"} <= names:
        raise MigrationError("Unknown database; refusing to initialize over it")
    try:
        conn.execute("BEGIN IMMEDIATE")
        if not names - {"sqlite_sequence"}:
            for statement in BASE_SQL:
                conn.execute(statement)
        _validate_base(conn)
        before = _original_rows(conn)
        for statement in CORE_SQL:
            conn.execute(statement)
        from .legacy_import import import_records
        imported = import_records(conn, legacy_records or [])
        baseline = baselines.store_baseline(conn, soups)
        report = {"schemaVersion": 1, "migrationVersion": 1,
                  "sessionsBefore": len(before[0]), "messagesBefore": len(before[1]),
                  "baseline": baseline, "issues": []}
        report.update(_legacy_backfill(conn, baseline))
        report["legacyRecords"], report["importedSessions"] = imported["legacyRecords"], imported["importedSessions"]
        report["issues"].extend(imported["issues"])
        after = _original_rows(conn)
        old_session_ids, old_message_ids = {r[0] for r in before[0]}, {r[0] for r in before[1]}
        if ([r for r in after[0] if r[0] in old_session_ids], [r for r in after[1] if r[0] in old_message_ids]) != before:
            raise MigrationError("Original records changed during migration")
        if conn.execute("PRAGMA foreign_key_check").fetchone() or conn.execute("PRAGMA integrity_check").fetchone()[0] != "ok":
            raise MigrationError("Database integrity checks failed")
        conn.execute("INSERT INTO runtime_meta (key,value_json) VALUES ('migration_001_report',?)",
                     (baselines.canonical_json(report),))
        conn.execute("INSERT INTO schema_migrations (version,checksum,applied_at) VALUES (1,?,?)", (CHECKSUM_001, time.time()))
        verify_schema(conn)
        conn.commit()
        return report
    except BaseException as error:
        conn.rollback()
        if isinstance(error, (sqlite3.Error, ValueError, OverflowError, baselines.SnapshotError)):
            raise MigrationError("Migration failed; this phase was rolled back") from error
        raise


def _migrate_to_audit(conn: sqlite3.Connection, soups: list[Soup], *, legacy_records: list | None = None, target_version: int = 1) -> dict:
    if type(target_version) is not int or target_version not in (1, 2):
        raise MigrationError("Unregistered target migration version")
    report001 = _migrate_001(conn, soups, legacy_records=legacy_records)
    if target_version == 1:
        return report001
    if conn.execute("SELECT 1 FROM schema_migrations WHERE version=2").fetchone():
        return baselines.strict_json(conn.execute("SELECT value_json FROM runtime_meta WHERE key='migration_002_report'").fetchone()[0])
    try:
        conn.execute("BEGIN IMMEDIATE")
        for statement in AUDIT_SQL:
            conn.execute(statement)
        started = time.time()
        coverage = {"schemaVersion": 1, "startedAt": started, "historicalAttemptsBackfilled": False}
        report = {**report001, "migrationVersion": 2, "phase002": {"checksum": CHECKSUM_002, "coverageStart": started}}
        conn.execute("INSERT INTO runtime_meta (key,value_json) VALUES ('audit_coverage_start',?)", (baselines.canonical_json(coverage),))
        conn.execute("INSERT INTO runtime_meta (key,value_json) VALUES ('migration_002_report',?)", (baselines.canonical_json(report),))
        conn.execute("INSERT INTO schema_migrations (version,checksum,applied_at) VALUES (2,?,?)", (CHECKSUM_002, started))
        verify_schema(conn, required_version=2)
        if conn.execute("PRAGMA foreign_key_check").fetchone() or conn.execute("PRAGMA integrity_check").fetchone()[0] != "ok":
            raise MigrationError("Audit migration integrity checks failed")
        conn.commit()
        return report
    except BaseException as error:
        conn.rollback()
        if isinstance(error, (sqlite3.Error, ValueError, OverflowError, baselines.SnapshotError)):
            raise MigrationError("Audit migration failed; phase 002 was rolled back") from error
        raise


def _migrate_to_agent(conn: sqlite3.Connection, soups: list[Soup], *, legacy_records: list | None = None, target_version: int = 1) -> dict:
    if type(target_version) is not int or target_version not in (1, 2, 3):
        raise MigrationError("Unregistered target migration version")
    report = _migrate_to_audit(conn, soups, legacy_records=legacy_records, target_version=min(target_version, 2))
    if target_version < 3:
        return report
    if conn.execute("SELECT 1 FROM schema_migrations WHERE version=3").fetchone():
        return baselines.strict_json(conn.execute("SELECT value_json FROM runtime_meta WHERE key='migration_003_report'").fetchone()[0])
    try:
        conn.execute("BEGIN IMMEDIATE")
        for statement in AGENT_SQL:
            conn.execute(statement)
        started = time.time()
        report = {**report, "migrationVersion": 3, "phase003": {
            "checksum": CHECKSUM_003, "coverageStart": started, "historicalRunsBackfilled": False}}
        conn.execute("INSERT INTO runtime_meta(key,value_json) VALUES('migration_003_report',?)", (baselines.canonical_json(report),))
        conn.execute("INSERT INTO schema_migrations(version,checksum,applied_at) VALUES(3,?,?)", (CHECKSUM_003, started))
        verify_schema(conn, required_version=3)
        if conn.execute("PRAGMA foreign_key_check").fetchone() or conn.execute("PRAGMA integrity_check").fetchone()[0] != "ok":
            raise MigrationError("Agent migration integrity checks failed")
        conn.commit()
        return report
    except BaseException as error:
        conn.rollback()
        if isinstance(error, (sqlite3.Error, ValueError, OverflowError, baselines.SnapshotError)):
            raise MigrationError("Agent migration failed; phase 003 was rolled back") from error
        raise


def _migrate_to_metrics(conn: sqlite3.Connection, soups: list[Soup], *, legacy_records: list | None = None, target_version: int = 1) -> dict:
    if type(target_version) is not int or target_version not in (1, 2, 3, 4):
        raise MigrationError("Unregistered target migration version")
    report = _migrate_to_agent(conn, soups, legacy_records=legacy_records, target_version=min(target_version, 3))
    if target_version < 4:
        return report
    if conn.execute("SELECT 1 FROM schema_migrations WHERE version=4").fetchone():
        return baselines.strict_json(conn.execute("SELECT value_json FROM runtime_meta WHERE key='migration_004_report'").fetchone()[0])
    try:
        conn.execute("BEGIN IMMEDIATE")
        for statement in METRICS_SQL:
            conn.execute(statement)
        report = {**report, "migrationVersion": 4, "phase004": {
            "checksum": CHECKSUM_004, "indexNames": list(_METRICS_INDEX_NAMES), "noHistoricalBackfill": True}}
        conn.execute("INSERT INTO runtime_meta(key,value_json) VALUES('migration_004_report',?)", (baselines.canonical_json(report),))
        conn.execute("INSERT INTO schema_migrations(version,checksum,applied_at) VALUES(4,?,?)", (CHECKSUM_004, time.time()))
        verify_schema(conn, required_version=4)
        if conn.execute("PRAGMA foreign_key_check").fetchone() or conn.execute("PRAGMA integrity_check").fetchone()[0] != "ok":
            raise MigrationError("Metrics migration integrity checks failed")
        conn.commit()
        return report
    except BaseException as error:
        conn.rollback()
        if isinstance(error, (sqlite3.Error, ValueError, OverflowError, baselines.SnapshotError)):
            raise MigrationError("Metrics migration failed; phase 004 was rolled back") from error
        raise


def migrate(conn: sqlite3.Connection, soups: list[Soup], *, legacy_records: list | None = None, target_version: int = 1) -> dict:
    if type(target_version) is not int or target_version not in (1, 2, 3, 4, 5):
        raise MigrationError('Unregistered target migration version')
    report = _migrate_to_metrics(conn, soups, legacy_records=legacy_records, target_version=min(target_version, 4))
    if target_version < 5:
        return report
    if conn.execute('SELECT 1 FROM schema_migrations WHERE version=5').fetchone():
        return baselines.strict_json(conn.execute("SELECT value_json FROM runtime_meta WHERE key='migration_005_report'").fetchone()[0])
    try:
        conn.execute('BEGIN IMMEDIATE')
        for statement in POST_PUBLICATION_SQL:
            conn.execute(statement)
        started = time.time()
        report = {**report, 'migrationVersion': 5, 'phase005': {
            'checksum': CHECKSUM_005, 'coverageStart': started, 'noHistoricalBackfill': True}}
        conn.execute("INSERT INTO runtime_meta(key,value_json) VALUES('migration_005_report',?)", (baselines.canonical_json(report),))
        conn.execute('INSERT INTO schema_migrations(version,checksum,applied_at) VALUES(5,?,?)', (CHECKSUM_005, started))
        verify_schema(conn, required_version=5)
        if conn.execute('PRAGMA foreign_key_check').fetchone() or conn.execute('PRAGMA integrity_check').fetchone()[0] != 'ok':
            raise MigrationError('Post-publication migration integrity checks failed')
        conn.commit()
        return report
    except BaseException as error:
        conn.rollback()
        if isinstance(error, (sqlite3.Error, ValueError, OverflowError, baselines.SnapshotError)):
            raise MigrationError('Post-publication migration failed; phase005 was rolled back') from error
        raise
