"""Runner retains actual outcomes and group-local history, never gold history."""
import pytest
from pydantic import ValidationError

from .support import RecordingDriver, small_snapshot
from .test_run_contracts import system


def run(snapshot, driver, **options):
    from eval.runner import run_dataset
    return run_dataset(snapshot, system=system(), driver=driver, repeat_index=options.pop("repeat_index", 0),
        repeat_count=options.pop("repeat_count", 1), **options)


def test_actual_wrong_answers_are_history_without_gold_or_source_fields(reviewed, catalog):
    snapshot = small_snapshot(reviewed, catalog)
    before = snapshot.model_dump_json()
    driver = RecordingDriver()
    report = run(snapshot, driver)
    assert report.metrics.total == 7 and report.complete and driver.closed
    assert snapshot.model_dump_json() == before
    assert all(r.expectedLabel.answer == "是" and r.actualAnswer == "不是" for r in report.records)
    assert [len(i.history) for i in driver.inputs] == [0, 1, 2, 0, 1, 2, 0]
    assert all(h.answer == "不是" for i in driver.inputs for h in i.history)
    assert driver.inputs[1].question == driver.inputs[4].question == "Is he awake?"
    assert driver.inputs[1].history[0].question != driver.inputs[4].history[0].question
    assert all(not set(i.model_dump()) & {"expectedLabel", "review", "proposedLabel", "sourceGroup", "familyGroup"} for i in driver.inputs)


def test_same_pronoun_opposite_synthetic_truth_never_replaces_actual_answers(reviewed, catalog):
    driver = RecordingDriver(("不是", "不是", "不是", "是", "是", "是"))
    report = run(small_snapshot(reviewed, catalog, standalone=False, opposite_second=True), driver)
    assert driver.inputs[1].question == driver.inputs[4].question == "Is he awake?"
    assert driver.inputs[1].history[0].answer == "不是" and driver.inputs[4].history[0].answer == "是"
    assert report.records[1].expectedLabel.answer == "是" and report.records[4].expectedLabel.answer == "不是"
    assert report.metrics.total == 6 and report.metrics.correct == 0 and report.complete


@pytest.mark.parametrize("middle", ["reminder", "error", "win", ValueError("synthetic-private-body"), "是 是"])
def test_failed_or_free_middle_is_not_history_but_all_rows_survive(reviewed, catalog, middle):
    snapshot = small_snapshot(reviewed, catalog, groups=1, standalone=False)
    driver = RecordingDriver(("不是", middle, "是"))
    report = run(snapshot, driver)
    assert report.metrics.total == 3 and len(report.records) == 3 and report.complete
    assert len(driver.inputs[2].history) == 1 and driver.inputs[2].history[0].answer == "不是"
    assert report.records[1].prediction == ("reminder" if middle == "reminder" else "error")
    assert "synthetic-private-body" not in report.model_dump_json()


def test_each_repeat_and_system_starts_a_new_context(reviewed, catalog):
    snapshot = small_snapshot(reviewed, catalog, groups=1, standalone=False)
    first = RecordingDriver(); second = RecordingDriver()
    run(snapshot, first, repeat_count=2)
    result = run(snapshot, second, repeat_index=1, repeat_count=2)
    assert not first.inputs[0].history and not second.inputs[0].history
    assert result.manifest.repeatIndex == 1 and result.manifest.repeatCount == 2


def test_non_dto_display_answer_is_not_accepted(reviewed, catalog):
    snapshot = small_snapshot(reviewed, catalog, groups=1, standalone=False)
    driver = RecordingDriver(({"reply": "是"}, "是", "是"))
    report = run(snapshot, driver)
    assert report.records[0].prediction == "error" and report.records[0].errorCode == "invalid_output"
    assert report.metrics.total == 3 and report.complete


def test_unknown_cleanup_stops_remaining_decisions_without_dropping_rows(reviewed, catalog):
    snapshot = small_snapshot(reviewed, catalog, groups=1, standalone=False)
    driver = RecordingDriver(clean=False)
    report = run(snapshot, driver)
    assert len(driver.inputs) == 1 and driver.closed and not report.complete
    assert report.metrics.total == 3 and report.metrics.notAttemptedCount == 2
    assert all(r.errorCode == "driver_unavailable" for r in report.records[1:])


def test_expired_deadlines_leave_all_rows_unattempted(reviewed, catalog):
    snapshot = small_snapshot(reviewed, catalog, groups=1, standalone=False)
    ticks = iter((0.0, 46.0, 47.0, 100.0, 146.0, 147.0, 200.0, 246.0, 247.0))
    driver = RecordingDriver()
    report = run(snapshot, driver, clock=lambda: next(ticks))
    assert driver.inputs == [] and not report.complete and report.metrics.notAttemptedCount == 3
    assert all(r.errorCode == "budget_exhausted" for r in report.records)


