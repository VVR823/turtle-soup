"""Hand-derived full denominators: failures are not a success-only subset."""
from uuid import UUID

import pytest


def row(index, truth="是", prediction="是", *, soup="metrics-owned", code=None,
        attempted=True, usage=None, usage_status="unknown", attempts=1):
    from app.audit_events import TokenUsage
    from app.schemas import HostVersions
    from eval.contracts import ExpectedLabel
    from eval.run_contracts import PredictionRecord
    return PredictionRecord(caseId=str(UUID(int=index + 1)), soupId=soup, repeatIndex=0,
        systemName="new_system", expectedLabel=ExpectedLabel(kind="reminder" if truth == "reminder" else "answer",
            answer=None if truth == "reminder" else truth), prediction=prediction,
        actualAnswer=prediction if prediction not in {"reminder", "error"} else None,
        errorCode=code or ("model_output_invalid" if prediction == "error" else None),
        source="flow" if prediction == "reminder" else "deterministic" if attempts == 0 and prediction != "error" else "llm",
        resultVersions=HostVersions(puzzleVersion="p1:" + "a" * 64, ruleVersion="r1:" + "b" * 64),
        durationMs=float(index + 1), decisionAttempted=attempted, modelAttemptCount=attempts,
        usage=usage or TokenUsage(), usageStatus=usage_status,
        contextTurnsIncluded=None, inputChars=None, contextPolicyVersion="context-v1")


def eight_rows():
    return tuple(row(n, truth, prediction, soup="small" if n < 2 else "large") for n, (truth, prediction) in enumerate((
        ("是", "是"), ("不是", "不是"), ("是也不是", "是"), ("算是", "reminder"),
        ("与此无关", "error"), ("reminder", "reminder"), ("reminder", "不是"), ("reminder", "error"))))


def test_all_eight_decisions_and_error_column_enter_literal_denominator():
    from eval.metrics import compute_metrics
    measured = compute_metrics(eight_rows())
    assert (measured.total, measured.correct, measured.errorCount) == (8, 3, 2)
    assert measured.accuracy == pytest.approx(3 / 8) and measured.errorRate == pytest.approx(2 / 8)
    assert measured.answerSupport == 5 and measured.answerCorrect == 2
    assert measured.answerAccuracy == pytest.approx(2 / 5)
    assert measured.confusionMatrix == ((1, 0, 0, 0, 0, 0, 0), (0, 1, 0, 0, 0, 0, 0),
        (1, 0, 0, 0, 0, 0, 0), (0, 0, 0, 0, 0, 1, 0), (0, 0, 0, 0, 0, 0, 1), (0, 1, 0, 0, 0, 1, 1))
    assert sum(map(sum, measured.confusionMatrix)) == 8
    assert measured.classificationMatrix == ((3, 1, 1), (1, 1, 1))


def test_five_class_macro_f1_includes_failures_false_reminders_and_control_false_positives():
    from eval.metrics import compute_metrics
    measured = compute_metrics(eight_rows())
    assert measured.macroF1 == pytest.approx(4 / 15)
    classes = {c.label: c for c in measured.classes}
    assert len(classes) == 5
    assert (classes["是"].tp, classes["是"].fp, classes["是"].fn) == (1, 1, 0)
    assert (classes["不是"].tp, classes["不是"].fp, classes["不是"].fn) == (1, 1, 0)
    assert classes["算是"].fn == classes["与此无关"].fn == 1
    assert measured.reminderMetrics.precision == pytest.approx(1 / 2)
    assert measured.reminderMetrics.recall == pytest.approx(1 / 3)
    assert measured.reminderMetrics.f1 == pytest.approx(2 / 5)


