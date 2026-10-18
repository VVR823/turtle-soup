"""Native SQLite failures inside wrapped baseline SELECTs, never real data."""
import sqlite3

import pytest

from .test_metrics_queries import metrics_runtime, query, reader_api


# Removing the wrapped-cause translation must make the interrupt cases fail.
@pytest.mark.parametrize("target", ["pointer", "rules", "puzzle"])
@pytest.mark.parametrize("failure", ["interrupt", "permanent"])
def test_native_wrapped_baseline_failure_keeps_classification_and_closes(metrics_runtime, monkeypatch, target, failure):
    metrics, contracts = reader_api()
    real_connect = sqlite3.connect
    connections, observed = [], []
    selected_sql = {
        "pointer": "SELECT value_json FROM runtime_meta WHERE key='active_baseline'",
        "rules": "SELECT rules_json,manifest_json,parent_id FROM rule_releases WHERE id=?",
        "puzzle": "SELECT soup_id,payload_json FROM puzzle_versions WHERE id=?",
    }[target]

    class NativeFailureConnection(metrics._DeadlineConnection):
        closed = False

        def execute(self, sql, parameters=()):
            if sql != selected_sql:
                return super().execute(sql, parameters)
            try:
                if failure == "interrupt":
                    sqlite3.Connection.set_progress_handler(self, lambda: 1, 1)
                    return sqlite3.Connection.execute(self, sql, parameters)
                return sqlite3.Connection.execute(self, "SELECT * FROM PRIVATE_ABSENT_FIXTURE_TABLE")
            except sqlite3.Error as error:
                observed.append((sql, error.sqlite_errorcode))
                raise

        def close(self):
            super().close()
            self.closed = True

    def connect(*args, **kwargs):
        kwargs["factory"] = NativeFailureConnection
        conn = real_connect(*args, **kwargs)
        connections.append(conn)
        return conn

    monkeypatch.setattr(sqlite3, "connect", connect)
    with pytest.raises(contracts.MetricsError) as caught:
        query(metrics_runtime)
    # Native codes and exact targeted SQL prove this isn't an initial-schema fault.
    assert observed == [(selected_sql, 9 if failure == "interrupt" else 1)]
    assert (caught.value.code, caught.value.status) == (
        "metrics_busy" if failure == "interrupt" else "metrics_unavailable", 503)
    assert "PRIVATE" not in str(caught.value) and str(metrics_runtime.settings.DATA_DIR) not in str(caught.value)
    assert len(connections) == 1 and connections[0].closed
    with pytest.raises(sqlite3.ProgrammingError, match="closed"):
        sqlite3.Connection.execute(connections[0], "SELECT 1")
