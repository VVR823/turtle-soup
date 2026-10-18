"""Permanent sole-review regressions; synthetic cancellation/source mutations only."""
import json
import time
from concurrent.futures import Future

import pytest

from .support import RecordingDriver, ScriptedFakeModel, small_snapshot
from .test_eval_cli import command, input_file
from .test_run_contracts import system


class InterruptingDriver(RecordingDriver):
    def decide(self, input, *, deadline):
        if len(self.inputs) == 1:
            self.inputs.append(input)
            raise KeyboardInterrupt("synthetic-private-interrupt")
        return super().decide(input, deadline=deadline)


def checked_cancelled(call, *args, **kwargs):
    try:
        return call(*args, **kwargs)
    except KeyboardInterrupt:
        pytest.fail("Ordinary operator cancellation escaped without a complete planned ledger")


def interrupted(snapshot, *, repeat=0, count=1):
    from eval.runner import run_dataset
    driver = InterruptingDriver()
    report = checked_cancelled(run_dataset, snapshot, system=system(), driver=driver, repeat_index=repeat, repeat_count=count)
    assert driver.closed and len(driver.inputs) == 2
    return report


def test_cancellation_preserves_previous_current_and_remaining_cases_without_zero_guess(reviewed, catalog):
    report = interrupted(small_snapshot(reviewed, catalog, groups=1, standalone=False))
    assert not report.complete and report.metrics.total == 3 and report.metrics.errorCount == 2
    first, cancelled, pending = report.records
    assert first.actualAnswer == "不是" and first.modelAttemptCount == 0
    assert cancelled.errorCode == "cancelled" and cancelled.decisionAttempted
    assert cancelled.modelAttemptCount is None and cancelled.usageStatus == "unknown"
    assert cancelled.usage.totalTokens is None
    assert not pending.decisionAttempted and pending.modelAttemptCount == 0
    assert report.metrics.notAttemptedCount == 1


def test_cancelled_unknown_reservations_stay_unknown_in_comparison(reviewed, catalog):
    from eval.comparison import compare_runs
    report = interrupted(small_snapshot(reviewed, catalog, groups=1, standalone=False))
    compared = compare_runs((report,))
    moments = next(m for m in compared.statistics[2].moments if m.metric == "modelReservations")
    assert moments.knownCount == 0 and moments.unknownCount == 1 and moments.mean is None
    assert not compared.complete and compared.qualityConclusion is None


def test_rehashed_complete_cancelled_run_cannot_be_certified(reviewed, catalog):
    from app.baselines import digest
    from eval.contracts import DatasetError
    from eval.run_contracts import verify_run_report
    report = interrupted(small_snapshot(reviewed, catalog, groups=1, standalone=False))
    altered = report.model_copy(update={"complete": True})
    altered = altered.model_copy(update={"reportDigest": digest(altered.model_dump(mode="json", exclude={"reportDigest"}))})
    with pytest.raises(DatasetError): verify_run_report(altered)


def test_later_repeat_interrupt_preserves_earlier_reports_and_every_planned_repeat(tmp_path, reviewed, catalog, capsys, monkeypatch):
    import eval.run_cli as cli
    created = []
    def factory(*args, **kwargs):
        driver = InterruptingDriver() if len(created) == 2 else RecordingDriver()
        created.append(driver)
        return driver
    monkeypatch.setattr(cli, "_offline_driver", factory)
    output = tmp_path / "cancelled-all-repeats.json"
    assert checked_cancelled(cli.main, command(input_file(tmp_path, reviewed, catalog), output, repeat=4)) == 2
    bundle = cli.read_run_bundle(output)
    assert len(created) == 3 and all(d.closed for d in created)
    assert [r.complete for r in bundle.reports] == [True, True, False, False]
    assert [r.metrics.total for r in bundle.reports] == [3, 3, 3, 3]
    assert [r.metrics.notAttemptedCount for r in bundle.reports] == [0, 0, 1, 3]
    assert bundle.reports[2].records[1].modelAttemptCount is None
    assert all(r.actualAnswer == "不是" for run in bundle.reports[:2] for r in run.records)
    status = capsys.readouterr()
    assert json.loads(status.out)["runCount"] == 4 and not status.err
    assert "synthetic-private" not in status.out


