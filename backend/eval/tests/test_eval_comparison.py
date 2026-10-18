"""Full synthetic cohorts; statistics cannot select the best repeat or drop failures."""
import math

import pytest

from .support import RecordingDriver, small_snapshot
from .test_run_contracts import system


@pytest.fixture
def runs(reviewed, catalog):
    from eval.runner import run_dataset
    snapshot = small_snapshot(reviewed, catalog, groups=1, standalone=False)
    scripts = {"pure_llm": (("是", "不是", "不是"), ("不是",) * 3, ("是",) * 3),
        "frozen_old": (("是",) * 3, ("是", "是", "不是"), ("是", "不是", "不是")),
        "new_system": (("是",) * 3, ("是", "不是", "不是"), ("是", "error", "error"))}
    return tuple(run_dataset(snapshot, system=system().model_copy(update={"name": name}),
        driver=RecordingDriver(outputs), repeat_index=repeat, repeat_count=3)
        for name, series in scripts.items() for repeat, outputs in enumerate(series))


def compare(reports):
    from eval.comparison import compare_runs
    return compare_runs(reports)


def reseal(report, **manifest_changes):
    from app.baselines import canonical_json, digest
    from eval.run_contracts import RunManifest, seal_run_report
    body = report.manifest.model_dump(mode="json", exclude={"manifestDigest"})
    body.update(manifest_changes)
    manifest = RunManifest.model_validate_json(canonical_json({**body, "manifestDigest": digest(body)}))
    return seal_run_report(report.datasetProof, manifest, report.records, report.complete)


def test_all_nine_whole_reports_and_manual_statistics_are_retained(runs):
    result = compare(runs)
    assert result.reports == runs and result.reportDigests == tuple(r.reportDigest for r in runs)
    assert result.complete and result.missingRuns == () and result.incompleteRuns == ()
    assert result.qualityConclusion is None
    new = next(s for s in result.statistics if s.systemName == "new_system")
    assert len(new.perRun) == 3 and new.perRun[2].metrics.errorCount == 2
    accuracy = next(m for m in new.moments if m.metric == "accuracy")
    assert accuracy.knownCount == 3 and accuracy.unknownCount == 0
    assert accuracy.min == pytest.approx(1 / 3) and accuracy.max == 1
    assert accuracy.mean == pytest.approx(5 / 9) and accuracy.populationStddev == pytest.approx(math.sqrt(8 / 81))
    assert sum(r.metrics.total for r in result.reports) == 27


def test_deltas_keep_positive_negative_and_zero_instead_of_best_seed(runs):
    deltas = compare(runs).deltas
    assert len(deltas) == 6
    pure = sorted((d for d in deltas if d.baselineSystem == "pure_llm"), key=lambda d: d.repeatIndex)
    old = sorted((d for d in deltas if d.baselineSystem == "frozen_old"), key=lambda d: d.repeatIndex)
    assert [d.accuracy for d in pure] == pytest.approx([2 / 3, 1 / 3, -2 / 3])
    assert [d.accuracy for d in old] == pytest.approx([0, -1 / 3, 0])
    assert all(d.reason is None for d in deltas)


def test_unknown_run_tokens_are_not_treated_as_full_zero_usage(runs):
    result = compare(runs)
    new = next(s for s in result.statistics if s.systemName == "new_system")
    tokens = next(m for m in new.moments if m.metric == "totalTokens")
    assert tokens.knownCount == 2 and tokens.unknownCount == 1
    assert new.perRun[2].metrics.usage.totalTokens.unknownCount == 2
    assert tokens.mean == 0  # Only the two explicitly zero-call runs; not all three.


@pytest.mark.parametrize("drop", ["one", "whole-repeat", "whole-system"])
def test_missing_reports_are_detected_from_declared_repeat_count(runs, drop):
    kept = tuple(r for r in runs if not (r.manifest.repeatIndex == 2 if drop == "whole-repeat"
        else r.manifest.system.name == "frozen_old" if drop == "whole-system"
        else r.manifest.system.name == "new_system" and r.manifest.repeatIndex == 2))
    result = compare(kept)
    assert not result.complete and result.reports == kept
    assert len(result.missingRuns) == (1 if drop == "one" else 3)
    assert result.incompleteRuns == () and result.qualityConclusion is None


