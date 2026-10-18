"""Immutable private evaluation DTOs; labels are report-only, never driver inputs."""
from datetime import datetime, timezone
from typing import Annotated, Literal

from pydantic import Field, StrictInt, field_validator, model_validator
from app.audit_events import CanonicalId, ModelCallObservation, TokenUsage
from app.baselines import canonical_json, digest, strict_json
from app.rule_contract import PuzzleVersion, RuleVersion
from app.schemas import AnswerType, HostResult, HostSource, HostVersions, ModelErrorCode
from .contracts import DatasetError, Digest, EvalPuzzle, ExpectedLabel, Identity, StrictDatasetModel, require_utc
from .manifest import FrozenDataset, verify_frozen_dataset

SystemName = Literal["pure_llm", "frozen_old", "new_system"]
Prediction = AnswerType | Literal["reminder", "error"]
RunErrorCode = ModelErrorCode | Literal["budget_exhausted", "driver_unavailable", "unexpected_host_kind",
    "version_mismatch", "driver_error", "cancelled", "invalid_output"]
Count = Annotated[StrictInt, Field(ge=0, le=5000)]
Probability = Annotated[float, Field(ge=0, le=1)] | None
Duration = Annotated[float, Field(ge=0)]
UsageStatus = Literal["known", "partial", "unknown", "invalid"]
ModelIdentity = Annotated[str, Field(min_length=1, max_length=200, pattern=r"^[A-Za-z0-9][A-Za-z0-9_.:/-]*$")]


def utc_timestamp() -> str:
    return datetime.now(timezone.utc).isoformat()


class RunBudget(StrictDatasetModel):
    modelAttemptsPerCase: Annotated[StrictInt, Field(ge=1, le=2)]
    caseTimeoutSeconds: Annotated[float, Field(gt=0, le=45)]
    maxContextTurns: Literal[12]
    maxInputChars: Literal[8000]
    contextPolicyVersion: Literal["context-v1"]
    usagePolicyVersion: Literal["provider-declared-v1"]

    @field_validator("maxContextTurns", "maxInputChars", mode="before")
    @classmethod
    def integer_policies(cls, value):
        if type(value) is not int: raise ValueError("Real context limit required")
        return value


class SystemSpec(StrictDatasetModel):
    name: SystemName
    implementationDigest: Digest
    promptDigest: Digest
    adapterId: ModelIdentity
    providerId: ModelIdentity
    modelId: ModelIdentity
    engineVersion: Identity
    normalizationVersion: Literal["exact-v1"]
    seed: Annotated[StrictInt, Field(ge=0, le=9223372036854775807)]
    executionEvidence: Literal["synthetic_fixture", "offline_engine", "real_provider"]
    budget: RunBudget

    @field_validator("adapterId", "providerId", "modelId", "engineVersion")
    @classmethod
    def finite_identity(cls, value):
        if not value.strip() or "://" in value: raise ValueError("Bounded identity, not a URL")
        return value


class HistoryTurn(StrictDatasetModel):
    question: Annotated[str, Field(min_length=1, max_length=500)]
    answer: AnswerType
    versions: HostVersions


class EvaluationInput(StrictDatasetModel):
    caseId: CanonicalId
    soupId: Identity
    puzzleVersion: PuzzleVersion
    question: Annotated[str, Field(min_length=1, max_length=500)]
    puzzle: EvalPuzzle
    history: Annotated[tuple[HistoryTurn, ...], Field(max_length=5000)]
    system: SystemSpec

    @model_validator(mode="after")
    def coherent_scope(self):
        if (self.puzzle.soupId != self.soupId or self.puzzle.puzzleVersion != self.puzzleVersion
            or any(h.versions.puzzleVersion != self.puzzleVersion or h.versions.ruleVersion != self.puzzle.ruleSnapshot.ruleVersion
                or h.versions.engineVersion != self.system.engineVersion or h.versions.normalizationVersion != "exact-v1" for h in self.history)):
            raise ValueError("Driver input scope differs")
        return self


