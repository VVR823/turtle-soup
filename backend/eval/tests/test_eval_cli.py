"""Fixed offline entrypoints, private full-repeat bundles and no legacy defaults."""
import ast
import json
import subprocess
import sys
from pathlib import Path

import pytest

from .support import small_snapshot

BACKEND = Path(__file__).resolve().parents[2]
LEGACY = BACKEND / "app" / "scripts" / "eval_host_accuracy.py"


def require_retired_legacy():
    tree = ast.parse(LEGACY.read_text(encoding="utf-8"))
    modules = set()
    for node in tree.body:
        if isinstance(node, ast.Import): modules.update(item.name.split(".")[0] for item in node.names)
        if isinstance(node, ast.ImportFrom): modules.add((node.module or "").split(".")[0])
    assert modules <= {"sys", "pathlib"}, "Unsafe old entrypoint must not be executed before retirement"
    assert not any(isinstance(n, ast.FunctionDef) and n.name in {"extract_actual", "parse_file", "judge"} for n in tree.body)


def input_file(tmp_path, reviewed, catalog):
    from eval.manifest import write_new_snapshot
    path = tmp_path / "owned-private-regression.json"
    write_new_snapshot(small_snapshot(reviewed, catalog, groups=1, standalone=False), output=path)
    return path


def command(dataset, output, *, name="pure_llm", repeat=2):
    return ["run", "--dataset", str(dataset), "--output", str(output), "--system", name,
        "--repeat", str(repeat), "--fake-answer", "不是"]


def test_legacy_ast_has_no_runtime_top_imports_or_default_parser():
    require_retired_legacy()


@pytest.mark.parametrize("args", [[], ["run"], ["wrong"], ["--only", "synthetic-private-arg"],
    ["run", "--dataset", "synthetic-private-arg", "--provider", "paid"]])
def test_argument_failures_do_not_echo_private_argv(args, capsys):
    from eval.run_cli import main
    assert main(args) == 1
    captured = capsys.readouterr()
    assert json.loads(captured.out)["status"] == "refused" and not captured.err
    assert "synthetic-private-arg" not in captured.out


def test_fixed_fake_run_writes_every_repeat_without_gold_in_stdout(tmp_path, reviewed, catalog, capsys):
    from eval.run_cli import main, read_run_bundle
    dataset = input_file(tmp_path, reviewed, catalog); original = dataset.read_bytes()
    output = tmp_path / "all-repeats.json"
    assert main(command(dataset, output)) == 0
    status = json.loads(capsys.readouterr().out)
    bundle = read_run_bundle(output)
    assert len(bundle.reports) == status["runCount"] == 2 and status["inputCount"] == 3
    assert [r.manifest.repeatIndex for r in bundle.reports] == [0, 1]
    assert all(r.metrics.total == 3 and r.metrics.correct == 0 and r.complete for r in bundle.reports)
    assert all(r.manifest.system.executionEvidence == "synthetic_fixture" for r in bundle.reports)
    assert all(r.metrics.usage.totalTokens.knownSum is None for r in bundle.reports)
    assert all(len(r.manifest.system.implementationDigest) == 64 and len(r.manifest.system.promptDigest) == 64 for r in bundle.reports)
    assert "casesJson" not in status and "expectedLabel" not in status and dataset.read_bytes() == original


@pytest.mark.parametrize("problem", ["existing", "relative", "runtime", "alias", "env", "input-overlap", "corrupt", "role"])
def test_unsafe_or_corrupt_paths_preserve_original_and_refuse_before_driver(tmp_path, reviewed, catalog, capsys, monkeypatch, problem):
    import eval.run_cli as module
    dataset = input_file(tmp_path, reviewed, catalog); output = tmp_path / "output.json"
    if problem == "existing": output.write_bytes(b"original")
    if problem == "relative": output = Path("new.json")
    if problem == "runtime": output = BACKEND / "data" / "never-write.json"
    if problem == "alias": output = tmp_path / "child" / ".." / "new.json"
    if problem == "env": output = tmp_path / ".env.report"
    if problem == "input-overlap": output = dataset
    if problem == "corrupt": dataset.write_text('{"private":"synthetic-private-corruption",broken}', encoding="utf-8")
    def forbidden_factory(*args, **kwargs): pytest.fail("Invalid input must be refused before model construction")
    monkeypatch.setattr(module, "_offline_driver", forbidden_factory)
    args = command(dataset, output) + (["--role", "holdout"] if problem == "role" else [])
    before = dataset.read_bytes()
    assert module.main(args) == 1
    captured = capsys.readouterr()
    assert json.loads(captured.out)["status"] == "refused" and not captured.err
    assert "synthetic-private-corruption" not in captured.out and dataset.read_bytes() == before
    if problem == "existing": assert output.read_bytes() == b"original"