@pytest.mark.parametrize("field,value", [("seed", 1), ("providerId", "different-fake"), ("modelId", "different-model"),
    ("adapterId", "different-adapter"), ("executionEvidence", "offline_engine"),
    ("implementationDigest", "c" * 64), ("promptDigest", "d" * 64), ("engineVersion", "other-engine")])
def test_shared_scope_or_same_system_repeat_drift_is_refused(runs, field, value):
    from eval.contracts import DatasetError
    selected = runs[0]
    spec = selected.manifest.system.model_dump(mode="json"); spec[field] = value
    if field == "engineVersion":
        # Nonerror records bind the engine too; preserve that positive report proof.
        from eval.run_contracts import seal_run_report, RunManifest
        from app.baselines import canonical_json, digest
        rows = tuple(r.model_copy(update={"resultVersions": r.resultVersions.model_copy(update={"engineVersion": value})}) for r in selected.records)
        body = selected.manifest.model_dump(mode="json", exclude={"manifestDigest"}); body["system"] = spec
        manifest = RunManifest.model_validate_json(canonical_json({**body, "manifestDigest": digest(body)}))
        changed = seal_run_report(selected.datasetProof, manifest, rows, True)
    else: changed = reseal(selected, system=spec)
    with pytest.raises(DatasetError): compare((changed,) + runs[1:])


def test_different_implementations_between_systems_are_allowed(runs):
    changed = []
    for report in runs:
        spec = report.manifest.system.model_dump(mode="json")
        digit = {"pure_llm": "a", "frozen_old": "b", "new_system": "c"}[spec["name"]]
        spec.update(implementationDigest=digit * 64, promptDigest=digit * 64)
        changed.append(reseal(report, system=spec))
    assert compare(tuple(changed)).complete


@pytest.mark.parametrize("change", ["budget", "repeat-count", "run-id", "slot"])
def test_budget_and_repeat_plan_or_duplicate_run_slot_is_refused(runs, change):
    from eval.contracts import DatasetError
    selected = runs[0]
    if change == "budget":
        spec = selected.manifest.system.model_dump(mode="json"); spec["budget"]["modelAttemptsPerCase"] = 1
        changed = reseal(selected, system=spec)
        reports = (changed,) + runs[1:]
    elif change == "repeat-count": reports = (reseal(selected, repeatCount=4),) + runs[1:]
    elif change == "run-id": reports = runs + (selected,)
    else:
        reports = runs + (reseal(selected, runId="00000000-0000-0000-0000-000000000777"),)
    with pytest.raises(DatasetError): compare(reports)


def test_unavailable_old_is_preserved_as_incomplete_not_fake_quality(runs, reviewed, catalog):
    from eval.drivers import UnavailableOldDriver
    from eval.runner import run_dataset
    snapshot = small_snapshot(reviewed, catalog, groups=1, standalone=False)
    old = tuple(run_dataset(snapshot, system=system().model_copy(update={"name": "frozen_old"}),
        driver=UnavailableOldDriver(), repeat_index=i, repeat_count=3) for i in range(3))
    reports = tuple(r for r in runs if r.manifest.system.name != "frozen_old") + old
    result = compare(reports)
    assert result.reports == reports and not result.complete and not result.missingRuns
    assert len(result.incompleteRuns) == 3 and result.qualityConclusion is None
    assert all(r.metrics.notAttemptedCount == 3 for r in old)
    deltas = [d for d in result.deltas if d.baselineSystem == "frozen_old"]
    assert len(deltas) == 3 and all(d.reason == "incomplete_run" and d.accuracy is None for d in deltas)


