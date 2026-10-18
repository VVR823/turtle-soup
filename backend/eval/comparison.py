"""Full-cohort comparison; no best-repeat filtering or inferred model quality."""
from statistics import fmean, pstdev
from typing import Annotated, Literal

from pydantic import Field, StrictInt

from app.audit_events import CanonicalId
from app.baselines import digest
from .contracts import DatasetError, Digest, StrictDatasetModel
from .run_contracts import EvaluationMetrics, RunReport, SystemName, verify_run_report

SYSTEMS = ("pure_llm", "frozen_old", "new_system")
MAX_BYTES = 100 * 1024 * 1024
MetricName = Literal["accuracy", "answerAccuracy", "macroF1", "errorRate", "p50Ms", "p95Ms", "totalTokens", "modelReservations"]
METRICS = ("accuracy", "answerAccuracy", "macroF1", "errorRate", "p50Ms", "p95Ms", "totalTokens", "modelReservations")
Number = Annotated[float, Field(ge=0)] | None
Delta = Annotated[float, Field(ge=-1, le=1)] | None
RepeatIndex = Annotated[StrictInt, Field(ge=0, le=9)]


class MissingRun(StrictDatasetModel):
    systemName: SystemName
    repeatIndex: RepeatIndex


class IncompleteRun(MissingRun):
    runId: CanonicalId


class RunSummary(StrictDatasetModel):
    runId: CanonicalId
    repeatIndex: RepeatIndex
    complete: bool
    metrics: EvaluationMetrics


class MetricMoments(StrictDatasetModel):
    metric: MetricName
    knownCount: Annotated[StrictInt, Field(ge=0, le=10)]
    unknownCount: Annotated[StrictInt, Field(ge=0, le=10)]
    min: Number
    max: Number
    mean: Number
    populationStddev: Number


class SystemStatistics(StrictDatasetModel):
    systemName: SystemName
    perRun: Annotated[tuple[RunSummary, ...], Field(max_length=10)]
    moments: Annotated[tuple[MetricMoments, ...], Field(min_length=8, max_length=8)]


class ExploratoryDelta(StrictDatasetModel):
    baselineSystem: Literal["pure_llm", "frozen_old"]
    repeatIndex: RepeatIndex
    newRunId: CanonicalId
    baselineRunId: CanonicalId
    accuracy: Delta
    macroF1: Delta
    errorRate: Delta
    reason: Literal["incomplete_run"] | None


class ComparisonReport(StrictDatasetModel):
    schemaVersion: Literal[1] = 1
    reports: Annotated[tuple[RunReport, ...], Field(min_length=1, max_length=30)]
    reportDigests: Annotated[tuple[Digest, ...], Field(min_length=1, max_length=30)]
    commonScopeDigest: Digest
    missingRuns: Annotated[tuple[MissingRun, ...], Field(max_length=30)]
    incompleteRuns: Annotated[tuple[IncompleteRun, ...], Field(max_length=30)]
    complete: bool
    statistics: Annotated[tuple[SystemStatistics, ...], Field(min_length=3, max_length=3)]
    deltas: Annotated[tuple[ExploratoryDelta, ...], Field(max_length=20)]
    qualityConclusion: None
    comparisonDigest: Digest


def _common_scope(report):
    manifest = report.manifest
    spec = manifest.system
    return dict(datasetDigest=manifest.datasetDigest, puzzleVersions=manifest.puzzleVersions,
        ruleVersions=manifest.ruleVersions, inputCaseIds=manifest.inputCaseIds, inputCount=manifest.inputCount,
        repeatCount=manifest.repeatCount, adapterId=spec.adapterId, providerId=spec.providerId, modelId=spec.modelId,
        seed=spec.seed, budget=spec.budget.model_dump(mode="json"), normalizationVersion=spec.normalizationVersion,
        executionEvidence=spec.executionEvidence)


def _value(report, metric):
    metrics = report.metrics
    if metric in {"accuracy", "answerAccuracy", "macroF1", "errorRate"}: return getattr(metrics, metric)
    if metric == "p50Ms": return metrics.latency.p50
    if metric == "p95Ms": return metrics.latency.p95
    if metric == "totalTokens":
        return metrics.usage.totalTokens.knownSum if metrics.usage.totalTokens.unknownCount == 0 else None
    return None if any(row.modelAttemptCount is None for row in report.records) else sum(row.modelAttemptCount for row in report.records)