class DriverOutcome(StrictDatasetModel):
    host: HostResult | None
    errorCode: RunErrorCode | None
    modelObservations: Annotated[tuple[ModelCallObservation, ...], Field(max_length=2)]
    modelAttemptCount: Annotated[StrictInt, Field(ge=0, le=2)] | None
    inputChars: Annotated[StrictInt, Field(ge=0, le=8000)] | None
    contextTurnsIncluded: Annotated[StrictInt, Field(ge=0, le=12)] | None
    decisionAttempted: bool
    cleanupComplete: bool

    @model_validator(mode="after")
    def one_outcome(self):
        if (self.host is None) == (self.errorCode is None): raise ValueError("Exactly one driver outcome required")
        if self.host is not None and not self.decisionAttempted: raise ValueError("Unattempted success")
        if self.modelAttemptCount is None and (self.errorCode != "cancelled" or not self.decisionAttempted or self.cleanupComplete):
            raise ValueError("Unknown reservation count requires incomplete attempted cancellation")
        if (not self.decisionAttempted and self.modelAttemptCount != 0
            or self.modelAttemptCount is not None and len(self.modelObservations) > self.modelAttemptCount
            or tuple(o.ordinal for o in self.modelObservations) != tuple(range(1, len(self.modelObservations) + 1))):
            raise ValueError("Observation/reservation accounting differs")
        return self


class PredictionRecord(StrictDatasetModel):
    schemaVersion: Literal[1] = 1
    caseId: CanonicalId
    soupId: Identity
    repeatIndex: Annotated[StrictInt, Field(ge=0, le=9)]
    systemName: SystemName
    expectedLabel: ExpectedLabel
    prediction: Prediction
    actualAnswer: AnswerType | None
    errorCode: RunErrorCode | None
    source: HostSource | None
    resultVersions: HostVersions | None
    durationMs: Duration
    decisionAttempted: bool
    modelAttemptCount: Annotated[StrictInt, Field(ge=0, le=2)] | None
    usage: TokenUsage
    usageStatus: UsageStatus
    contextTurnsIncluded: Annotated[StrictInt, Field(ge=0, le=12)] | None
    inputChars: Annotated[StrictInt, Field(ge=0, le=8000)] | None
    contextPolicyVersion: Literal["context-v1"]

    @model_validator(mode="after")
    def consistent_prediction(self):
        if self.prediction == "error":
            valid = self.actualAnswer is None and self.errorCode is not None
        elif self.prediction == "reminder":
            valid = self.actualAnswer is None and self.errorCode is None and self.decisionAttempted
        else:
            valid = self.actualAnswer == self.prediction and self.errorCode is None and self.decisionAttempted
        fields = (self.usage.inputTokens, self.usage.outputTokens, self.usage.totalTokens)
        present = sum(v is not None for v in fields)
        if self.modelAttemptCount is None and (self.errorCode != "cancelled" or not self.decisionAttempted
            or self.usageStatus != "unknown" or present):
            raise ValueError("Unknown cancelled reservations cannot fabricate known usage")
        if (not valid or (not self.decisionAttempted and self.modelAttemptCount != 0)
            or any(v is not None and v.bit_length() > 63 for v in fields)
            or (self.usageStatus == "known" and present != 3)
            or (self.usageStatus == "unknown" and present != 0)
            or (self.usageStatus == "partial" and present not in {1, 2})):
            raise ValueError("Prediction/usage accounting differs")
        return self


class RatioMetrics(StrictDatasetModel):
    support: Count
    predicted: Count
    tp: Count
    precision: Probability
    recall: Probability
    f1: Probability


class ClassMetrics(StrictDatasetModel):
    label: AnswerType
    support: Count
    tp: Count
    fp: Count
    fn: Count
    precision: Probability
    recall: Probability
    f1: Annotated[float, Field(ge=0, le=1)]


