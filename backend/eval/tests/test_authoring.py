"""Compile only explicit private AI drafts; never invent manual review."""
import hashlib
import json

import pytest

from .test_seed_catalog import IDS


def author(path):
    body = {"schemaVersion": 1, "soupIds": list(IDS), "authorBatchId": "synthetic-test-only",
        "collectedAt": "2026-10-09T05:46:53Z", "entries": [{"soupId": "xin", "question": "合成编译测试问题？",
            "caseType": "single", "sourceGroup": "owned-ai-batch", "familyGroup": "one-question",
            "conversationId": None, "contextIndex": None, "categories": ["literal"], "proposedLabel": None,
            "factSourcePaths": ["bottom"]}]}
    path.write_text(json.dumps(body, ensure_ascii=False), encoding="utf-8")
    return body


def compile_owned(path, tmp_path):
    from eval.authoring import compile_authoring
    return compile_authoring(path, cases_output=tmp_path / "cases.json", catalog_output=tmp_path / "catalog.json", audit_output=tmp_path / "audit.json")


def test_explicit_source_compiles_pending_private_artifacts_with_real_fact_refs(tmp_path):
    from eval.manifest import read_case_bundle
    from eval.grouping import GroupAudit
    path = tmp_path / "author.json"; author(path); before = path.read_bytes()
    counted = compile_owned(path, tmp_path)
    assert counted.inputCount == counted.pendingCount == 1 and counted.eligibleCount == 0
    bundle = read_case_bundle(tmp_path / "cases.json"); item = bundle.cases[0]
    assert counted.auditComplete is False and counted.deficits.single == 59
    assert item.review is None and item.authorRole == "ai_draft" and item.visibility == "private"
    assert item.proposedFactIds and item.evidenceSourceDigest == hashlib.sha256(before).hexdigest()
    assert bundle.sourceDigests[0].sourceDigest == item.evidenceSourceDigest
    assert path.read_bytes() == before
    assert GroupAudit.model_validate_json((tmp_path / "audit.json").read_text(encoding="utf-8")).complete is False
    assert len(json.loads((tmp_path / "catalog.json").read_text(encoding="utf-8"))["puzzles"]) == 6


def test_existing_output_is_refused_before_any_new_artifact(tmp_path):
    from eval.contracts import DatasetError
    path = tmp_path / "author.json"; author(path)
    (tmp_path / "catalog.json").write_bytes(b"original")
    with pytest.raises(DatasetError): compile_owned(path, tmp_path)
    assert not (tmp_path / "cases.json").exists() and not (tmp_path / "audit.json").exists()
    assert (tmp_path / "catalog.json").read_bytes() == b"original"


@pytest.mark.parametrize("bad", ["foreign-soup", "arbitrary-path", "human-label", "bad-schema"])
def test_authoring_unknown_scope_or_extra_review_fields_refuse(tmp_path, bad):
    from eval.contracts import DatasetError
    path = tmp_path / "author.json"; body = author(path)
    if bad == "foreign-soup": body["entries"][0]["soupId"] = "foreign"
    if bad == "arbitrary-path": body["entries"][0]["factSourcePaths"] = ["../../.env"]
    if bad == "human-label": body["entries"][0]["review"] = {"humanConfirmed": True}
    if bad == "bad-schema": body["schemaVersion"] = True
    path.write_text(json.dumps(body), encoding="utf-8")
    with pytest.raises(DatasetError): compile_owned(path, tmp_path)
    assert not (tmp_path / "cases.json").exists()


def test_authoring_output_alias_is_refused_before_writing(tmp_path):
    from eval.authoring import compile_authoring
    from eval.contracts import DatasetError
    path = tmp_path / "author.json"; author(path)
    output = tmp_path / "same.json"
    with pytest.raises(DatasetError):
        compile_authoring(path, cases_output=output, catalog_output=output, audit_output=tmp_path / "audit.json")
    assert not output.exists() and not (tmp_path / "audit.json").exists()
