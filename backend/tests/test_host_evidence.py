"""Pinned evidence is source-bound data, never similarity answer authority."""
from contextlib import closing
import importlib
import importlib.util
import json
from dataclasses import FrozenInstanceError

import pytest

from app import baselines, db
from app.config import Settings
from app.host_context import build_puzzle_context
from app.runtime import Runtime, runtime_context
from app.schemas import Checkpoint, ConfusionPoint, Soup, TruthItem


def module():
    assert importlib.util.find_spec("app.host_evidence") is not None, "Missing pinned evidence compiler"
    return importlib.import_module("app.host_evidence")


def soup(soup_id="synthetic"):
    return Soup(id=soup_id, title="Public title", surface="Public surface",
                bottom="Synthetic: 小明是凶手。小红不是凶手。",
                checkpoints=[Checkpoint(key="小明是凶手", answer=True),
                             Checkpoint(key="小红是凶手", answer=False)],
                truthItems=[TruthItem(subject="小明", relation="身份是", object="凶手",
                                     evidence="小明是凶手")],
                confusionPoints=[ConfusionPoint(q="小明是凶手吗", a="是", match=["小明.*凶手"],
                                                note="Synthetic authored full question")])


def pin(tmp_path, selected):
    active = Runtime(Settings.for_test(tmp_path), soups=[selected])
    with runtime_context(active):
        db.initialize()
        with closing(db._connect()) as conn, conn:
            manifest = baselines.active_manifest(conn)
            version = manifest["puzzleVersions"][selected.id]
            actual = baselines.session_soup(conn, version)
    return actual, version


def test_catalog_ids_are_stable_and_bind_actual_source_payload(tmp_path):
    selected, version = pin(tmp_path, soup())
    first = module().build_evidence_catalog(selected, version)
    second = module().build_evidence_catalog(selected, version)
    assert first == second and len(first) == 5
    assert {r.sourcePath for r in first} == {"bottom", "checkpoints[0]", "checkpoints[1]",
                                           "truthItems[0]", "confusionPoints[0]"}
    facts = [record for record in first if record.sourcePath == "truthItems[0]"]
    assert len(facts) == 1
    record = facts[0]
    assert record.soupId == "synthetic" and record.puzzleVersion == version
    assert json.loads(record.payload) == {"subject": "小明", "relation": "身份是", "object": "凶手",
                                          "evidence": "小明是凶手", "confidence": "high"}
    assert len({r.id for r in first}) == len(first)
    assert all(r.puzzleVersion == version and r.soupId == "synthetic" for r in first)


def test_same_text_in_other_soup_or_changed_version_never_reuses_fact_id(tmp_path):
    first, v1 = pin(tmp_path / "one", soup())
    other, v2 = pin(tmp_path / "two", soup("another-soup"))
    changed, v3 = pin(tmp_path / "three", soup().model_copy(update={"title": "Changed public title"}))
    records = [next(r for r in module().build_evidence_catalog(s, v) if r.sourcePath == "truthItems[0]")
               for s, v in ((first, v1), (other, v2), (changed, v3))]
    assert records[0].payload == records[1].payload == records[2].payload
    assert len({r.id for r in records}) == 3


@pytest.mark.parametrize("version", ["p1:" + "0" * 64, "unversioned", None])
def test_plausible_or_missing_version_without_matching_source_is_refused(tmp_path, version):
    selected, _ = pin(tmp_path, soup())
    with pytest.raises(baselines.SnapshotError):
        module().build_evidence_catalog(selected, version)


def test_changed_source_cannot_claim_old_verified_version(tmp_path):
    selected, version = pin(tmp_path, soup())
    changed = selected.model_copy(update={"bottom": "Synthetic opposite source"})
    with pytest.raises(baselines.SnapshotError):
        module().build_evidence_catalog(changed, version)


def test_non_puzzle_value_cannot_enter_the_evidence_boundary():
    with pytest.raises(baselines.SnapshotError, match="valid puzzle snapshot"):
        module().validate_puzzle_snapshot({"id": "synthetic"}, "p1:" + "0" * 64)


def test_empty_optional_truth_and_single_character_query_are_handled_explicitly(tmp_path):
    selected, version = pin(tmp_path, soup().model_copy(update={"bottom": ""}))
    catalog = module().build_evidence_catalog(selected, version)
    assert all(record.sourcePath != "bottom" for record in catalog)
    assert module().retrieve_evidence(selected, "小", puzzle_version=version)


def test_evidence_payload_is_immutable_and_only_existing_records_are_retrieved(tmp_path):
    selected, version = pin(tmp_path, soup())
    catalog = module().build_evidence_catalog(selected, version)
    matches = module().retrieve_evidence(selected, "小明不是凶手吗？", puzzle_version=version, limit=2)
    assert isinstance(matches, tuple) and 1 <= len(matches) <= 2
    assert all(record in catalog for record in matches)
    assert all(not hasattr(record, "answer") and not hasattr(record, "match") for record in matches)
    with pytest.raises((FrozenInstanceError, AttributeError, TypeError)):
        matches[0].payload = "forged"
    assert module().retrieve_evidence(selected, "zzzzzzz", puzzle_version=version) == ()


@pytest.mark.parametrize("limit", [0, 9, True])
def test_retrieval_bound_cannot_be_disabled_by_invalid_limit(tmp_path, limit):
    selected, version = pin(tmp_path, soup())
    with pytest.raises(ValueError):
        module().retrieve_evidence(selected, "小明是凶手吗", puzzle_version=version, limit=limit)


def test_evidence_only_rag_candidates_do_not_lock_opposite_polarity_answer(tmp_path):
    from app import rag
    selected, version = pin(tmp_path, soup())
    assert hasattr(rag, "retrieve_candidates"), "Missing evidence-only RAG API"
    candidates = rag.retrieve_candidates("小明不是凶手吗？", selected, puzzle_version=version)
    assert candidates and all(r.puzzleVersion == version for r in candidates)
    assert all(not hasattr(r, "answer") and not hasattr(r, "checkpoint") for r in candidates)


def test_verified_context_keeps_full_truth_and_source_ids_without_truncating_evidence(tmp_path):
    selected, version = pin(tmp_path, soup())
    context = build_puzzle_context(soup=selected, system_prompt="Synthetic instructions",
                                  question="小明是凶手吗？", history=[], puzzle_version=version)
    assert selected.bottom in context.user
    fact = next(r for r in module().build_evidence_catalog(selected, version) if r.sourcePath == "truthItems[0]")
    assert fact.id in context.user and fact.payload in context.user
    assert context.input_chars <= 8000


def test_context_mismatched_puzzle_version_is_not_silently_empty_evidence(tmp_path):
    selected, _ = pin(tmp_path, soup())
    with pytest.raises(baselines.SnapshotError):
        build_puzzle_context(soup=selected, system_prompt="Synthetic instructions", question="小明是凶手吗？",
                             history=[], puzzle_version="p1:" + "0" * 64)