def _statistics(name, reports):
    selected = tuple(sorted((r for r in reports if r.manifest.system.name == name), key=lambda r: r.manifest.repeatIndex))
    moments = []
    for metric in METRICS:
        known = tuple(v for r in selected if (v := _value(r, metric)) is not None)
        moments.append(MetricMoments(metric=metric, knownCount=len(known), unknownCount=len(selected) - len(known),
            min=float(min(known)) if known else None, max=float(max(known)) if known else None,
            mean=fmean(known) if known else None, populationStddev=pstdev(known) if known else None))
    return SystemStatistics(systemName=name, perRun=tuple(RunSummary(runId=r.manifest.runId,
        repeatIndex=r.manifest.repeatIndex, complete=r.complete, metrics=r.metrics) for r in selected), moments=tuple(moments))


def compare_runs(reports: tuple[RunReport, ...]) -> ComparisonReport:
    try:
        if type(reports) is not tuple or not 1 <= len(reports) <= 30:
            raise DatasetError("eval_comparison_input_invalid")
        checked = []; input_bytes = 0
        for report in reports:
            input_bytes += len(report.model_dump_json(warnings="error").encode("utf-8"))
            if input_bytes > MAX_BYTES: raise DatasetError("eval_comparison_limit")
            checked.append(verify_run_report(report))
        checked = tuple(checked)
        common = _common_scope(checked[0]); slots = {}; ids = set(); specs = {}
        for report in checked:
            manifest = report.manifest; name = manifest.system.name
            key = (name, manifest.repeatIndex)
            if manifest.runId in ids or key in slots: raise DatasetError("eval_comparison_duplicate")
            if _common_scope(report) != common: raise DatasetError("eval_comparison_scope_mismatch")
            if name in specs and specs[name] != manifest.system: raise DatasetError("eval_comparison_system_drift")
            ids.add(manifest.runId); slots[key] = report; specs[name] = manifest.system
        missing = tuple(MissingRun(systemName=name, repeatIndex=index) for name in SYSTEMS
            for index in range(common["repeatCount"]) if (name, index) not in slots)
        incomplete = tuple(IncompleteRun(systemName=r.manifest.system.name, repeatIndex=r.manifest.repeatIndex,
            runId=r.manifest.runId) for r in checked if not r.complete)
        deltas = []
        for baseline in SYSTEMS[:2]:
            for index in range(common["repeatCount"]):
                new, old = slots.get(("new_system", index)), slots.get((baseline, index))
                if new is None or old is None: continue
                ready = new.complete and old.complete
                values = {metric: getattr(new.metrics, metric) - getattr(old.metrics, metric)
                    if ready and getattr(new.metrics, metric) is not None and getattr(old.metrics, metric) is not None else None
                    for metric in ("accuracy", "macroF1", "errorRate")}
                deltas.append(ExploratoryDelta(baselineSystem=baseline, repeatIndex=index, newRunId=new.manifest.runId,
                    baselineRunId=old.manifest.runId, **values, reason=None if ready else "incomplete_run"))
        result = ComparisonReport(reports=checked, reportDigests=tuple(r.reportDigest for r in checked),
            commonScopeDigest=digest(common), missingRuns=missing, incompleteRuns=incomplete,
            complete=not missing and not incomplete, statistics=tuple(_statistics(name, checked) for name in SYSTEMS),
            deltas=tuple(deltas), qualityConclusion=None, comparisonDigest="0" * 64)
        result = result.model_copy(update={"comparisonDigest": digest(result.model_dump(mode="json", exclude={"comparisonDigest"}))})
        if len(result.model_dump_json(warnings="error").encode("utf-8")) > MAX_BYTES:
            raise DatasetError("eval_comparison_limit")
        return result
    except DatasetError:
        raise
    except Exception:
        raise DatasetError("eval_comparison_invalid") from None


def verify_comparison_report(report: ComparisonReport) -> ComparisonReport:
    try:
        raw = report.model_dump_json(warnings="error")
        if len(raw.encode("utf-8")) > MAX_BYTES: raise DatasetError("eval_comparison_limit")
        checked = ComparisonReport.model_validate_json(raw)
        if checked.comparisonDigest != digest(checked.model_dump(mode="json", exclude={"comparisonDigest"})):
            raise DatasetError("eval_comparison_digest_mismatch")
        recomputed = compare_runs(checked.reports)
        if checked != recomputed: raise DatasetError("eval_comparison_derived_mismatch")
        return checked
    except DatasetError:
        raise
    except Exception:
        raise DatasetError("eval_comparison_invalid") from None
