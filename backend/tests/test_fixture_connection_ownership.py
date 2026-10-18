"""Fixtures must preserve their committed setup without leaking owned handles."""
import sqlite3

import pytest

from app import db
from . import test_metrics_queries, test_post_publication_store


def assert_closed(connections):
    assert connections
    for connection in connections:
        with pytest.raises(sqlite3.ProgrammingError, match='closed'):
            connection.execute('SELECT 1')


def test_metrics_setup_closes_owned_connections_before_returning_runtime(runtime, monkeypatch):
    original = db._connect
    opened = []

    def connect(*args, **kwargs):
        connection = original(*args, **kwargs)
        opened.append(connection)
        return connection

    monkeypatch.setattr(db, '_connect', connect)
    try:
        active = test_metrics_queries.metrics_runtime.__wrapped__(runtime)
        assert active is runtime
        assert_closed(opened)
    finally:
        for connection in opened:
            connection.close()


def test_publication_store_setup_closes_connections_and_preserves_committed_schema(runtime, monkeypatch):
    original = sqlite3.connect
    opened = []

    def connect(*args, **kwargs):
        connection = original(*args, **kwargs)
        opened.append(connection)
        return connection

    monkeypatch.setattr(sqlite3, 'connect', connect)
    try:
        active, database, _, _ = test_post_publication_store.owned.__wrapped__(runtime)
        assert active is runtime
        assert_closed(opened)
        check = original(database)
        try:
            assert check.execute('SELECT max(version) FROM schema_migrations').fetchone()[0] == 5
        finally:
            check.close()
    finally:
        for connection in opened:
            connection.close()
