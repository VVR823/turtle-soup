"""Fixed actual old CLI, complete repeat bodies and byte-bound offline identity."""
import json
import subprocess
import sys
import time
from pathlib import Path

import pytest
from eval.contracts import DatasetError
from .test_eval_cli import command, input_file


def test_fixed_old_spec_binds_archived_engine_not_the_current_host():
    # Merely renaming new system must fail: both source and prompt must differ.
    from eval.run_cli import _fixed_system_spec
    from eval.frozen_old_driver import frozen_old_system_spec
    old = _fixed_system_spec("frozen_old", "不是")
    assert old.engineVersion == "host-ts01-frozen-v1"
    assert old == frozen_old_system_spec("不是")
    pure = _fixed_system_spec("pure_llm", "不是")
    new = _fixed_system_spec("new_system", "不是")
    assert len({s.implementationDigest for s in (old, pure, new)}) == 3
    assert old.promptDigest != new.promptDigest
    assert all(s.budget == old.budget and s.modelId == old.modelId and s.providerId == "fake"
        and s.adapterId == old.adapterId and s.seed == old.seed for s in (pure, new))


def test_fixed_factory_executes_actual_old_host_with_owned_fake(tmp_path, catalog):
    # A placeholder UnavailableOldDriver or renamed modern host cannot satisfy this.
    from eval.run_cli import _fixed_system_spec, _offline_driver
    from eval.frozen_old_driver import FrozenOldDriver
    from eval.run_contracts import EvaluationInput
    try:
        driver = _offline_driver("frozen_old", data_dir=tmp_path, answer="不是")
    except DatasetError:
        pytest.fail("Explicit actual old factory choice is missing")
    assert isinstance(driver, FrozenOldDriver)
    try:
        puzzle = catalog[0]
        input = EvaluationInput(caseId="00000000-0000-0000-0000-000000000001", soupId=puzzle.soupId,
            puzzleVersion=puzzle.puzzleVersion, puzzle=puzzle, question="灯已经灭了吗？", history=(),
            system=_fixed_system_spec("frozen_old", "不是"))
        outcome = driver.decide(input, deadline=time.monotonic()+5)
        assert outcome.host is not None and outcome.host.source == "legacy" and outcome.host.answer == "不是"
        assert outcome.modelAttemptCount == 1 and outcome.cleanupComplete
    finally:
        assert driver.close() and driver.modules.closed


def test_three_actual_cli_systems_keep_all_nine_runs_and_full_scope(tmp_path, reviewed, catalog, capsys):
    # Missing old choice, best-repeat filtering, source substitution or lost rows must fail.
    from eval.run_cli import main, read_run_bundle
    from eval.comparison import ComparisonReport, verify_comparison_report
    dataset = input_file(tmp_path, reviewed, catalog)
    original = dataset.read_bytes()
    outputs = []
    bundles = []
    for name in ("pure_llm", "frozen_old", "new_system"):
        output = tmp_path / (name + "-three.json")
        assert main(command(dataset, output, name=name, repeat=3)) == 0
        status = json.loads(capsys.readouterr().out)
        assert status["runCount"] == 3 and status["inputCount"] == 3
        assert "expectedLabel" not in status and "casesJson" not in status
        bundle = read_run_bundle(output)
        assert [r.manifest.repeatIndex for r in bundle.reports] == [0, 1, 2]
        assert all(r.metrics.total == len(r.records) == 3 and r.complete for r in bundle.reports)
        if name == "frozen_old":
            assert all(r.manifest.system.engineVersion == "host-ts01-frozen-v1" for r in bundle.reports)
            assert all(row.source == "legacy" and row.modelAttemptCount == 1
                and row.usageStatus == "unknown" for r in bundle.reports for row in r.records)
        outputs.append(output)
        bundles.append(bundle)
    output = tmp_path / "all-nine-comparison.json"
    assert main(["compare", "--input", *map(str, outputs), "--output", str(output)]) == 0
    result = verify_comparison_report(ComparisonReport.model_validate_json(output.read_bytes()))
    assert len(result.reports) == 9 and sum(len(r.records) for r in result.reports) == 27
    assert result.complete and not result.missingRuns and not result.incompleteRuns
    assert result.qualityConclusion is None and all(len(s.perRun) == 3 for s in result.statistics)
    assert set(result.reportDigests) == {r.reportDigest for b in bundles for r in b.reports}
    assert dataset.read_bytes() == original
    assert json.loads(capsys.readouterr().out)["runCount"] == 9


