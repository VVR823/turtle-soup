"""Full private snapshot proof; changing a field cannot reuse a seal."""
import json
from pathlib import Path

import pytest

from .test_dataset_grouping import sources
from .test_dataset_inventory import audited, request110


def checked110(catalog):
    from eval.contracts import ExpectedLabel, ReviewRecord, case_digest, review_context_digest
    from eval.drafts import build_pending_draft
    request = request110(catalog)
    cases = build_pending_draft(request); reviewed = []
    for case in cases:
        receipt = ReviewRecord(operatorId="synthetic-test-only", reviewedAt="2026-10-09T00:00:00Z",
            caseDigest=case_digest(case), expectedLabel=ExpectedLabel(kind="answer", answer="是"),
            factIds=case.proposedFactIds, reviewNote="Synthetic pipeline fixture, not an actual human label.", humanConfirmed=True)
        reviewed.append(case.model_copy(update={"reviewState": "reviewed", "review": receipt}))
    rows = tuple(reviewed)
    rows = tuple(c.model_copy(update={"review": c.review.model_copy(update={
        "contextDigest": review_context_digest(c, rows)})}) if c.caseType == "context" else c for c in rows)
    return rows, request.catalog


def freeze(cases, catalog, **options):
    from eval.manifest import freeze_dataset
    return freeze_dataset(cases, catalog=catalog, audit=options.pop("audit", audited(cases)),
        source_digests=options.pop("source_digests", sources(cases)), frozen_at="2026-10-09T00:00:00Z", **options)


def test_full_reviewed_synthetic_snapshot_roundtrip_keeps_all_110_inputs(catalog, tmp_path):
    from eval.manifest import read_snapshot, verify_frozen_dataset, write_new_snapshot
    cases, puzzles = checked110(catalog); snapshot = freeze(cases, puzzles)
    assert snapshot.manifest.inputCount == snapshot.manifest.eligibleCount == 110
    assert snapshot.manifest.inputCaseIds == tuple(sorted(c.caseId for c in cases))
    assert len(json.loads(snapshot.casesJson)) == 110 and snapshot.manifest.splitRole == "holdout"
    assert verify_frozen_dataset(snapshot) == snapshot
    path = tmp_path / "new-private.json"; write_new_snapshot(snapshot, output=path)
    assert read_snapshot(path) == snapshot


@pytest.mark.parametrize("problem", ["pending", "ambiguous", "stale-review", "unknown-fact", "audit-unavailable", "omitted-input", "source-swap"])
def test_invalid_or_omitted_designated_inputs_cannot_be_frozen(catalog, problem):
    from eval.contracts import DatasetError
    cases, puzzles = checked110(catalog); proof = audited(cases); source = sources(cases)
    if problem in {"pending", "ambiguous"}:
        cases = (cases[0].model_copy(update={"reviewState": problem, "review": None}),) + cases[1:]
    elif problem == "stale-review": cases = (cases[0].model_copy(update={"question": "Changed question?"}),) + cases[1:]
    elif problem == "unknown-fact":
        receipt = cases[0].review.model_copy(update={"factIds": ("f1:" + "b" * 64,)})
        cases = (cases[0].model_copy(update={"review": receipt}),) + cases[1:]
    elif problem == "audit-unavailable": proof = audited(cases, source_complete=False)
    elif problem == "omitted-input": cases = cases[1:]
    else: source = (source[0].model_copy(update={"sourceDigest": "b" * 64}),) + source[1:]
    if problem in {"pending", "ambiguous", "stale-review", "unknown-fact"}:
        proof = audited(cases)  # Exercise the review/fact gate, not only an old audit hash.
    with pytest.raises(DatasetError) as error: freeze(cases, puzzles, audit=proof, source_digests=source)
    expected = {"pending": "dataset_review_required", "ambiguous": "dataset_review_required",
        "stale-review": "dataset_review_stale", "unknown-fact": "dataset_fact_mismatch"}
    if problem in expected: assert error.value.code == expected[problem]


@pytest.mark.parametrize("field,value", [("complete", True), ("inputCount", 109), ("splitRole", "dev"),
    ("casesDigest", "b" * 64), ("datasetDigest", "c" * 64), ("normalizationVersion", "other")])
def test_manifest_model_copy_cannot_bypass_verification(catalog, field, value):
    from eval.contracts import DatasetError
    from eval.manifest import verify_frozen_dataset
    cases, puzzles = checked110(catalog); original = freeze(cases, puzzles)
    if field == "complete": value = False
    changed = original.model_copy(update={"manifest": original.manifest.model_copy(update={field: value})})
    with pytest.raises(DatasetError): verify_frozen_dataset(changed)


