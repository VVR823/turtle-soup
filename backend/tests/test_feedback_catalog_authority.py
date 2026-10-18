"""Runtime never treats old JSONL feedback as new rules; rehearsal is explicit."""
import json

import pytest

from app import db, migrations
from app.config import Settings
from app.runtime import Runtime, runtime_context
from .test_migrations import puzzle


def legacy_file(directory, filename="verified_qa_pairs.jsonl"):
    directory.mkdir(parents=True, exist_ok=True)
    path = directory / filename
    content = json.dumps(dict(soupId="synthetic", feedbackId="legacy", confusionPoint=dict(q="小明是凶手吗？", a="是")),
        ensure_ascii=False).encode() + b"\n"
    path.write_bytes(content)
    return path, content


def test_runtime_does_not_inject_legacy_verified_jsonl(tmp_path, monkeypatch):
    path, content = legacy_file(tmp_path / "owned")
    monkeypatch.setattr(db, "SEED_SOUPS", [puzzle().model_dump(mode="json")])
    runtime = Runtime(Settings.for_test(path.parent, LOAD_RUNTIME_PUZZLES=True))
    with runtime_context(runtime):
        soups = db.get_soups()
    assert [item.q for item in soups[0].confusionPoints] == ["Question?"]
    assert path.read_bytes() == content and not (path.parent / "sessions.db").exists()


@pytest.mark.parametrize("filename", ["verified_qa_pairs.jsonl", "feedback.jsonl"])
@pytest.mark.parametrize("include_runtime", [True, False])
def test_empty_app_with_legacy_rules_requires_explicit_rehearsal(tmp_path, filename, include_runtime):
    path, content = legacy_file(tmp_path / "owned", filename)
    runtime = Runtime(Settings.for_test(path.parent, LOAD_RUNTIME_PUZZLES=include_runtime), soups=[puzzle()])
    with runtime_context(runtime):
        with pytest.raises(migrations.MigrationRequired):
            db.initialize()
    assert not runtime.initialized and not (path.parent / "sessions.db").exists()
    assert path.read_bytes() == content


def test_migration_catalog_explicit_legacy_verified_preserves_old_semantics(tmp_path, monkeypatch):
    path, content = legacy_file(tmp_path / "owned")
    monkeypatch.setattr(db, "SEED_SOUPS", [puzzle().model_dump(mode="json")])
    legacy = db.load_catalog(path.parent, include_legacy_verified=True)
    plain = db.load_catalog(path.parent, include_legacy_verified=False)
    assert [item.q for item in legacy[0].confusionPoints] == ["Question?", "小明是凶手吗？"]
    assert [item.q for item in plain[0].confusionPoints] == ["Question?"]
    assert path.read_bytes() == content and not (path.parent / "sessions.db").exists()


def test_existing_registered_database_uses_frozen_rules_even_if_legacy_file_is_bad(tmp_path, monkeypatch):
    directory = tmp_path / "owned"; runtime = Runtime(Settings.for_test(directory), soups=[puzzle()])
    with runtime_context(runtime): db.initialize()
    path = directory / "verified_qa_pairs.jsonl"; path.write_bytes(b"not-json-private-legacy\n")
    monkeypatch.setattr(db, "SEED_SOUPS", [puzzle().model_dump(mode="json")])
    reloaded = Runtime(Settings.for_test(directory, LOAD_RUNTIME_PUZZLES=True))
    with runtime_context(reloaded): db.initialize()
    assert [item.q for item in reloaded.soups[0].confusionPoints] == ["Question?"]
    assert path.read_bytes() == b"not-json-private-legacy\n"