def test_rehashed_gold_tamper_is_rejected_before_comparison(runs):
    from app.baselines import digest
    from eval.contracts import DatasetError, ExpectedLabel
    from eval.metrics import compute_metrics
    selected = runs[0]
    rows = (selected.records[0].model_copy(update={"expectedLabel": ExpectedLabel(kind="answer", answer="不是")}),) + selected.records[1:]
    changed = selected.model_copy(update={"records": rows, "metrics": compute_metrics(rows)})
    changed = changed.model_copy(update={"reportDigest": digest(changed.model_dump(mode="json", exclude={"reportDigest"}))})
    with pytest.raises(DatasetError): compare((changed,) + runs[1:])


def test_comparison_derived_metadata_cannot_be_self_rehashed_as_truth(runs):
    from app.baselines import digest
    from eval.contracts import DatasetError
    from eval.comparison import verify_comparison_report
    original = compare(runs)
    assert verify_comparison_report(original) == original
    altered = original.model_copy(update={"complete": False})
    altered = altered.model_copy(update={"comparisonDigest": digest(altered.model_dump(mode="json", exclude={"comparisonDigest"}))})
    with pytest.raises(DatasetError): verify_comparison_report(altered)


@pytest.mark.parametrize("field", ["reportDigests", "commonScopeDigest", "missingRuns", "statistics", "deltas", "reports"])
def test_rehashed_derived_metadata_or_dropped_bodies_are_refused(runs, field):
    from app.baselines import digest
    from eval.contracts import DatasetError
    from eval.comparison import MissingRun, verify_comparison_report
    original = compare(runs)
    values = {"reportDigests": tuple(reversed(original.reportDigests)), "commonScopeDigest": "f" * 64,
        "missingRuns": (MissingRun(systemName="new_system", repeatIndex=0),),
        "statistics": tuple(reversed(original.statistics)), "deltas": original.deltas[:-1], "reports": original.reports[:-1]}
    changed = original.model_copy(update={field: values[field]})
    changed = changed.model_copy(update={"comparisonDigest": digest(changed.model_dump(mode="json", exclude={"comparisonDigest"}))})
    with pytest.raises(DatasetError): verify_comparison_report(changed)


def test_illegal_internal_quality_copy_is_refused_without_private_warning(runs):
    import warnings
    from eval.contracts import DatasetError
    from eval.comparison import verify_comparison_report
    bad = compare(runs).model_copy(update={"qualityConclusion": "synthetic-private-quality-claim"})
    with warnings.catch_warnings(record=True) as caught:
        warnings.simplefilter("always")
        with pytest.raises(DatasetError) as error: verify_comparison_report(bad)
    assert not caught and "synthetic-private-quality-claim" not in str(error.value)


def test_a_different_valid_dataset_scope_cannot_join_same_cohort(runs, reviewed, catalog):
    from eval.contracts import DatasetError
    from eval.runner import run_dataset
    from eval.run_contracts import verify_run_report
    different = run_dataset(small_snapshot(reviewed, catalog, groups=2, standalone=False), system=system(),
        driver=RecordingDriver(), repeat_index=0, repeat_count=3)
    assert verify_run_report(different).metrics.total == 6
    with pytest.raises(DatasetError): compare(runs[:-1] + (different,))


@pytest.mark.parametrize("bound", ["input", "output"])
def test_combined_input_and_output_size_each_have_an_independent_bound(runs, monkeypatch, bound):
    import eval.comparison as module
    from eval.contracts import DatasetError
    size = sum(len(r.model_dump_json().encode("utf-8")) for r in runs)
    monkeypatch.setattr(module, "MAX_BYTES", size - 1 if bound == "input" else size)
    with pytest.raises(DatasetError) as error: compare(runs)
    assert error.value.code == "eval_comparison_limit"


@pytest.mark.parametrize("bad", [(), [], tuple(range(31))])
def test_empty_untyped_or_over_count_input_is_refused_before_access(bad):
    from eval.contracts import DatasetError
    with pytest.raises(DatasetError): compare(bad)