@pytest.mark.parametrize("blob", ["casesJson", "catalogJson", "groupAuditJson"])
def test_body_blob_swap_or_duplicate_json_cannot_reuse_manifest(catalog, blob):
    from eval.contracts import DatasetError
    from eval.manifest import verify_frozen_dataset
    cases, puzzles = checked110(catalog); original = freeze(cases, puzzles)
    with pytest.raises(DatasetError): verify_frozen_dataset(original.model_copy(update={blob: "[]"}))


def test_holdout_labels_never_enter_repair_loader_even_with_role_copy(catalog):
    from eval.contracts import DatasetError
    from eval.manifest import load_repair_corpus
    cases, puzzles = checked110(catalog); original = freeze(cases, puzzles)
    with pytest.raises(DatasetError): load_repair_corpus(original)
    with pytest.raises(DatasetError):
        load_repair_corpus(original.model_copy(update={"manifest": original.manifest.model_copy(update={"splitRole": "regression"})}))


def test_small_dev_snapshot_is_explicit_repair_only_not_formal_quality(catalog, reviewed):
    from eval.contracts import case_digest
    from eval.grouping import audit_groups
    from eval.manifest import freeze_regression, load_repair_corpus
    c = reviewed.model_copy(update={"split": "regression"})
    c = c.model_copy(update={"review": c.review.model_copy(update={"caseDigest": case_digest(c)})})
    proof = audit_groups((), repair_cases=(c,), source_digests=sources((c,)), source_complete=True)
    snap = freeze_regression((c,), catalog=catalog, audit=proof, source_digests=sources((c,)), frozen_at="2026-10-09T00:00:00Z")
    assert load_repair_corpus(snap) == (c,) and snap.manifest.splitRole == "regression"
    assert snap.manifest.inventory.deficits.single == 60


def test_new_output_never_overwrites_existing_report(catalog, tmp_path):
    from eval.contracts import DatasetError
    from eval.manifest import write_new_snapshot
    cases, puzzles = checked110(catalog); snap = freeze(cases, puzzles)
    path = tmp_path / "existing.json"; path.write_bytes(b"owned original report")
    with pytest.raises(DatasetError): write_new_snapshot(snap, output=path)
    assert path.read_bytes() == b"owned original report"


@pytest.mark.parametrize("name", ["relative", "runtime", "env", "alias"])
def test_snapshot_io_refuses_implicit_runtime_configuration_and_aliases(catalog, tmp_path, name):
    from eval.contracts import DatasetError
    from eval.manifest import write_new_snapshot
    cases, puzzles = checked110(catalog); snap = freeze(cases, puzzles)
    path = tmp_path / "new.json"
    if name == "relative": path = Path("new.json")
    if name == "runtime": path = Path(__file__).resolve().parents[3] / "backend" / "data" / "never-write.json"
    if name == "env": path = tmp_path / ".env.snapshot"
    if name == "alias": path = tmp_path / "child" / ".." / "new.json"
    with pytest.raises(DatasetError): write_new_snapshot(snap, output=path)


def test_pending_case_bundle_can_be_inventoried_without_frozen_manifest(catalog, tmp_path):
    from eval.drafts import build_pending_draft
    from eval.manifest import CaseBundle, read_case_bundle, write_new_case_bundle
    cases = build_pending_draft(request110(catalog))
    bundle = CaseBundle(cases=cases, sourceDigests=sources(cases), issues=())
    path = tmp_path / "pending.json"; write_new_case_bundle(bundle, output=path)
    actual = read_case_bundle(path)
    assert actual == bundle and all(c.review is None for c in actual.cases)
    assert "manifest" not in actual.model_dump(mode="json")


def test_corrupt_and_oversized_inputs_never_expose_raw_traceback(tmp_path):
    from eval.contracts import DatasetError
    from eval.manifest import read_case_bundle, read_snapshot
    path = tmp_path / "corrupt.json"; path.write_text('{"private":"synthetic-secret",broken}', encoding="utf-8")
    for loader in (read_case_bundle, read_snapshot):
        with pytest.raises(DatasetError) as error: loader(path)
        assert "synthetic-secret" not in str(error.value)
    path = tmp_path / "large.json"
    with path.open("wb") as stream: stream.truncate(100 * 1024 * 1024 + 1)
    with pytest.raises(DatasetError): read_case_bundle(path)


