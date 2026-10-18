"""Permanent refusal checks for the sole TS11 C0/I3 review, using real APIs."""
import json

import pytest

from .test_dataset_manifest import checked110, freeze
from .test_dataset_grouping import sources


@pytest.mark.parametrize("change", ["question", "answer"])
def test_prior_context_change_requires_downstream_review_again(catalog, change):
    from eval.contracts import DatasetError, ExpectedLabel, case_digest
    cases, puzzles = checked110(catalog)
    assert freeze(cases, puzzles).manifest.inputCount == 110
    first = next(c for c in cases if c.caseType == "context" and c.contextIndex == 1)
    changed = first.model_copy(update={"question": "Did the other actor switch it off?"}) if change == "question" else first
    receipt = first.review.model_copy(update={"caseDigest": case_digest(changed), **(
        {"expectedLabel": ExpectedLabel(kind="answer", answer="不是")} if change == "answer" else {})})
    changed = changed.model_copy(update={"review": receipt})
    modified = tuple(changed if c.caseId == first.caseId else c for c in cases)
    with pytest.raises(DatasetError): freeze(modified, puzzles)


@pytest.mark.parametrize("change", ["missing", "swapped"])
def test_inventory_cli_refuses_invalid_physical_bundle_provenance(tmp_path, catalog, capsys, change):
    from eval.cli import main
    from .test_dataset_cli import inputs, args
    paths = inputs(tmp_path, catalog, reviewed=True)
    body = json.loads(paths[0].read_text(encoding="utf-8"))
    if change == "missing": body["sourceDigests"] = []
    else: body["sourceDigests"][0]["sourceDigest"] = "b" * 64
    paths[0].write_text(json.dumps(body), encoding="utf-8")
    output = tmp_path / "never-ready.json"
    assert main(args("inventory", paths, output)) == 1
    assert json.loads(capsys.readouterr().out)["status"] == "refused" and not output.exists()


def test_inventory_cli_refuses_rehashed_cleared_whole_group_quarantine(tmp_path, catalog, capsys):
    from app.baselines import digest
    from eval.authoring import CatalogBundle
    from eval.cli import main
    from eval.contracts import case_digest
    from eval.grouping import audit_groups
    from eval.manifest import CaseBundle
    from .test_dataset_cli import args
    cases, puzzles = checked110(catalog)
    old = cases[0].model_copy(update={"caseId": "d0000000-0000-4000-8000-00000000ffff", "split": "regression"})
    old = old.model_copy(update={"review": old.review.model_copy(update={"caseDigest": case_digest(old)})})
    source = sources(cases + (old,))
    proof = audit_groups(cases, repair_cases=(old,), source_digests=source, source_complete=True)
    assert proof.quarantineCaseIds
    body = proof.model_dump(mode="json"); body["quarantineCaseIds"] = []
    body["auditDigest"] = digest({k: v for k, v in body.items() if k != "auditDigest"})
    paths = tuple(tmp_path / name for name in ("cases.json", "catalog.json", "audit.json"))
    paths[0].write_text(CaseBundle(cases=cases, sourceDigests=source, issues=()).model_dump_json(), encoding="utf-8")
    paths[1].write_text(CatalogBundle(puzzles=puzzles).model_dump_json(), encoding="utf-8")
    paths[2].write_text(json.dumps(body), encoding="utf-8")
    output = tmp_path / "never-ready.json"
    assert main(args("inventory", paths, output)) == 1
    assert json.loads(capsys.readouterr().out)["status"] == "refused" and not output.exists()


@pytest.mark.parametrize("problem", ["field-set", "p1", "coerced-count", "identity", "catalog-set", "origin", "parent", "overlay"])
def test_all_full_release_members_are_structurally_validated(catalog, problem):
    from app.baselines import canonical_json, digest, strict_json
    from eval.catalog import validate_catalog
    from eval.contracts import DatasetError
    puzzle = catalog[0]; snapshot = puzzle.ruleSnapshot
    rules, manifest = strict_json(snapshot.releaseRulesJson), strict_json(snapshot.releaseManifestJson)
    identity = "unused"
    rules["rulesBySoup"][identity] = dict(rules["rulesBySoup"][puzzle.soupId])
    manifest["puzzleVersions"][identity] = "p1:" + "b" * 64
    if problem == "field-set": rules["rulesBySoup"][identity] = {"badField": "invalid"}
    elif problem == "p1": manifest["puzzleVersions"][identity] = "not-a-p1"
    elif problem == "coerced-count": rules["rulesBySoup"][identity]["castCount"] = "1"
    elif problem == "identity":
        rules["rulesBySoup"][" "] = rules["rulesBySoup"].pop(identity)
        manifest["puzzleVersions"][" "] = manifest["puzzleVersions"].pop(identity)
    elif problem == "catalog-set": del manifest["puzzleVersions"][identity]
    elif problem == "origin": manifest["origin"] = None
    else:
        rules["schemaVersion"] = manifest["schemaVersion"] = 2
        rules["exactQaBySoup"] = {key: [] for key in rules["rulesBySoup"]}
        manifest.update(origin="reviewed-exact-rule", parentRuleVersion="r1:" + "c" * 64)
        if problem == "parent": manifest["parentRuleVersion"] = "not-a-r1"
        else: rules["exactQaBySoup"][identity] = [{"badField": "invalid overlay"}]
    modified = puzzle.model_copy(update={"ruleSnapshot": snapshot.model_copy(update={
        "releaseRulesJson": canonical_json(rules), "releaseManifestJson": canonical_json(manifest),
        "ruleVersion": "r1:" + digest({"rules": rules, "manifest": manifest})})})
    with pytest.raises(DatasetError): validate_catalog((modified,))