Matrix = Annotated[tuple[Annotated[tuple[Count, ...], Field(min_length=7, max_length=7)], ...], Field(min_length=6, max_length=6)]
ClassificationMatrix = Annotated[tuple[Annotated[tuple[Count, ...], Field(min_length=3, max_length=3)], ...], Field(min_length=2, max_length=2)]


class SoupMetrics(StrictDatasetModel):
    soupId: Identity
    total: Count
    correct: Count
    accuracy: Probability
    errorCount: Count
    errorRate: Probability
    macroF1: Probability
    confusionMatrix: Matrix
    reminderMetrics: RatioMetrics


class LatencyMetrics(StrictDatasetModel):
    count: Count
    min: Duration | None
    p50: Duration | None
    p95: Duration | None
    max: Duration | None


class UsageDimension(StrictDatasetModel):
    knownSum: Annotated[StrictInt, Field(ge=0, le=5000 * 9223372036854775807)] | None
    knownCount: Count
    unknownCount: Count


class UsageMetrics(StrictDatasetModel):
    inputTokens: UsageDimension
    outputTokens: UsageDimension
    totalTokens: UsageDimension


class EvaluationMetrics(StrictDatasetModel):
    total: Count
    correct: Count
    accuracy: Probability
    answerSupport: Count
    answerCorrect: Count
    answerAccuracy: Probability
    macroF1: Probability
    errorCount: Count
    errorRate: Probability
    notAttemptedCount: Count
    confusionMatrix: Matrix
    classes: Annotated[tuple[ClassMetrics, ...], Field(min_length=5, max_length=5)]
    soups: Annotated[tuple[SoupMetrics, ...], Field(max_length=5000)]
    reminderMetrics: RatioMetrics
    classificationMatrix: ClassificationMatrix
    errors: Annotated[tuple[tuple[RunErrorCode, Count], ...], Field(max_length=32)]
    latency: LatencyMetrics
    usage: UsageMetrics


class RunManifest(StrictDatasetModel):
    schemaVersion: Literal[1] = 1
    runId: CanonicalId
    datasetDigest: Digest
    puzzleVersions: Annotated[tuple[PuzzleVersion, ...], Field(min_length=1, max_length=256)]
    ruleVersions: Annotated[tuple[RuleVersion, ...], Field(min_length=1, max_length=256)]
    system: SystemSpec
    startedAt: Annotated[str, Field(min_length=20, max_length=40)]
    finishedAt: Annotated[str, Field(min_length=20, max_length=40)]
    inputCaseIds: Annotated[tuple[CanonicalId, ...], Field(min_length=1, max_length=5000)]
    inputCount: Annotated[StrictInt, Field(ge=1, le=5000)]
    repeatIndex: Annotated[StrictInt, Field(ge=0, le=9)]
    repeatCount: Annotated[StrictInt, Field(ge=1, le=10)]
    runnerVersion: Literal["eval-runner-v1"]
    metricsVersion: Literal["full-denominator-v1"]
    attemptAccounting: Literal["local-reservations-v1"]
    manifestDigest: Digest

    @field_validator("startedAt", "finishedAt")
    @classmethod
    def utc(cls, value): return require_utc(value)

    @model_validator(mode="after")
    def consistent_manifest(self):
        if (tuple(sorted(set(self.inputCaseIds))) != self.inputCaseIds or self.inputCount != len(self.inputCaseIds)
            or self.repeatIndex >= self.repeatCount
            or datetime.fromisoformat(self.finishedAt.replace("Z", "+00:00")) < datetime.fromisoformat(self.startedAt.replace("Z", "+00:00"))):
            raise ValueError("Run scope/time differs")
        return self


class RunReport(StrictDatasetModel):
    schemaVersion: Literal[1] = 1
    datasetProof: FrozenDataset
    manifest: RunManifest
    records: Annotated[tuple[PredictionRecord, ...], Field(min_length=1, max_length=5000)]
    metrics: EvaluationMetrics
    complete: bool
    reportDigest: Digest


