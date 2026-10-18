"""Pure whole-input statistics. Invalid/provider failures stay in the denominator."""
from collections import Counter
from math import ceil
from .contracts import DatasetError
from .run_contracts import (PredictionRecord, EvaluationMetrics, ClassMetrics, RatioMetrics,
    SoupMetrics, LatencyMetrics, UsageMetrics, UsageDimension)

ANSWERS = ("是", "不是", "是也不是", "算是", "与此无关")
LABELS = ANSWERS + ("reminder",)


def _ratio(numerator, denominator):
    return numerator / denominator if denominator else None


def _counts(records):
    matrix = [[0] * 7 for _ in range(6)]
    for record in records:
        truth = record.expectedLabel.answer if record.expectedLabel.kind == "answer" else "reminder"
        matrix[LABELS.index(truth)][6 if record.prediction == "error" else LABELS.index(record.prediction)] += 1
    total = len(records); correct = sum(matrix[i][i] for i in range(6))
    errors = sum(row[6] for row in matrix)
    classes = []
    for index, answer in enumerate(ANSWERS):
        tp = matrix[index][index]; support = sum(matrix[index]); predicted = sum(row[index] for row in matrix)
        fp, fn = predicted - tp, support - tp
        classes.append(ClassMetrics(label=answer, support=support, tp=tp, fp=fp, fn=fn,
            precision=_ratio(tp, predicted), recall=_ratio(tp, support), f1=_ratio(2 * tp, 2 * tp + fp + fn) or 0.0))
    reminder_support = sum(matrix[5]); reminder_predicted = sum(row[5] for row in matrix); reminder_tp = matrix[5][5]
    reminder = RatioMetrics(support=reminder_support, predicted=reminder_predicted, tp=reminder_tp,
        precision=_ratio(reminder_tp, reminder_predicted), recall=_ratio(reminder_tp, reminder_support),
        f1=_ratio(2 * reminder_tp, reminder_support + reminder_predicted))
    return dict(total=total, correct=correct, accuracy=_ratio(correct, total), errorCount=errors,
        errorRate=_ratio(errors, total), macroF1=sum(c.f1 for c in classes) / 5 if total else None,
        confusionMatrix=tuple(tuple(row) for row in matrix), reminderMetrics=reminder), tuple(classes)


def compute_metrics(records: tuple[PredictionRecord, ...]) -> EvaluationMetrics:
    try:
        if type(records) is not tuple or len(records) > 5000:
            raise DatasetError("eval_metrics_input_invalid")
        checked = tuple(PredictionRecord.model_validate_json(r.model_dump_json(warnings="error")) for r in records)
        if len({r.caseId for r in checked}) != len(checked):
            raise DatasetError("eval_metrics_duplicate_case")
        counts, classes = _counts(checked); matrix = counts["confusionMatrix"]
        soups = []
        for soup in sorted({r.soupId for r in checked}):
            subset = tuple(r for r in checked if r.soupId == soup)
            values, _ = _counts(subset)
            soups.append(SoupMetrics(soupId=soup, **values))
        durations = sorted(r.durationMs for r in checked)
        latency = LatencyMetrics(count=len(durations), min=durations[0] if durations else None,
            p50=durations[ceil(len(durations) * .5) - 1] if durations else None,
            p95=durations[ceil(len(durations) * .95) - 1] if durations else None,
            max=durations[-1] if durations else None)
        usage = {}
        for field in ("inputTokens", "outputTokens", "totalTokens"):
            known = [getattr(r.usage, field) for r in checked if getattr(r.usage, field) is not None]
            usage[field] = UsageDimension(knownSum=sum(known) if known else None,
                knownCount=len(known), unknownCount=len(checked) - len(known))
        answer_support = sum(c.support for c in classes); answer_correct = sum(c.tp for c in classes)
        classification = (
            (sum(sum(row[:5]) for row in matrix[:5]), sum(row[5] for row in matrix[:5]), sum(row[6] for row in matrix[:5])),
            (sum(matrix[5][:5]), matrix[5][5], matrix[5][6]))
        return EvaluationMetrics(**counts, answerSupport=answer_support, answerCorrect=answer_correct,
            answerAccuracy=_ratio(answer_correct, answer_support), classes=classes, soups=tuple(soups),
            notAttemptedCount=sum(not r.decisionAttempted for r in checked), classificationMatrix=classification,
            errors=tuple(sorted(Counter(r.errorCode for r in checked if r.prediction == "error").items())),
            latency=latency, usage=UsageMetrics(**usage))
    except DatasetError:
        raise
    except Exception:
        raise DatasetError("eval_metrics_invalid") from None