def test_valid_unused_structural_member_does_not_claim_its_full_p1_content(catalog):
    from app.baselines import canonical_json, digest, strict_json
    from eval.catalog import validate_catalog
    puzzle = catalog[0]; snapshot = puzzle.ruleSnapshot
    rules, manifest = strict_json(snapshot.releaseRulesJson), strict_json(snapshot.releaseManifestJson)
    rules["rulesBySoup"]["unused"] = rules["rulesBySoup"][puzzle.soupId]
    manifest["puzzleVersions"]["unused"] = "p1:" + "b" * 64
    modified = puzzle.model_copy(update={"ruleSnapshot": snapshot.model_copy(update={
        "releaseRulesJson": canonical_json(rules), "releaseManifestJson": canonical_json(manifest),
        "ruleVersion": "r1:" + digest({"rules": rules, "manifest": manifest})})})
    assert validate_catalog((modified,)) == (modified,)


def test_changed_prefix_can_freeze_only_after_affected_context_receipts_renewed(catalog):
    from eval.contracts import case_digest, review_context_digest
    cases, puzzles = checked110(catalog)
    first = next(c for c in cases if c.caseType == "context" and c.contextIndex == 1)
    changed = first.model_copy(update={"question": "Did a different keeper switch it off?"})
    changed = changed.model_copy(update={"review": first.review.model_copy(update={"caseDigest": case_digest(changed)})})
    rows = tuple(changed if c.caseId == first.caseId else c for c in cases)
    renewed = tuple(c.model_copy(update={"review": c.review.model_copy(update={
        "contextDigest": review_context_digest(c, rows)})}) if c.conversationId == first.conversationId else c for c in rows)
    assert freeze(renewed, puzzles).manifest.inputCount == 110
    assert [c.question for c in renewed] == [c.question for c in rows]


def test_context_receipt_without_prefix_binding_cannot_freeze_or_be_eligible(catalog):
    from eval.contracts import DatasetError
    from eval.inventory import inventory
    from .test_dataset_inventory import audited
    cases, puzzles = checked110(catalog)
    last = next(c for c in cases if c.caseType == "context" and c.contextIndex == 3)
    changed = last.model_copy(update={"review": last.review.model_copy(update={"contextDigest": None})})
    rows = tuple(changed if c.caseId == last.caseId else c for c in cases)
    counted = inventory(rows, audit=audited(rows), source_digests=sources(rows))
    assert counted.inputCount == 110 and counted.reviewedCount == 110 and counted.eligibleCount == 109
    with pytest.raises(DatasetError): freeze(rows, puzzles)


def test_honest_contamination_inventory_retains_counts_but_is_not_ready(tmp_path, catalog, capsys):
    from eval.cli import main
    from eval.authoring import CatalogBundle
    from eval.contracts import case_digest
    from eval.grouping import audit_groups
    from eval.manifest import CaseBundle
    from .test_dataset_cli import args
    cases, puzzles = checked110(catalog)
    old = cases[0].model_copy(update={"caseId": "d0000000-0000-4000-8000-00000000ffff", "split": "regression"})
    old = old.model_copy(update={"review": old.review.model_copy(update={"caseDigest": case_digest(old)})})
    source = sources(cases + (old,))
    proof = audit_groups(cases, repair_cases=(old,), source_digests=source, source_complete=True)
    paths = tuple(tmp_path / name for name in ("cases.json", "catalog.json", "audit.json"))
    for path, packet in zip(paths, (CaseBundle(cases=cases, sourceDigests=source, issues=()), CatalogBundle(puzzles=puzzles), proof)):
        path.write_text(packet.model_dump_json(), encoding="utf-8")
    output = tmp_path / "honest-report.json"
    assert main(args("inventory", paths, output)) == 2
    report = json.loads(output.read_text(encoding="utf-8"))
    assert report["inventory"]["inputCount"] == 110 and report["inventory"]["quarantineCount"] == 1
    assert report["inventory"]["eligibleCount"] == 109 and json.loads(capsys.readouterr().out)["status"] == "needs_human"