def seal_run_report(dataset_proof, manifest, records, complete):
    from .metrics import compute_metrics
    try:
        if type(records) is not tuple or type(complete) is not bool:
            raise DatasetError("eval_report_input_invalid")
        body = dict(schemaVersion=1, datasetProof=dataset_proof.model_dump(mode="json", warnings="error"),
            manifest=manifest.model_dump(mode="json", warnings="error"),
            records=[r.model_dump(mode="json", warnings="error") for r in records],
            metrics=compute_metrics(records).model_dump(mode="json", warnings="error"), complete=complete)
        return verify_run_report(RunReport.model_validate_json(canonical_json({**body, "reportDigest": digest(body)})))
    except DatasetError:
        raise
    except Exception:
        raise DatasetError("eval_report_invalid") from None


def verify_run_report(report):
    from .metrics import compute_metrics
    from .contracts import EvalCase
    try:
        raw = report.model_dump_json(warnings="error")
        if len(raw.encode("utf-8")) > 100 * 1024 * 1024:
            raise DatasetError("eval_report_limit")
        checked = RunReport.model_validate_json(raw)
        dataset = verify_frozen_dataset(checked.datasetProof)
        manifest = checked.manifest
        if (manifest.manifestDigest != digest(manifest.model_dump(mode="json", exclude={"manifestDigest"}))
            or checked.reportDigest != digest(checked.model_dump(mode="json", exclude={"reportDigest"}))):
            raise DatasetError("eval_report_digest_mismatch")
        if (manifest.datasetDigest != dataset.manifest.datasetDigest
            or manifest.inputCaseIds != dataset.manifest.inputCaseIds or manifest.inputCount != dataset.manifest.inputCount
            or manifest.puzzleVersions != dataset.manifest.puzzleVersions or manifest.ruleVersions != dataset.manifest.ruleVersions):
            raise DatasetError("eval_report_dataset_mismatch")
        cases = tuple(EvalCase.model_validate_json(canonical_json(c)) for c in strict_json(dataset.casesJson))
        puzzles = tuple(EvalPuzzle.model_validate_json(canonical_json(p)) for p in strict_json(dataset.catalogJson))
        by_id = {c.caseId: c for c in cases}
        rules = {(p.soupId, p.puzzleVersion): p.ruleSnapshot.ruleVersion for p in puzzles}
        if (len(checked.records) != manifest.inputCount or len({r.caseId for r in checked.records}) != manifest.inputCount
            or {r.caseId for r in checked.records} != set(manifest.inputCaseIds)):
            raise DatasetError("eval_report_case_mismatch")
        for record in checked.records:
            case = by_id[record.caseId]
            if (record.soupId != case.soupId or record.expectedLabel != case.review.expectedLabel
                or record.repeatIndex != manifest.repeatIndex or record.systemName != manifest.system.name
                or record.modelAttemptCount is not None and record.modelAttemptCount > manifest.system.budget.modelAttemptsPerCase
                or record.contextPolicyVersion != manifest.system.budget.contextPolicyVersion):
                raise DatasetError("eval_report_case_mismatch")
            if record.prediction != "error":
                expected = HostVersions(puzzleVersion=case.puzzleVersion,
                    ruleVersion=rules[(case.soupId, case.puzzleVersion)], engineVersion=manifest.system.engineVersion,
                    normalizationVersion=manifest.system.normalizationVersion)
                if record.resultVersions != expected:
                    raise DatasetError("eval_report_version_mismatch")
        if checked.complete and any(not r.decisionAttempted or r.errorCode == "cancelled" for r in checked.records):
            raise DatasetError("eval_report_completeness_invalid")
        if checked.metrics != compute_metrics(checked.records):
            raise DatasetError("eval_report_metrics_mismatch")
        return checked
    except DatasetError:
        raise
    except Exception:
        raise DatasetError("eval_report_invalid") from None
