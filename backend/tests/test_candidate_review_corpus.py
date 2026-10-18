"""Trusted optional corpus plumbing; fixtures are synthetic, never production proof."""
from contextlib import closing
from dataclasses import replace
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from app.config import Settings
from app.runtime import Runtime
from app.testing import FakeModel
from .test_rule_snapshots import rule_storage
from .test_candidate_validation import scope
from .test_repair_corpus import frozen_corpus


def test_runtime_default_has_no_corpus_or_model_allocation(tmp_path):
    active = Runtime(Settings.for_test(tmp_path))
    assert active.repair_corpus is None and active.model_gateway is None and active.agent_worker is None
    assert not tmp_path.joinpath("sessions.db").exists()


def test_verified_corpus_runtime_input_is_owned_pure_and_does_not_allocate_model(rule_storage, tmp_path, monkeypatch):
    from app import db
    corpus = frozen_corpus(scope())
    model = FakeModel()
    # rule_storage already initialized tmp_path/sessions.db. Observe a fresh
    # owned target, not the fixture's deliberately pre-existing database.
    path = tmp_path / "pure-corpus-runtime"

    def forbidden(*args, **kwargs):
        raise AssertionError("Pure corpus construction touched files/database/model")

    with monkeypatch.context() as patch:
        patch.setattr(db, "_connect", forbidden)
        patch.setattr(Path, "read_bytes", forbidden)
        patch.setattr(Runtime, "get_model_gateway", forbidden)
        active = Runtime(Settings.for_test(path), model=model, soups=rule_storage.soups, repair_corpus=corpus)
    assert active.repair_corpus == corpus and active.repair_corpus is not corpus
    assert active.model_gateway is None and active.agent_worker is None and model.calls == []
    assert not path.exists()


@pytest.mark.parametrize("bad", ["raw_path", "dictionary", "altered", "holdout", "too_many", "foreign_soup", "synthetic_real"])
def test_corpus_input_refuses_wrong_proof_scope_and_synthetic_production_before_io(rule_storage, tmp_path, bad, monkeypatch):
    from app import db
    from app.agents.contracts import AgentError
    corpus = frozen_corpus(scope(), extra_cases=99 if bad == "too_many" else 0)
    soups = rule_storage.soups
    path = tmp_path / "invalid-corpus-runtime"
    settings = Settings.for_test(path, TESTING=bad != "synthetic_real")
    if bad == "raw_path":
        corpus = "PRIVATE/corpus.json"
    elif bad == "dictionary":
        corpus = corpus.model_dump(mode="json")
    elif bad == "altered":
        corpus = corpus.model_copy(update={"casesJson": "[]"})
    elif bad == "holdout":
        corpus = corpus.model_copy(update={"manifest": corpus.manifest.model_copy(update={"splitRole": "holdout"})})
    elif bad == "foreign_soup":
        soups = [soups[0].model_copy(update={"bottom": "Different synthetic source"})]
    def forbidden(*args, **kwargs):
        raise AssertionError("Rejected corpus touched files/database/model")

    # AgentError intentionally hides diagnostics; count boundary calls too so
    # catching a forbidden-I/O assertion cannot masquerade as input rejection.
    calls = []

    def recorded_forbidden(*args, **kwargs):
        calls.append(True)
        return forbidden(*args, **kwargs)

    with monkeypatch.context() as patch:
        patch.setattr(db, "_connect", recorded_forbidden)
        patch.setattr(Path, "read_bytes", recorded_forbidden)
        patch.setattr(Runtime, "get_model_gateway", recorded_forbidden)
        with pytest.raises(AgentError) as caught:
            Runtime(settings, soups=soups, repair_corpus=corpus)
    assert caught.value.code == "agent_corpus_invalid" and "PRIVATE" not in str(caught.value)
    assert calls == [] and not path.exists()


def test_app_factory_is_pure_and_disabled_lifespan_keeps_corpus_without_hidden_003_or_gateway(rule_storage, tmp_path):
    import sqlite3
    from app.main import create_app
    corpus = frozen_corpus(scope())
    path = tmp_path / "new-owned-app"
    model = FakeModel()
    app = create_app(Settings.for_test(path), model=model, soups=rule_storage.soups, repair_corpus=corpus)
    assert app.state.runtime is None and not path.exists() and model.calls == []
    with TestClient(app) as client:
        assert client.get("/health").status_code == 200
        active = app.state.runtime
        assert active.repair_corpus == corpus and active.model_gateway is None and active.agent_worker is None
    with closing(sqlite3.connect(path / "sessions.db")) as conn, conn:
        assert [row[0] for row in conn.execute("SELECT version FROM schema_migrations ORDER BY version")] == [1, 2]
    assert active.closed and model.calls == []


def test_enabled_worker_uses_same_verified_corpus_digest_without_model_call(rule_storage):
    from app import db
    from app.main import create_app
    from app.migrations import migrate
    corpus = frozen_corpus(scope())
    conn = db._connect()
    try:
        migrate(conn, rule_storage.soups, target_version=3)
    finally:
        conn.close()
    model = FakeModel()
    app = create_app(replace(rule_storage.settings, ENABLE_AGENT=True), model=model,
        soups=rule_storage.soups, repair_corpus=corpus)
    with TestClient(app) as client:
        assert client.get("/health").status_code == 200
        active = app.state.runtime
        regression = active.agent_worker.agent.executor.regression
        assert regression.corpus == active.repair_corpus == corpus
        assert regression.corpus.manifest.datasetDigest == corpus.manifest.datasetDigest
        assert model.calls == []
    assert active.agent_shutdown.cleanupConfirmed and active.model_shutdown["active"] == 0