def test_close_exception_is_incomplete_not_report_dropped(reviewed, catalog):
    class BrokenClose(RecordingDriver):
        def close(self): raise ValueError("synthetic-private-close")
    report = run(small_snapshot(reviewed, catalog, groups=1, standalone=False), BrokenClose())
    assert not report.complete and report.metrics.total == 3
    assert "synthetic-private-close" not in report.model_dump_json()


@pytest.mark.parametrize("clock", [lambda: float("nan"), lambda: float("inf"), lambda: False])
def test_invalid_clock_refuses_artifact_and_closes_owned_driver(reviewed, catalog, clock):
    from eval.contracts import DatasetError
    driver = RecordingDriver()
    with pytest.raises(DatasetError): run(small_snapshot(reviewed, catalog), driver, clock=clock)
    assert driver.closed


def test_reservation_count_is_not_inferred_from_observations():
    from eval.run_contracts import DriverOutcome
    body = dict(host=None, errorCode="model_timeout", modelObservations=(), modelAttemptCount=1,
        inputChars=None, contextTurnsIncluded=None, decisionAttempted=True, cleanupComplete=True)
    outcome = DriverOutcome(**body)
    assert outcome.modelAttemptCount == 1 and outcome.modelObservations == ()
    with pytest.raises(ValidationError): DriverOutcome(**{**body, "decisionAttempted": False})


@pytest.mark.parametrize("field", ["puzzleVersion", "ruleVersion", "engineVersion", "normalizationVersion"])
def test_foreign_host_scope_is_an_error_and_not_next_history(reviewed, catalog, field):
    class ForeignDriver(RecordingDriver):
        def decide(self, input, *, deadline):
            outcome = super().decide(input, deadline=deadline)
            if len(self.inputs) == 1:
                return outcome.model_copy(update={"host": outcome.host.model_copy(update={
                    "versions": outcome.host.versions.model_copy(update={field: "foreign-version"})})})
            return outcome
    driver = ForeignDriver()
    report = run(small_snapshot(reviewed, catalog, groups=1, standalone=False), driver)
    assert report.records[0].errorCode == "version_mismatch" and report.records[0].prediction == "error"
    assert not driver.inputs[1].history and len(driver.inputs[2].history) == 1
    assert report.metrics.total == 3 and report.complete


def test_nonmonotonic_clock_refuses_report_and_still_closes_driver(reviewed, catalog):
    from eval.contracts import DatasetError
    ticks = iter((2.0, 1.0))
    driver = RecordingDriver()
    with pytest.raises(DatasetError) as error:
        run(small_snapshot(reviewed, catalog), driver, clock=lambda: next(ticks))
    assert error.value.code == "eval_clock_invalid" and driver.closed and not driver.inputs


@pytest.mark.parametrize("change", [{"repeat_index": True}, {"repeat_count": 11}, {"repeat_index": 2, "repeat_count": 2}])
def test_invalid_repeat_refuses_before_any_decision_and_closes_driver(reviewed, catalog, change):
    from eval.contracts import DatasetError
    driver = RecordingDriver()
    with pytest.raises(DatasetError): run(small_snapshot(reviewed, catalog), driver, **change)
    assert not driver.inputs and driver.closed


@pytest.mark.parametrize("bad_phase", ["start", "finish"])
def test_bad_utc_clock_cannot_leak_validation_body_and_owned_driver_still_closes(reviewed, catalog, bad_phase):
    from eval.contracts import DatasetError
    ticks = iter(("synthetic-private-clock-text", "2026-10-09T00:00:01Z") if bad_phase == "start"
        else ("2026-10-09T00:00:00Z", "synthetic-private-clock-text"))
    driver = RecordingDriver()
    with pytest.raises(DatasetError) as error:
        run(small_snapshot(reviewed, catalog, groups=1, standalone=False), driver, utc_now=lambda: next(ticks))
    assert driver.closed and "synthetic-private-clock-text" not in str(error.value)
    if bad_phase == "start": assert not driver.inputs


def test_trusted_driver_budget_violation_cannot_erase_observed_reservations(reviewed, catalog):
    from app.audit_events import ModelCallObservation
    from eval.contracts import DatasetError
    from eval.runner import run_dataset
    class OverspendingDriver(RecordingDriver):
        def decide(self, input, *, deadline):
            outcome = super().decide(input, deadline=deadline)
            observations = tuple(ModelCallObservation(ordinal=n, status="succeeded", provider="injected") for n in (1, 2))
            return outcome.model_copy(update={"modelAttemptCount": 2, "modelObservations": observations,
                "host": outcome.host.model_copy(update={"source": "llm"})})
    driver = OverspendingDriver()
    spec = system().model_copy(update={"budget": system().budget.model_copy(update={"modelAttemptsPerCase": 1})})
    with pytest.raises(DatasetError) as error:
        run_dataset(small_snapshot(reviewed, catalog, groups=1, standalone=False), system=spec,
            driver=driver, repeat_index=0, repeat_count=1)
    assert error.value.code == "eval_driver_budget_violation" and driver.closed and len(driver.inputs) == 1