def test_old_actual_module_entrypoint_uses_fixed_driver(tmp_path, reviewed, catalog):
    from eval.run_cli import read_run_bundle
    dataset = input_file(tmp_path, reviewed, catalog)
    output = tmp_path / "actual-old-module.json"
    process = subprocess.run([sys.executable, "-m", "eval.run_cli", *command(dataset, output,
        name="frozen_old", repeat=1)], cwd=Path(__file__).resolve().parents[2],
        capture_output=True, text=True, timeout=60)
    assert process.returncode == 0 and not process.stderr
    assert json.loads(process.stdout)["status"] == "ready"
    bundle = read_run_bundle(output)
    assert len(bundle.reports) == 1 and bundle.reports[0].manifest.system.engineVersion == "host-ts01-frozen-v1"


@pytest.mark.parametrize("source", ["frozen_old_driver.py", "frozen_old_sources.py", "frozen_ts01_sources/source-manifest.json"])
def test_old_actual_bridge_dependencies_change_fingerprint_without_writing(source, monkeypatch):
    # Omitting any actual loader/bridge/manifest dependency creates false provenance.
    import eval.frozen_old_driver as old
    before = old.frozen_old_system_spec("不是")
    original = old._read_copy
    hits = []
    def changed_read(path):
        content = original(path)
        if path.as_posix().endswith("/" + source):
            hits.append(source)
            return content + b"\n# synthetic source mutation; not written\n"
        return content
    monkeypatch.setattr(old, "_read_copy", changed_read)
    after = old.frozen_old_system_spec("不是")
    assert hits and after.implementationDigest != before.implementationDigest


def test_changed_raw_source_refuses_cli_before_driver_without_private_output(tmp_path, reviewed, catalog, capsys, monkeypatch):
    # A byte-changed archive cannot borrow the original successful fingerprint.
    import eval.frozen_old_sources as source
    import eval.run_cli as cli
    original = source._read_copy
    def changed_read(path):
        content = original(path)
        return content + b"PRIVATE-SYNTHETIC-RAW" if path.name == "ai_host.py.raw" else content
    monkeypatch.setattr(source, "_read_copy", changed_read)
    monkeypatch.setattr(cli, "_offline_driver", lambda *a, **kw: pytest.fail("Bad archive reached driver"))
    dataset = input_file(tmp_path, reviewed, catalog)
    output = tmp_path / "never-written.json"
    assert cli.main(command(dataset, output, name="frozen_old", repeat=1)) == 1
    captured = capsys.readouterr()
    assert json.loads(captured.out)["code"] == "eval_frozen_source_invalid" and not captured.err
    assert "PRIVATE-SYNTHETIC" not in captured.out and not output.exists()


@pytest.mark.parametrize("flag", ["--module", "--legacy-dir", "--provider", "--adapter", "--holdout", "--only"])
def test_old_choice_does_not_open_dynamic_or_paid_options(tmp_path, reviewed, catalog, capsys, monkeypatch, flag):
    # Post-implementation correct controls: old choice may not weaken the shared parser.
    import eval.run_cli as cli
    dataset = input_file(tmp_path, reviewed, catalog)
    output = tmp_path / "forbidden-old-option.json"
    monkeypatch.setattr(cli, "_offline_driver", lambda *a, **kw: pytest.fail("Forbidden option reached driver"))
    assert cli.main(command(dataset, output, name="frozen_old", repeat=1) + [flag, "PRIVATE-SYNTHETIC-OPTION"]) == 1
    captured = capsys.readouterr()
    assert json.loads(captured.out)["code"] == "eval_cli_arguments_invalid"
    assert not captured.err and "PRIVATE-SYNTHETIC" not in captured.out and not output.exists()


def test_old_choice_cannot_overwrite_an_existing_report(tmp_path, reviewed, catalog, capsys, monkeypatch):
    import eval.run_cli as cli
    dataset = input_file(tmp_path, reviewed, catalog)
    output = tmp_path / "existing-old-report.json"
    output.write_bytes(b"original-synthetic-report")
    before = dataset.read_bytes()
    monkeypatch.setattr(cli, "_offline_driver", lambda *a, **kw: pytest.fail("Existing output reached driver"))
    assert cli.main(command(dataset, output, name="frozen_old", repeat=1)) == 1
    assert json.loads(capsys.readouterr().out)["code"] == "dataset_output_exists"
    assert output.read_bytes() == b"original-synthetic-report" and dataset.read_bytes() == before