def test_interrupt_between_repeats_stops_factories_and_persists_unattempted_repeats(tmp_path, reviewed, catalog, monkeypatch, capsys):
    import eval.run_cli as cli
    created = []
    def factory(*args, **kwargs):
        created.append(1)
        if len(created) == 2: raise KeyboardInterrupt("synthetic-private-factory")
        return RecordingDriver()
    monkeypatch.setattr(cli, "_offline_driver", factory)
    output = tmp_path / "factory-cancelled.json"
    assert checked_cancelled(cli.main, command(input_file(tmp_path, reviewed, catalog), output, repeat=3)) == 2
    bundle = cli.read_run_bundle(output)
    assert len(created) == 2 and [r.complete for r in bundle.reports] == [True, False, False]
    assert [r.metrics.notAttemptedCount for r in bundle.reports] == [0, 3, 3]
    assert all(r.modelAttemptCount == 0 for run in bundle.reports[1:] for r in run.records)
    assert not capsys.readouterr().err


def test_known_cancelled_driver_stops_even_when_cleanup_is_confirmed(reviewed, catalog):
    from eval.runner import run_dataset
    class KnownCancellation(RecordingDriver):
        def decide(self, input, *, deadline):
            outcome = super().decide(input, deadline=deadline)
            return outcome.model_copy(update={"host": None, "errorCode": "cancelled"})
    driver = KnownCancellation()
    report = checked_cancelled(run_dataset, small_snapshot(reviewed, catalog, groups=1, standalone=False),
        system=system(), driver=driver, repeat_index=0, repeat_count=1)
    assert not report.complete and len(driver.inputs) == 1 and driver.closed
    assert report.records[0].errorCode == "cancelled" and report.records[0].modelAttemptCount == 0
    assert report.metrics.notAttemptedCount == 2


def test_cancellation_during_cleanup_does_not_erase_completed_ledger(reviewed, catalog):
    from eval.runner import run_dataset
    class InterruptedClose(RecordingDriver):
        def close(self):
            self.closed = True
            raise KeyboardInterrupt("synthetic-private-close")
    driver = InterruptedClose()
    report = checked_cancelled(run_dataset, small_snapshot(reviewed, catalog, groups=1, standalone=False),
        system=system(), driver=driver, repeat_index=0, repeat_count=1)
    assert not report.complete and report.metrics.total == 3 and all(r.decisionAttempted for r in report.records)
    assert driver.closed


@pytest.mark.parametrize("name", ["pure_llm", "new_system"])
def test_actual_owned_gateway_interrupt_retains_real_reservation_observations(catalog, tmp_path, monkeypatch, name):
    from app.config import Settings
    from eval.drivers import PureLLMDriver, NewSystemDriver
    from .test_eval_drivers import request
    model = ScriptedFakeModel(("BLOCK",))
    driver = (PureLLMDriver if name == "pure_llm" else NewSystemDriver)(settings=Settings.for_test(tmp_path), fake_model=model)
    original = Future.result
    fired = []
    def interrupt(self, *args, **kwargs):
        if not fired:
            assert model.entered.wait(1)
            fired.append(True)
            model.release.set()
            raise KeyboardInterrupt("synthetic-private-owned")
        return original(self, *args, **kwargs)
    monkeypatch.setattr(Future, "result", interrupt)
    try:
        result = checked_cancelled(driver.decide, request(catalog, name=name), deadline=time.monotonic() + 5)
        assert result.errorCode == "cancelled" and result.host is None and result.decisionAttempted
        assert result.modelAttemptCount == len(model.calls) == 1
        assert len(result.modelObservations) == 1 and result.inputChars is not None
    finally:
        model.release.set()
        assert driver.close()


