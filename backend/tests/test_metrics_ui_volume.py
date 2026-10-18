"""UI statistical fixtures require exact server nonce and preexisting phase4."""
from contextlib import closing
import sqlite3
from uuid import uuid4

import pytest

from app import baselines, migrations
from .test_migrations import puzzle


def database(tmp_path, *, nonce=None, phase=4):
    soups = [puzzle().model_copy(update={"id": f"synthetic-{i}"}) for i in range(4)]
    with closing(sqlite3.connect(tmp_path / "sessions.db")) as conn, conn:
        migrations.migrate(conn, soups, target_version=phase)
        if nonce is not None:
            conn.execute("INSERT INTO runtime_meta(key,value_json) VALUES('owned_ui_fixture',?)", (baselines.canonical_json({"instanceId": nonce}),))


def test_metrics_ui_volume_missing_or_foreign_nonce_has_no_rows(tmp_path):
    from testing.metrics_ui_fixture import seed_owned_metrics_volume
    nonce = str(uuid4()); database(tmp_path, nonce=nonce)
    with pytest.raises(ValueError, match="belong"):
        seed_owned_metrics_volume(tmp_path, str(uuid4()))
    with closing(sqlite3.connect(tmp_path / "sessions.db")) as conn, conn:
        assert conn.execute("SELECT count(*) FROM sessions").fetchone()[0] == 0


def test_metrics_ui_volume_never_creates_missing_database(tmp_path):
    from testing.metrics_ui_fixture import seed_owned_metrics_volume
    with pytest.raises(sqlite3.OperationalError):
        seed_owned_metrics_volume(tmp_path, str(uuid4()))
    assert not (tmp_path / "sessions.db").exists()


def test_declared_metrics_ui_volume_is_repeat_safe_and_not_candidates(tmp_path):
    from testing.metrics_ui_fixture import seed_owned_metrics_volume
    nonce = str(uuid4()); database(tmp_path, nonce=nonce)
    first = seed_owned_metrics_volume(tmp_path, nonce)
    second = seed_owned_metrics_volume(tmp_path, nonce)
    assert first["evidenceKind"] == second["evidenceKind"] == "declared_synthetic_ui_volume"
    assert first["sessionRows"] == second["sessionRows"] == 105
    with closing(sqlite3.connect(tmp_path / "sessions.db")) as conn, conn:
        assert conn.execute("SELECT count(*) FROM sessions").fetchone()[0] == 105
        assert conn.execute("SELECT count(*) FROM agent_runs").fetchone()[0] == 0
        assert conn.execute("SELECT count(*) FROM rule_candidates").fetchone()[0] == 0


def test_actual_owned_ui_server_nonce_allows_only_its_synthetic_volume(tmp_path):
    from fastapi.testclient import TestClient
    from .test_ui_agent_fixture import app
    from testing.metrics_ui_fixture import seed_owned_metrics_volume
    application = app(tmp_path)
    with TestClient(application) as client:
        settings = application.state.runtime.settings
        health = client.get('/health').json()
        assert health['instanceId'] == settings.TEST_INSTANCE_ID
        result = seed_owned_metrics_volume(settings.DATA_DIR, settings.TEST_INSTANCE_ID)
        assert result['evidenceKind'] == 'declared_synthetic_ui_volume' and result['sessionRows'] == 105