@pytest.mark.parametrize("flag", ["--provider", "--module", "--adapter", "--only", "--max-per-soup", "--test-dir"])
def test_dynamic_and_legacy_or_paid_options_are_refused(tmp_path, reviewed, catalog, capsys, flag):
    from eval.run_cli import main
    dataset = input_file(tmp_path, reviewed, catalog); output = tmp_path / "output.json"
    assert main(command(dataset, output) + [flag, "synthetic-private-arg"]) == 1
    assert not output.exists() and "synthetic-private-arg" not in capsys.readouterr().out


def test_comparison_cli_keeps_all_two_system_repeats_and_reports_missing_old(tmp_path, reviewed, catalog, capsys):
    from eval.run_cli import main
    from eval.comparison import ComparisonReport, verify_comparison_report
    dataset = input_file(tmp_path, reviewed, catalog)
    pure, new = tmp_path / "pure.json", tmp_path / "new.json"
    assert main(command(dataset, pure)) == 0
    assert main(command(dataset, new, name="new_system")) == 0
    capsys.readouterr()
    output = tmp_path / "comparison.json"
    assert main(["compare", "--input", str(pure), str(new), "--output", str(output)]) == 2
    result = verify_comparison_report(ComparisonReport.model_validate_json(output.read_bytes()))
    assert len(result.reports) == 4 and len(result.missingRuns) == 2 and not result.complete
    assert result.qualityConclusion is None and json.loads(capsys.readouterr().out)["status"] == "incomplete"


def test_bundle_cannot_drop_the_last_repeat(tmp_path, reviewed, catalog, capsys):
    from eval.run_cli import main, RunBundle, verify_run_bundle, read_run_bundle
    from eval.contracts import DatasetError
    dataset = input_file(tmp_path, reviewed, catalog); output = tmp_path / "three.json"
    assert main(command(dataset, output, repeat=3)) == 0
    capsys.readouterr()
    bundle = read_run_bundle(output)
    assert len(bundle.reports) == 3
    with pytest.raises(DatasetError): verify_run_bundle(RunBundle(reports=bundle.reports[:-1]))


@pytest.mark.parametrize("module_name", ["eval.run_cli", "app.scripts.eval_host_accuracy"])
def test_module_entrypoint_actual_roundtrip_without_old_defaults(tmp_path, reviewed, catalog, module_name):
    if module_name.startswith("app."): require_retired_legacy()
    dataset = input_file(tmp_path, reviewed, catalog); output = tmp_path / "module-run.json"
    process = subprocess.run([sys.executable, "-m", module_name, *command(dataset, output, repeat=1)],
        cwd=BACKEND, capture_output=True, text=True, timeout=20)
    assert process.returncode == 0 and json.loads(process.stdout)["runCount"] == 1 and not process.stderr


def test_legacy_import_is_inert_in_cold_process():
    require_retired_legacy()
    script = """import os, sys, json
before_modules = set(sys.modules)
before_env = dict(os.environ)
import app.scripts.eval_host_accuracy
assert dict(os.environ) == before_env
assert not (set(sys.modules) - before_modules) & {'app.db', 'app.ai_host', 'app.runtime', 'app.main', 'app.config', 'eval.run_cli'}
print(json.dumps({'inert': True}))
"""
    process = subprocess.run([sys.executable, "-c", script], cwd=BACKEND, capture_output=True, text=True, timeout=15)
    assert process.returncode == 0 and json.loads(process.stdout)["inert"] and not process.stderr


def test_direct_legacy_script_uses_same_safe_cli(tmp_path, reviewed, catalog):
    require_retired_legacy()
    dataset = input_file(tmp_path, reviewed, catalog); output = tmp_path / "direct-run.json"
    process = subprocess.run([sys.executable, str(LEGACY), *command(dataset, output, repeat=1)],
        cwd=tmp_path, capture_output=True, text=True, timeout=20)
    assert process.returncode == 0 and json.loads(process.stdout)["runCount"] == 1 and output.exists() and not process.stderr


@pytest.fixture
def bundle_fixture(reviewed, catalog):
    from eval.run_cli import RunBundle
    from eval.runner import run_dataset
    from .support import RecordingDriver
    from .test_run_contracts import system
    snapshot = small_snapshot(reviewed, catalog, groups=1, standalone=False)
    return RunBundle(reports=tuple(run_dataset(snapshot, system=system(), driver=RecordingDriver(),
        repeat_index=i, repeat_count=3) for i in range(3)))


