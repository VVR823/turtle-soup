"""Operator-only local CLI, safe status codes and exclusive private outputs."""
import json
import sys
import subprocess
from pathlib import Path

import pytest

from .test_dataset_inventory import request110
from .test_dataset_grouping import sources
from .test_dataset_manifest import checked110


def inputs(tmp_path, catalog, *, reviewed=False):
    from eval.authoring import CatalogBundle
    from eval.drafts import build_pending_draft
    from eval.grouping import audit_groups
    from eval.manifest import CaseBundle
    request = request110(catalog)
    cases, puzzles = checked110(catalog) if reviewed else (build_pending_draft(request), request.catalog)
    bundle = CaseBundle(cases=cases, sourceDigests=sources(cases), issues=())
    proof = audit_groups(cases, repair_cases=(), source_digests=bundle.sourceDigests, source_complete=reviewed)
    paths = tuple(tmp_path / name for name in ("cases.json", "catalog.json", "audit.json"))
    for path, value in zip(paths, (bundle, CatalogBundle(puzzles=puzzles), proof)):
        path.write_text(value.model_dump_json(), encoding="utf-8")
    return paths


def args(action, paths, output):
    return [action, "--input", str(paths[0]), "--catalog", str(paths[1]), "--audit", str(paths[2]), "--output", str(output)]


def test_pending_inventory_reports_110_and_needs_human_without_raw_input(tmp_path, catalog, capsys):
    from eval.cli import main
    paths = inputs(tmp_path, catalog); before = [p.read_bytes() for p in paths]
    output = tmp_path / "report.json"
    assert main(args("inventory", paths, output)) == 2
    stdout = capsys.readouterr()
    status = json.loads(stdout.out)
    assert status["status"] == "needs_human" and status["inputCount"] == 110 and status["pendingCount"] == 110
    assert "Owned synthetic question" not in stdout.out and "synthetic-test-only" not in stdout.out and not stdout.err
    assert json.loads(output.read_text(encoding="utf-8"))["inventory"]["eligibleCount"] == 0
    assert [p.read_bytes() for p in paths] == before


def test_pending_freeze_returns_two_and_report_not_formal_snapshot(tmp_path, catalog, capsys):
    from eval.cli import main
    paths = inputs(tmp_path, catalog); output = tmp_path / "needs-human.json"
    assert main(args("freeze", paths, output)) == 2
    report = json.loads(output.read_text(encoding="utf-8"))
    assert report["status"] == "needs_human" and "manifest" not in report and "casesJson" not in report
    assert json.loads(capsys.readouterr().out)["status"] == "needs_human"


def test_reviewed_synthetic_fixture_can_freeze_but_never_repair_export_holdout(tmp_path, catalog, capsys):
    from eval.cli import main
    from eval.manifest import read_snapshot
    paths = inputs(tmp_path, catalog, reviewed=True); output = tmp_path / "frozen.json"
    assert main(args("freeze", paths, output)) == 0
    assert read_snapshot(output).manifest.inputCount == 110
    capsys.readouterr()
    repair = tmp_path / "repair.json"
    assert main(["repair-export", "--input", str(output), "--output", str(repair)]) == 1
    assert not repair.exists() and "Owned synthetic question" not in capsys.readouterr().out


def test_bundle_physical_issues_cannot_be_hidden_by_clean_complete_audit(tmp_path, catalog, capsys):
    from eval.cli import main
    paths = inputs(tmp_path, catalog, reviewed=True)
    body = json.loads(paths[0].read_text(encoding="utf-8"))
    body["issues"] = [{"code": "dataset_partial_tail", "caseIds": [], "lineNumber": 1, "sourceDigest": "a" * 64}]
    paths[0].write_text(json.dumps(body), encoding="utf-8")
    output = tmp_path / "issue-report.json"
    assert main(args("freeze", paths, output)) == 2
    report = json.loads(output.read_text(encoding="utf-8"))
    assert report["sourceIssueCount"] == 1 and report["status"] == "needs_human" and "manifest" not in report


@pytest.mark.parametrize("problem", ["existing", "overlap", "relative", "runtime", "alias", "corrupt", "schema", "role-override"])
def test_cli_refuses_unsafe_inputs_outputs_and_never_overwrites(tmp_path, catalog, capsys, problem):
    from eval.cli import main
    paths = inputs(tmp_path, catalog); output = tmp_path / "output.json"
    if problem == "existing": output.write_bytes(b"original")
    if problem == "overlap": output = paths[0]
    if problem == "relative": output = Path("new.json")
    if problem == "runtime": output = Path(__file__).resolve().parents[3] / "backend" / "data" / "never-write.json"
    if problem == "alias": output = tmp_path / "child" / ".." / "new.json"
    if problem == "corrupt": paths[0].write_text('{"private":"private-secret",broken}', encoding="utf-8")
    if problem == "schema":
        raw = json.loads(paths[0].read_text(encoding="utf-8")); raw["schemaVersion"] = True
        paths[0].write_text(json.dumps(raw), encoding="utf-8")
    command = args("inventory", paths, output) + (["--role", "dev"] if problem == "role-override" else [])
    before = {p: p.read_bytes() for p in paths}
    assert main(command) == 1
    stdout = capsys.readouterr()
    assert json.loads(stdout.out)["status"] == "refused" and "private-secret" not in stdout.out and not stdout.err
    assert {p: p.read_bytes() for p in paths} == before
    if problem == "existing": assert output.read_bytes() == b"original"