def test_write_failure_retains_new_partial_artifact_and_original_report(catalog, tmp_path, monkeypatch):
    from eval.contracts import DatasetError
    from eval.manifest import read_snapshot, write_new_snapshot
    cases, puzzles = checked110(catalog); snap = freeze(cases, puzzles)
    path = tmp_path / "partial.json"; original = tmp_path / "original.json"; original.write_bytes(b"original")
    real_open = Path.open
    class FailingWriter:
        def __init__(self, handle): self.handle = handle
        def __enter__(self): return self
        def __exit__(self, *args): self.handle.close()
        def write(self, raw):
            self.handle.write(raw[:9]); self.handle.flush()
            raise OSError("synthetic-private-error")
    def opening(self, *args, **kwargs):
        handle = real_open(self, *args, **kwargs)
        return FailingWriter(handle) if self == path and args and args[0] == "xb" else handle
    monkeypatch.setattr(Path, "open", opening)
    with pytest.raises(DatasetError) as error: write_new_snapshot(snap, output=path)
    assert error.value.code == "dataset_output_failed" and "synthetic-private-error" not in str(error.value)
    assert original.read_bytes() == b"original" and len(path.read_bytes()) == 9
    with pytest.raises(DatasetError): read_snapshot(path)


def test_group_claim_cannot_hide_intrinsic_duplicate_or_old_reference(catalog):
    from app.baselines import digest
    from eval.contracts import DatasetError
    from eval.manifest import freeze_dataset
    from eval.grouping import audit_groups
    cases, puzzles = checked110(catalog)
    old = cases[0].model_copy(update={"split": "regression", "caseId": "00000000-0000-4000-8000-000000000111"})
    source = sources(cases + (old,))
    proof = audit_groups(cases, repair_cases=(old,), source_digests=source, source_complete=True)
    body = {"quarantineCaseIds": (), "groups": tuple(g.model_copy(update={"contaminationCauses": ()}) for g in proof.groups)}
    wire = proof.model_copy(update=body).model_dump(mode="json", exclude={"auditDigest"})
    altered = proof.model_copy(update={**body, "auditDigest": digest(wire)})
    with pytest.raises(DatasetError):
        freeze_dataset(cases, catalog=puzzles, audit=altered, source_digests=source, frozen_at="2026-10-09T00:00:00Z")


def test_duplicate_nested_case_json_is_rejected_even_with_valid_outer_bundle(catalog, tmp_path):
    from eval.contracts import DatasetError
    from eval.drafts import build_pending_draft
    from eval.manifest import CaseBundle, read_case_bundle
    cases = build_pending_draft(request110(catalog))
    bundle = CaseBundle(cases=cases, sourceDigests=sources(cases), issues=())
    raw = bundle.model_dump_json(); first = cases[0].model_dump_json()
    assert first in raw
    path = tmp_path / "duplicate.json"; path.write_text(raw.replace(first, first[:-1] + ',"question":"extra"}', 1), encoding="utf-8")
    with pytest.raises(DatasetError): read_case_bundle(path)


def test_smaller_designated_input_with_fresh_audit_still_cannot_claim_target(catalog):
    from eval.contracts import DatasetError
    cases, puzzles = checked110(catalog)
    with pytest.raises(DatasetError) as error: freeze(cases[1:], puzzles)
    assert error.value.code == "dataset_target_incomplete"


@pytest.mark.parametrize("mixed", ["role", "visibility"])
def test_repair_snapshot_refuses_mixed_roles_or_public_private_rows(catalog, reviewed, mixed):
    from eval.contracts import DatasetError, case_digest
    from eval.grouping import audit_groups
    from eval.manifest import freeze_regression
    a = reviewed.model_copy(update={"split": "regression"})
    b = a.model_copy(update={"caseId": "00000000-0000-4000-8000-000000000123", "question": "Another synthetic question?",
        **({"split": "dev"} if mixed == "role" else {"visibility": "public_authorized"})})
    cases = tuple(c.model_copy(update={"review": c.review.model_copy(update={"caseDigest": case_digest(c)})}) for c in (a, b))
    proof = audit_groups((), repair_cases=cases, source_digests=sources(cases), source_complete=True)
    with pytest.raises(DatasetError) as error:
        freeze_regression(cases, catalog=catalog, audit=proof, source_digests=sources(cases), frozen_at="2026-10-09T00:00:00Z")
    assert error.value.code == ("dataset_repair_role_invalid" if mixed == "role" else "dataset_visibility_mixed")
