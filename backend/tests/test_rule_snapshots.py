"""Actual immutable SQLite releases; forged overlay/source must not be trusted."""
import json
from uuid import uuid4

import pytest
from pydantic import ValidationError

from app import baselines, db
from app.host_evidence import build_evidence_catalog
from app.schemas import Soup


@pytest.fixture
def rule_storage(runtime):
    runtime.soups = [Soup(id="synthetic", title="Test", surface="Surface", bottom="小明是凶手。",
        confusionPoints=[{"q": "小明是凶手吗？", "a": "不是"}])]
    db.initialize()
    return runtime


def release_rows():
    conn = db._connect()
    try:
        return [tuple(row) for row in conn.execute("SELECT * FROM rule_releases ORDER BY rowid")]
    finally:
        conn.close()


def schema2(conn, *, change=None, parent_column=None, manifest_change=None):
    active = baselines.active_manifest(conn)
    p1 = active["puzzleVersions"]["synthetic"]
    original, _ = baselines._rule_release(conn, active["ruleVersion"])
    fact = build_evidence_catalog(baselines.session_soup(conn, p1), p1)[0]
    old_soup = baselines.session_soup(conn, p1)
    full_target = baselines.digest(dict(type="confusion", sourcePath="confusionPoints[0]",
        sourcePayload=old_soup.confusionPoints[0].model_dump(mode="json"), puzzleVersion=p1,
        baseRuleVersion=active["ruleVersion"], normalizationVersion="exact-v1"))
    overlay = dict(schemaVersion=1, type="exact_qa", op="replace", canonicalQuestionKey="小明是凶手吗",
        question="小明是凶手吗？", normalizationVersion="exact-v1", answer="是", factIds=[fact.id],
        targetRuleDigest=full_target, puzzleVersion=p1, baseRuleVersion=active["ruleVersion"],
        candidateDigest="b" * 64, reportDigest="c" * 64, confirmedContext=True)
    draft = {name: overlay[name] for name in ("op", "canonicalQuestionKey", "question", "answer", "factIds",
        "targetRuleDigest", "puzzleVersion", "baseRuleVersion", "confirmedContext")}
    overlay["reviewReceipt"] = dict(draftDigest=baselines.digest(draft), candidateDigest="b" * 64,
        regressionReportId=str(uuid4()), reportDigest="c" * 64, suiteManifestDigest="d" * 64,
        puzzleVersion=p1, baseRuleVersion=active["ruleVersion"], status="complete", answerSupported=True,
        contextIndependent=True, reviewNote="Synthetic reviewed snapshot")
    overlay.update(change or {})
    # This fixture owns a fresh synthetic review of this exact body. A source
    # test must not accidentally pass only because an unrelated old receipt
    # fails its digest check first.
    overlay["reviewReceipt"]["draftDigest"] = baselines.digest({name: overlay[name] for name in draft})
    overlay["reviewReceipt"]["puzzleVersion"] = overlay["puzzleVersion"]
    overlay["reviewReceipt"]["baseRuleVersion"] = overlay["baseRuleVersion"]
    rules = dict(schemaVersion=2, rulesBySoup=original["rulesBySoup"], exactQaBySoup={"synthetic": [overlay]})
    manifest = dict(schemaVersion=2, puzzleVersions=active["puzzleVersions"], origin="reviewed-exact-rule",
        parentRuleVersion=active["ruleVersion"])
    manifest.update(manifest_change or {})
    r1 = "r1:" + baselines.digest({"rules": rules, "manifest": manifest})
    conn.execute("INSERT INTO rule_releases(id,parent_id,rules_json,manifest_json,created_at) VALUES(?,?,?,?,0)",
        (r1, parent_column or active["ruleVersion"], baselines.canonical_json(rules), baselines.canonical_json(manifest)))
    return p1, r1, overlay


def test_schema1_read_is_empty_overlay_and_original_bytes_unchanged(rule_storage):
    from app.rule_contract import read_rule_snapshot
    before = release_rows(); conn = db._connect()
    try:
        active = baselines.active_manifest(conn)
        result = read_rule_snapshot(conn, active["puzzleVersions"]["synthetic"], active["ruleVersion"])
        assert result.soupId == "synthetic" and result.exactRules == ()
        assert json.loads(result.releaseRulesJson)["schemaVersion"] == 1
    finally:
        conn.close()
    assert release_rows() == before and rule_storage.model.calls == []


