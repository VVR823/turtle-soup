"""The actual bounded reader query, not a hand-written stand-in SQL plan."""
import sqlite3

from app import db
from app.runtime import runtime_context
from .test_audit_admin import ADMIN, api, seed


def test_five_thousand_rows_query_uses_time_index_and_sql_limit(api, monkeypatch):
    stamp = seed(api, 5000)
    statements = []; plans = []
    class ObservedConnection(sqlite3.Connection):
        def execute(self, sql, parameters=()):
            if sql.startswith("SELECT id,request_id,session_id,turn_id,run_id,event_type,details_json,created_at") and "created_at>=?" in sql:
                statements.append((sql, parameters))
                plans.extend(tuple(row) for row in super().execute("EXPLAIN QUERY PLAN " + sql, parameters))
            return super().execute(sql, parameters)
    def tracked(*, timeout=10):
        with runtime_context(api[0].state.runtime):
            conn = sqlite3.connect(api[0].state.runtime.settings.DATA_DIR / "sessions.db", timeout=timeout, factory=ObservedConnection)
            conn.row_factory = sqlite3.Row
            return conn
    monkeypatch.setattr(db, "_connect", tracked)
    response = api[1].get("/api/audit/admin", params={"limit": 3, "start": stamp - 1, "end": stamp + 1}, headers=ADMIN)
    assert response.status_code == 200 and len(response.json()["events"]) == 3
    assert response.json()["nextCursor"]
    assert len(statements) == 1 and statements[0][0].endswith("LIMIT ?")
    assert statements[0][1][-1] == 4  # One look-ahead, never all 5000 rows.
    assert any("idx_audit_events_time" in str(row) for row in plans)
