"""Migration fixtures own their connections after committing or rejecting drift."""
import sqlite3

import pytest

from . import test_agent_migrations


@pytest.mark.parametrize('mutation', ['checksum', 'missing_table'])
def test_drift_fixture_closes_its_database_after_verification(tmp_path, monkeypatch, mutation):
    original = sqlite3.connect
    opened = []

    def connect(*args, **kwargs):
        connection = original(*args, **kwargs)
        opened.append(connection)
        return connection

    monkeypatch.setattr(sqlite3, 'connect', connect)
    try:
        test_agent_migrations.test_003_structural_or_coverage_drift_refuses_read_only(tmp_path, mutation)
        assert opened
        for connection in opened:
            with pytest.raises(sqlite3.ProgrammingError, match='closed'):
                connection.execute('SELECT 1')
    finally:
        for connection in opened:
            connection.close()