def test_schema2_overlay_preserves_original_puzzle_and_whole_snapshot_proof(rule_storage):
    from app.rule_contract import read_rule_snapshot
    before = release_rows(); conn = db._connect()
    try:
        p1, r1, _ = schema2(conn); conn.commit()
        result = read_rule_snapshot(conn, p1, r1)
        assert result.exactRules[0].answer == "是" and result.exactRules[0].canonicalQuestionKey == "小明是凶手吗"
        assert baselines.session_baseline(conn, p1, r1).confusionPoints[0].a == "不是"
        assert "r1:" + baselines.digest({"rules": json.loads(result.releaseRulesJson),
            "manifest": json.loads(result.releaseManifestJson)}) == r1
        conn.execute("UPDATE runtime_meta SET value_json=? WHERE key='active_baseline'",
            (json.dumps({"schemaVersion": 1, "ruleVersion": r1}),)); conn.commit()
        assert baselines.active_manifest(conn)["ruleVersion"] == r1
        with pytest.raises(ValidationError):
            result.exactRules[0].answer = "不是"
    finally:
        conn.close()
    assert release_rows()[0] == before[0] and rule_storage.model.calls == []


@pytest.mark.parametrize("change", [
    {"schemaVersion": True}, {"confirmedContext": False}, {"canonicalQuestionKey": "小明不是凶手吗"},
    {"normalizationVersion": "fuzzy-v1"}, {"answer": "大概是"}, {"factIds": ["f1:" + "f" * 64]},
    {"factIds": []}, {"extraPlayerBody": "private"}, {"puzzleVersion": "p1:" + "f" * 64},
    {"baseRuleVersion": "r1:" + "e" * 64}, {"question": "他是凶手吗？", "canonicalQuestionKey": "他是凶手吗"},
    {"op": "add", "targetRuleDigest": "a" * 64}, {"op": "replace", "targetRuleDigest": None},
])
def test_untrusted_rule_fields_refused_even_with_recomputed_release_digest(rule_storage, change):
    from app.rule_contract import read_rule_snapshot
    conn = db._connect()
    try:
        p1, r1, _ = schema2(conn, change=change); conn.commit()
        with pytest.raises(baselines.SnapshotError):
            read_rule_snapshot(conn, p1, r1)
        with pytest.raises(baselines.SnapshotError):
            baselines.session_baseline(conn, p1, r1)
    finally:
        conn.close()


def test_manifest_parent_column_mismatch_is_not_valid_release(rule_storage):
    from app.rule_contract import read_rule_snapshot
    conn = db._connect()
    try:
        other = "r1:" + "f" * 64
        # FK deliberately uses a real existing row, manifest points elsewhere.
        p1, r1, _ = schema2(conn, manifest_change={"parentRuleVersion": other}); conn.commit()
        with pytest.raises(baselines.SnapshotError):
            read_rule_snapshot(conn, p1, r1)
    finally:
        conn.close()


def test_unknown_schema2_manifest_fields_are_not_inert_metadata(rule_storage):
    from app.rule_contract import read_rule_snapshot
    conn = db._connect()
    try:
        p1, r1, _ = schema2(conn, manifest_change={"modelChosenPath": "arbitrary"}); conn.commit()
        with pytest.raises(baselines.SnapshotError):
            read_rule_snapshot(conn, p1, r1)
    finally:
        conn.close()


def test_duplicate_exact_keys_are_not_arbitrary_first_match(rule_storage):
    from app.rule_contract import read_rule_snapshot
    conn = db._connect()
    try:
        p1, _, overlay = schema2(conn)
        active = baselines.active_manifest(conn)
        original, _ = baselines._rule_release(conn, active["ruleVersion"])
        rules = dict(schemaVersion=2, rulesBySoup=original["rulesBySoup"], exactQaBySoup={"synthetic": [overlay, overlay]})
        manifest = dict(schemaVersion=2, puzzleVersions=active["puzzleVersions"], origin="reviewed-exact-rule",
            parentRuleVersion=active["ruleVersion"])
        r1 = "r1:" + baselines.digest({"rules": rules, "manifest": manifest})
        conn.execute("INSERT INTO rule_releases(id,parent_id,rules_json,manifest_json,created_at) VALUES(?,?,?,?,0)",
            (r1, active["ruleVersion"], baselines.canonical_json(rules), baselines.canonical_json(manifest)))
        conn.commit()
        with pytest.raises(baselines.SnapshotError):
            read_rule_snapshot(conn, p1, r1)
    finally:
        conn.close()


def test_recomputed_r1_does_not_make_fake_replacement_source_real(rule_storage):
    from app.rule_contract import read_rule_snapshot
    conn = db._connect()
    try:
        p1, r1, _ = schema2(conn, change={"targetRuleDigest": "f" * 64}); conn.commit()
        with pytest.raises(baselines.SnapshotError):
            read_rule_snapshot(conn, p1, r1)
    finally:
        conn.close()