@pytest.mark.parametrize("change", ["duplicate", "missing", "spec-drift", "gold-tamper"])
def test_bundle_refuses_duplicate_partial_drifting_or_self_rehashed_gold(bundle_fixture, change):
    from eval.contracts import DatasetError, ExpectedLabel
    from eval.run_cli import verify_run_bundle
    from .test_eval_comparison import reseal
    from app.baselines import digest
    from eval.metrics import compute_metrics
    reports = bundle_fixture.reports
    if change == "duplicate": reports = (reports[0], reports[0], reports[2])
    if change == "missing": reports = reports[:-1]
    if change == "spec-drift":
        spec = reports[0].manifest.system.model_dump(mode="json"); spec["seed"] = 1
        reports = (reseal(reports[0], system=spec),) + reports[1:]
    if change == "gold-tamper":
        first = reports[0]
        rows = (first.records[0].model_copy(update={"expectedLabel": ExpectedLabel(kind="answer", answer="不是")}),) + first.records[1:]
        altered = first.model_copy(update={"records": rows, "metrics": compute_metrics(rows)})
        altered = altered.model_copy(update={"reportDigest": digest(altered.model_dump(mode="json", exclude={"reportDigest"}))})
        reports = (altered,) + reports[1:]
    with pytest.raises(DatasetError): verify_run_bundle(bundle_fixture.model_copy(update={"reports": reports}))


def test_bundle_invalid_internal_copy_is_quiet_safe_refusal(bundle_fixture):
    import warnings
    from eval.contracts import DatasetError
    from eval.run_cli import verify_run_bundle
    bad = bundle_fixture.model_copy(update={"schemaVersion": "synthetic-private-schema"})
    with warnings.catch_warnings(record=True) as caught:
        warnings.simplefilter("always")
        with pytest.raises(DatasetError) as error: verify_run_bundle(bad)
    assert not caught and "synthetic-private-schema" not in str(error.value)


def test_formal_holdout_is_refused_before_constructing_fake_driver(tmp_path, reviewed, catalog, capsys, monkeypatch):
    import eval.run_cli as module
    from eval.manifest import write_new_snapshot
    from .test_dataset_manifest import checked110, freeze
    cases, puzzles = checked110(catalog)
    path = tmp_path / "synthetic-holdout.json"; write_new_snapshot(freeze(cases, puzzles), output=path)
    def forbidden(*args, **kwargs): pytest.fail("Holdout denied before driver")
    monkeypatch.setattr(module, "_offline_driver", forbidden)
    output = tmp_path / "no-holdout-run.json"
    assert module.main(command(path, output)) == 1 and not output.exists()
    assert json.loads(capsys.readouterr().out)["code"] == "eval_cli_holdout_forbidden"


@pytest.mark.parametrize("repeat", [0, 11, "true"])
def test_repeat_limits_refuse_before_file_reads(tmp_path, reviewed, catalog, capsys, repeat):
    from eval.run_cli import main
    path = tmp_path / "absent.json"; output = tmp_path / "no-run.json"
    assert main(command(path, output, repeat=repeat)) == 1 and not output.exists()
    assert json.loads(capsys.readouterr().out)["code"] == "eval_cli_arguments_invalid"


def test_abbreviated_flags_cannot_bypass_explicit_argument_allowlist(tmp_path, capsys):
    from eval.run_cli import main
    assert main(["run", "--dat", str(tmp_path / "absent.json"), "--output", str(tmp_path / "output.json"),
        "--system", "pure_llm", "--repeat", "1", "--fake-answer", "是"]) == 1
    assert json.loads(capsys.readouterr().out)["code"] == "eval_cli_arguments_invalid"


def test_incomplete_owned_run_stops_new_repeat_models_but_saves_all_planned_runs(tmp_path, reviewed, catalog, monkeypatch, capsys):
    import eval.run_cli as module
    from .support import RecordingDriver
    dataset = input_file(tmp_path, reviewed, catalog); output = tmp_path / "incomplete-series.json"
    created = []
    def unknown_cleanup(*args, **kwargs):
        driver = RecordingDriver(clean=False); created.append(driver)
        return driver
    monkeypatch.setattr(module, "_offline_driver", unknown_cleanup)
    assert module.main(command(dataset, output, repeat=3)) == 2
    bundle = module.read_run_bundle(output)
    assert len(created) == 1 and len(created[0].inputs) == 1
    assert len(bundle.reports) == 3 and all(r.metrics.total == 3 and not r.complete for r in bundle.reports)
    assert [r.metrics.notAttemptedCount for r in bundle.reports] == [2, 3, 3]
    assert json.loads(capsys.readouterr().out)["runCount"] == 3