@pytest.mark.parametrize("source,prompt_changes", [
    ("app/rag.py", True), ("app/schemas.py", True), ("app/host_cache.py", False),
    ("app/audit_events.py", False), ("app/audit_context.py", False), ("app/baselines.py", True),
    ("app/config.py", False), ("app/paths.py", False), ("app/model_admission.py", False),
    ("app/rate_policy.py", False), ("app/rate_limit.py", False), ("app/request_guards.py", False),
    ("app/request_lifecycle.py", False), ("app/scoring.py", False), ("app/prompts.py", True),
    ("eval/manifest.py", False), ("eval/inventory.py", False), ("eval/grouping.py", False),
    ("eval/proofs.py", False), ("eval/legacy.py", False), ("eval/comparison.py", False),
    ("app/ai_host.py", True), ("app/host_context.py", True), ("app/host_evidence.py", True),
])
def test_relevant_executable_source_change_updates_actual_fingerprint(monkeypatch, source, prompt_changes):
    import eval.run_cli as cli
    before = cli._fixed_system_spec("pure_llm", "是")
    original = cli._read_copy
    changed = []
    def synthetic_read(path):
        content = original(path)
        if path.as_posix().endswith("/" + source):
            changed.append(source)
            return content + b"\n# synthetic review source-byte mutation, never written\n"
        return content
    monkeypatch.setattr(cli, "_read_copy", synthetic_read)
    after = cli._fixed_system_spec("pure_llm", "是")
    assert changed, "Executable dependency omitted from provenance"
    assert after.implementationDigest != before.implementationDigest
    assert (after.promptDigest != before.promptDigest) is prompt_changes


def test_unchanged_sources_and_fake_answer_identity_are_stable():
    from eval.run_cli import _fixed_system_spec
    assert _fixed_system_spec("pure_llm", "是") == _fixed_system_spec("pure_llm", "是")


def test_cancellation_during_sealing_retains_already_attempted_records(tmp_path, reviewed, catalog, monkeypatch, capsys):
    import eval.run_cli as cli
    import eval.runner as runner
    original = runner.seal_run_report
    calls = []
    def interrupt_once(snapshot, manifest, records, complete):
        calls.append(complete)
        if len(calls) == 1: raise KeyboardInterrupt("synthetic-private-seal")
        return original(snapshot, manifest, records, complete)
    monkeypatch.setattr(runner, "seal_run_report", interrupt_once)
    monkeypatch.setattr(cli, "_offline_driver", lambda *args, **kwargs: RecordingDriver())
    output = tmp_path / "seal-cancelled.json"
    assert checked_cancelled(cli.main, command(input_file(tmp_path, reviewed, catalog), output, repeat=2)) == 2
    bundle = cli.read_run_bundle(output)
    assert not bundle.reports[0].complete and bundle.reports[0].metrics.notAttemptedCount == 0
    assert all(r.actualAnswer == "不是" for r in bundle.reports[0].records)
    assert bundle.reports[1].metrics.notAttemptedCount == 3
    assert not capsys.readouterr().err


def test_cancellation_between_cases_preserves_previous_case_and_zero_unattempted_counts(reviewed, catalog):
    from eval.runner import run_dataset
    ticks = []
    def clock():
        ticks.append(1)
        if len(ticks) == 4: raise KeyboardInterrupt("synthetic-private-clock")
        return float(len(ticks))
    driver = RecordingDriver()
    report = checked_cancelled(run_dataset, small_snapshot(reviewed, catalog, groups=1, standalone=False),
        system=system(), driver=driver, repeat_index=0, repeat_count=1, clock=clock)
    assert not report.complete and report.metrics.total == 3 and len(driver.inputs) == 1 and driver.closed
    assert report.records[0].actualAnswer == "不是"
    assert all(not r.decisionAttempted and r.modelAttemptCount == 0 for r in report.records[1:])