def test_per_soup_counts_sum_but_overall_accuracy_is_not_unweighted_soup_average():
    from eval.metrics import compute_metrics
    measured = compute_metrics(eight_rows()); soups = {s.soupId: s for s in measured.soups}
    assert (soups["small"].total, soups["small"].correct, soups["small"].accuracy) == (2, 2, 1.0)
    assert (soups["large"].total, soups["large"].correct, soups["large"].errorCount) == (6, 1, 2)
    assert measured.accuracy == pytest.approx(3 / 8)
    assert sum(s.total for s in measured.soups) == 8


def test_latency_nearest_rank_uses_failures_too():
    from eval.metrics import compute_metrics
    measured = compute_metrics(eight_rows())
    assert (measured.latency.count, measured.latency.min, measured.latency.p50, measured.latency.p95, measured.latency.max) == (8, 1.0, 4.0, 8.0, 8.0)


@pytest.mark.parametrize("code", ["model_quota", "model_timeout", "model_output_invalid", "driver_unavailable", "budget_exhausted"])
def test_each_failure_reason_is_retained_with_unchanged_denominator(code):
    from eval.metrics import compute_metrics
    attempted = code not in {"driver_unavailable", "budget_exhausted"}
    measured = compute_metrics((row(0), row(1, prediction="error", code=code, attempted=attempted, attempts=1 if attempted else 0)))
    assert (measured.total, measured.correct, measured.errorCount) == (2, 1, 1)
    assert measured.accuracy == measured.errorRate == 0.5
    assert measured.errors == ((code, 1),) and measured.notAttemptedCount == int(not attempted)


def test_unknown_usage_is_not_mistaken_for_known_zero_and_partial_fields_stay_partial():
    from app.audit_events import TokenUsage
    from eval.metrics import compute_metrics
    measured = compute_metrics((
        row(0, usage=TokenUsage(inputTokens=7, outputTokens=3, totalTokens=10), usage_status="known"),
        row(1), row(2, usage=TokenUsage(inputTokens=2), usage_status="partial"),
        row(3, usage=TokenUsage(inputTokens=0, outputTokens=0, totalTokens=0), usage_status="known", attempts=0)))
    assert (measured.usage.inputTokens.knownSum, measured.usage.inputTokens.knownCount, measured.usage.inputTokens.unknownCount) == (9, 3, 1)
    assert (measured.usage.totalTokens.knownSum, measured.usage.totalTokens.knownCount, measured.usage.totalTokens.unknownCount) == (10, 2, 2)
    unknown = compute_metrics((row(0),)).usage.totalTokens
    assert unknown.knownSum is None and unknown.knownCount == 0 and unknown.unknownCount == 1


def test_empty_input_does_not_manufacture_accuracy_or_latency():
    from eval.metrics import compute_metrics
    measured = compute_metrics(())
    assert measured.total == measured.correct == measured.errorCount == 0
    assert measured.accuracy is measured.errorRate is measured.answerAccuracy is measured.macroF1 is None
    assert measured.latency.count == 0 and measured.latency.p50 is measured.latency.p95 is None
    assert measured.reminderMetrics.precision is measured.reminderMetrics.recall is None


def test_unobserved_classes_have_zero_f1_not_a_perfect_observed_only_macro():
    from eval.metrics import compute_metrics
    measured = compute_metrics((row(0),))
    assert measured.accuracy == 1.0 and measured.macroF1 == pytest.approx(1 / 5)
    assert measured.reminderMetrics.precision is measured.reminderMetrics.recall is measured.reminderMetrics.f1 is None


def test_metrics_refuse_duplicate_case_identity_instead_of_inflating_support():
    from eval.contracts import DatasetError
    from eval.metrics import compute_metrics
    decision = row(0)
    with pytest.raises(DatasetError): compute_metrics((decision, decision))


def test_metrics_refuse_mutable_list_input_even_when_each_row_is_valid():
    from eval.contracts import DatasetError
    from eval.metrics import compute_metrics
    with pytest.raises(DatasetError, match="eval_metrics_input_invalid"):
        compute_metrics([row(0)])