@pytest.mark.parametrize("command", [[], ["inventory"], ["wrong-action"],
    ["repair-export", "--input", "private-secret", "--catalog", "private-secret", "--output", "new"]])
def test_cli_argument_errors_are_finite_safe_codes_not_raw_argv(capsys, command):
    from eval.cli import main
    assert main(command) == 1
    actual = capsys.readouterr()
    assert json.loads(actual.out)["status"] == "refused" and "private-secret" not in actual.out and not actual.err


def test_module_entrypoint_actually_runs_without_runtime_or_cloud(tmp_path, catalog):
    paths = inputs(tmp_path, catalog); output = tmp_path / "module-report.json"
    result = subprocess.run([sys.executable, "-m", "eval.cli", *args("inventory", paths, output)],
        cwd=Path(__file__).resolve().parents[2], capture_output=True, text=True, timeout=15)
    assert result.returncode == 2 and json.loads(result.stdout)["inputCount"] == 110 and not result.stderr


@pytest.mark.parametrize("field,value", [("puzzleVersion", "p1:" + "b" * 64), ("soupId", "foreign"),
    ("proposedFactIds", ("f1:" + "b" * 64,))])
def test_pending_inventory_refuses_foreign_catalog_scope_even_with_fresh_audit(tmp_path, catalog, capsys, field, value):
    from eval.cli import main
    from eval.grouping import audit_groups
    from eval.manifest import read_case_bundle, CaseBundle
    paths = inputs(tmp_path, catalog)
    original = read_case_bundle(paths[0]); cases = (original.cases[0].model_copy(update={field: value}),) + original.cases[1:]
    bundle = CaseBundle(cases=cases, sourceDigests=sources(cases), issues=())
    proof = audit_groups(cases, repair_cases=(), source_digests=bundle.sourceDigests, source_complete=False)
    paths[0].write_text(bundle.model_dump_json(), encoding="utf-8")
    paths[2].write_text(proof.model_dump_json(), encoding="utf-8")
    assert main(args("inventory", paths, tmp_path / "refuse.json")) == 1
    assert json.loads(capsys.readouterr().out)["code"] == "dataset_catalog_scope_invalid"


def test_complete_private_regression_exports_without_holdout_or_quality_claim(tmp_path, catalog, reviewed, capsys):
    from eval.cli import main
    from eval.contracts import case_digest
    from eval.grouping import audit_groups
    from eval.manifest import freeze_regression, write_new_snapshot, read_case_bundle
    case = reviewed.model_copy(update={"split": "regression"})
    case = case.model_copy(update={"review": case.review.model_copy(update={"caseDigest": case_digest(case)})})
    source = sources((case,)); proof = audit_groups((), repair_cases=(case,), source_digests=source, source_complete=True)
    snapshot = freeze_regression((case,), catalog=catalog, audit=proof, source_digests=source, frozen_at="2026-10-09T00:00:00Z")
    input_path = tmp_path / "private-regression.json"; write_new_snapshot(snapshot, output=input_path)
    output = tmp_path / "repair-corpus.json"
    assert main(["repair-export", "--input", str(input_path), "--output", str(output)]) == 0
    actual = read_case_bundle(output)
    assert actual.cases == (case,) and actual.cases[0].split == "regression"
    assert "Was the light" not in capsys.readouterr().out


@pytest.mark.parametrize("public", [False, True])
def test_public_export_flag_requires_actual_public_synthetic_origin(tmp_path, catalog, reviewed, capsys, public):
    from eval.cli import main
    from eval.contracts import case_digest
    from eval.grouping import audit_groups
    from eval.manifest import freeze_regression, write_new_snapshot, read_case_bundle
    updates = {"split": "regression"}
    if public:
        updates.update(origin="public_synthetic", authorRole="synthetic", visibility="public_authorized")
    case = reviewed.model_copy(update=updates)
    case = case.model_copy(update={"review": case.review.model_copy(update={"caseDigest": case_digest(case)})})
    source = sources((case,))
    proof = audit_groups((), repair_cases=(case,), source_digests=source, source_complete=True)
    snapshot = freeze_regression((case,), catalog=catalog, audit=proof, source_digests=source,
        frozen_at="2026-10-09T00:00:00Z")
    original = tmp_path / "demo.json"; write_new_snapshot(snapshot, output=original)
    before = original.read_bytes(); output = tmp_path / "export.json"
    command = ["repair-export", "--input", str(original), "--output", str(output)]
    if public:
        assert main(command) == 1 and not output.exists()
        assert json.loads(capsys.readouterr().out)["code"] == "dataset_public_export_confirmation_required"
    assert main(command + ["--public-synthetic"]) == (0 if public else 1)
    if public:
        assert read_case_bundle(output).cases == (case,)
    else:
        assert not output.exists()
        assert json.loads(capsys.readouterr().out)["code"] == "dataset_public_export_forbidden"
    assert original.read_bytes() == before