def test_cancelled_last_case_cannot_be_rehashed_complete_despite_all_cases_attempted(reviewed, catalog):
    from app.baselines import digest
    from eval.contracts import DatasetError
    from eval.run_contracts import verify_run_report
    from eval.runner import run_dataset
    class LastCancelled(RecordingDriver):
        def decide(self, input, *, deadline):
            outcome = super().decide(input, deadline=deadline)
            return outcome.model_copy(update={"host": None, "errorCode": "cancelled"}) if len(self.inputs) == 3 else outcome
    report = run_dataset(small_snapshot(reviewed, catalog, groups=1, standalone=False),
        system=system(), driver=LastCancelled(), repeat_index=0, repeat_count=1)
    assert not report.complete and all(r.decisionAttempted for r in report.records)
    changed = report.model_copy(update={"complete": True})
    changed = changed.model_copy(update={"reportDigest": digest(changed.model_dump(mode="json", exclude={"reportDigest"}))})
    with pytest.raises(DatasetError): verify_run_report(changed)


@pytest.mark.parametrize("kind", ["outcome", "prediction"])
def test_unknown_count_is_not_a_general_escape_from_budget_validation(kind):
    from pydantic import ValidationError
    from eval.run_contracts import DriverOutcome, PredictionRecord
    from .test_runner_accounting import row
    if kind == "outcome":
        with pytest.raises(ValidationError):
            DriverOutcome(host=None, errorCode="driver_error", modelObservations=(), modelAttemptCount=None,
                inputChars=None, contextTurnsIncluded=None, decisionAttempted=True, cleanupComplete=False)
    else:
        invalid = row(0, prediction="error").model_copy(update={"modelAttemptCount": None})
        with pytest.raises(ValidationError): PredictionRecord.model_validate_json(invalid.model_dump_json(warnings="error"))


def test_setup_cancellation_is_distinct_from_in_flight_unknown_counts(tmp_path, reviewed, catalog, monkeypatch, capsys):
    import eval.run_cli as cli
    import eval.runner as runner
    verify = runner.verify_frozen_dataset
    created = []
    probes = []
    def verify_once(value):
        probes.append(1)
        if len(probes) == 1: raise KeyboardInterrupt("synthetic-private-setup")
        return verify(value)
    def factory(*args, **kwargs):
        driver = RecordingDriver(); created.append(driver)
        return driver
    monkeypatch.setattr(runner, "verify_frozen_dataset", verify_once)
    monkeypatch.setattr(cli, "_offline_driver", factory)
    output = tmp_path / "setup-cancelled.json"
    assert checked_cancelled(cli.main, command(input_file(tmp_path, reviewed, catalog), output, repeat=2)) == 2
    bundle = cli.read_run_bundle(output)
    assert len(created) == 1 and created[0].closed and not created[0].inputs
    assert all(r.modelAttemptCount == 0 and not r.decisionAttempted for run in bundle.reports for r in run.records)
    assert not capsys.readouterr().err


def test_bad_clock_during_cancelled_sealing_retry_remains_safe_refusal(reviewed, catalog, monkeypatch):
    import eval.runner as runner
    from eval.contracts import DatasetError
    attempts = []
    times = []
    original = runner.seal_run_report
    def seal_once(*args, **kwargs):
        attempts.append(1)
        if len(attempts) == 1: raise KeyboardInterrupt("synthetic-private-seal")
        return original(*args, **kwargs)
    def utc_now():
        times.append(1)
        if len(times) == 3: raise ValueError("synthetic-private-utc")
        return "2026-10-09T00:00:00Z"
    monkeypatch.setattr(runner, "seal_run_report", seal_once)
    driver = RecordingDriver()
    with pytest.raises(DatasetError) as caught:
        runner.run_dataset(small_snapshot(reviewed, catalog, groups=1, standalone=False),
            system=system(), driver=driver, repeat_index=0, repeat_count=1, utc_now=utc_now)
    assert driver.closed and "synthetic-private" not in str(caught.value)
