"""Closed private aggregation contracts; cursors contain public group keys only."""
import base64
from datetime import date, datetime, timezone
import math
import re
from typing import Annotated, Literal

from pydantic import BaseModel, ConfigDict, Field, StrictInt, field_validator, model_validator

from . import baselines
from .rule_contract import PuzzleVersion, RuleVersion

MAX_STAMP = 253402300799
MAX_WINDOW = 31 * 86400
MAX_EXPORT_BYTES = 512 * 1024
Count = Annotated[StrictInt, Field(ge=0, le=9223372036854775807)]
PublicId = Annotated[str, Field(min_length=1, max_length=200)]


class MetricsError(RuntimeError):
    def __init__(self, code="metrics_query_invalid", status=422):
        self.code, self.status = code, status
        super().__init__(code)


class ClosedMetricsModel(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True, strict=True, allow_inf_nan=False)

    @field_validator("schemaVersion", check_fields=False, mode="before")
    @classmethod
    def real_schema(cls, value):
        if type(value) is not int or value != cls.model_fields["schemaVersion"].default:
            raise ValueError("Exact integer response schema required")
        return value

    @field_validator("soupId", check_fields=False)
    @classmethod
    def nonblank_id(cls, value):
        if value is not None and not value.strip():
            raise ValueError("Nonblank public identifier required")
        return value


def _stamp(value):
    if type(value) not in (int, float) or not math.isfinite(value) or not 0 <= value <= MAX_STAMP:
        raise ValueError("Finite bounded timestamp required")
    return float(value)


class MetricsWindow(ClosedMetricsModel):
    start: float
    end: float

    @field_validator("start", "end", mode="before")
    @classmethod
    def timestamps(cls, value):
        return _stamp(value)

    @model_validator(mode="after")
    def bounded_window(self):
        if not 0 <= self.end - self.start <= MAX_WINDOW:
            raise ValueError("Window must not exceed31 days")
        return self


class MetricsFilters(ClosedMetricsModel):
    soupId: PublicId | None = None
    puzzleVersion: PuzzleVersion | None = None
    ruleVersion: RuleVersion | None = None


class MetricsQuery(MetricsWindow, MetricsFilters):
    limit: Annotated[StrictInt, Field(ge=1, le=100)] = 50
    cursor: Annotated[str, Field(min_length=1, max_length=2048, pattern=r"^[A-Za-z0-9_-]+$")] | None = None


class MetricsGroupKey(MetricsFilters):
    day: Annotated[str, Field(pattern=r"^\d{4}-\d{2}-\d{2}$", min_length=10, max_length=10)]

    @field_validator("day")
    @classmethod
    def real_day(cls, value):
        if date.fromisoformat(value).isoformat() != value:
            raise ValueError("Canonical UTC day required")
        return value


class MetricsCounts(ClosedMetricsModel):
    sessionsCreated: Count = 0
    successfulChargedTurns: Count = 0
    httpAttempts: Count = 0
    feedbackSubmitted: Count = 0
    tasksCreated: Count = 0
    candidatesCreated: Count = 0
    reviewApproved: Count = 0
    reviewRejected: Count = 0
    candidatePublicationEvents: Count = 0


class MetricsExcluded(ClosedMetricsModel):
    test: MetricsCounts = Field(default_factory=MetricsCounts)
    synthetic: MetricsCounts = Field(default_factory=MetricsCounts)
    legacy: MetricsCounts = Field(default_factory=MetricsCounts)
    unknown: MetricsCounts = Field(default_factory=MetricsCounts)


class MetricsTaskStates(ClosedMetricsModel):
    queued: Count = 0
    running: Count = 0
    awaiting_review: Count = 0
    needs_human: Count = 0
    failed: Count = 0
    cancelled: Count = 0


class MetricsCandidateStates(ClosedMetricsModel):
    pending: Count = 0
    approved: Count = 0
    rejected: Count = 0
    published: Count = 0


class MetricsPublication(ClosedMetricsModel):
    numerator: Count = 0
    denominator: Count = 0
    ratio: Annotated[float, Field(ge=0, le=1)] | None = None

    @model_validator(mode="after")
    def exact_denominator(self):
        if self.numerator > self.denominator or (
            self.ratio != (self.numerator / self.denominator) if self.denominator else self.ratio is not None
        ):
            raise ValueError("Publication ratio must match its complete cohort")
        return self


class MetricsObservationCounts(ClosedMetricsModel):
    """Complete observation cohort, not accuracy or successful-results-only."""
    observedRuns: Count
    passedRuns: Count
    failedRuns: Count
    incompleteRuns: Count
    pendingRuns: Count
    pendingExpiredRuns: Count
    plannedCases: Count
    attemptedCases: Count
    passedCases: Count
    counterexampleCases: Count
    errorCases: Count
    unsupportedCases: Count
    notAttemptedCases: Count

    @model_validator(mode='after')
    def complete_denominator(self):
        if (self.observedRuns != self.passedRuns + self.failedRuns + self.incompleteRuns + self.pendingRuns
            or self.pendingExpiredRuns > self.pendingRuns
            or self.passedCases < self.passedRuns
            or not self.failedRuns <= self.counterexampleCases <= 100 * self.failedRuns
            or not self.observedRuns <= self.plannedCases <= 100 * self.observedRuns
            or self.notAttemptedCases < self.pendingRuns
            or self.attemptedCases > 100 * (self.observedRuns - self.pendingRuns)
            or self.attemptedCases != self.passedCases + self.counterexampleCases + self.errorCases + self.unsupportedCases
            or self.plannedCases != self.attemptedCases + self.notAttemptedCases):
            raise ValueError('Observation states must cover the complete cohort and planned cases')
        return self


class MetricsPostPublicationRegression(ClosedMetricsModel):
    """Unavailable observation source; absence is never zero."""
    state: Literal["unknown"] = "unknown"
    failedRuns: None = None
    observedRuns: None = None
    reason: Literal["source_not_integrated", "schema_5_required", "source_unavailable"] = "source_not_integrated"


class MetricsObservationExcluded(ClosedMetricsModel):
    test: MetricsObservationCounts
    synthetic: MetricsObservationCounts
    unknown: MetricsObservationCounts


class MetricsObservedRegression(MetricsObservationCounts):
    state: Literal["observed", "partial"]
    sourceCoverageStart: float
    historicalBackfill: Literal[False] = False
    windowStartsBeforeCoverage: bool
    excluded: MetricsObservationExcluded

    @field_validator("sourceCoverageStart", mode="before")
    @classmethod
    def coverage_stamp(cls, value):
        return _stamp(value)

    @field_validator("historicalBackfill", mode="before")
    @classmethod
    def no_backfill(cls, value):
        if value is not False:
            raise ValueError("Historical observation coverage cannot be manufactured")
        return value

    @model_validator(mode="after")
    def coverage_state(self):
        if (self.state == "partial") != self.windowStartsBeforeCoverage:
            raise ValueError("Observation state must disclose pre-coverage windows")
        return self


class MetricsSummary(ClosedMetricsModel):
    counts: MetricsCounts = Field(default_factory=MetricsCounts)
    excluded: MetricsExcluded = Field(default_factory=MetricsExcluded)
    unscopedReal: MetricsCounts = Field(default_factory=MetricsCounts)
    taskStates: MetricsTaskStates = Field(default_factory=MetricsTaskStates)
    candidateStates: MetricsCandidateStates = Field(default_factory=MetricsCandidateStates)
    taskPublication: MetricsPublication = Field(default_factory=MetricsPublication)
    postPublicationRegression: Annotated[MetricsPostPublicationRegression | MetricsObservedRegression,
        Field(discriminator="state")] = Field(default_factory=MetricsPostPublicationRegression)

    @model_validator(mode="after")
    def complete_states(self):
        if (sum(self.taskStates.model_dump().values()) != self.counts.tasksCreated
            or sum(self.candidateStates.model_dump().values()) != self.counts.candidatesCreated
            or self.taskPublication.denominator != self.counts.tasksCreated):
            raise ValueError("Current states and denominator must cover the full cohort")
        return self


class MetricsProcessAudit(ClosedMetricsModel):
    complete: bool
    permanentGap: bool
    dropped: Count
    fallbackCount: Count
    memoryCount: Count
    activeIO: Count

    @model_validator(mode="after")
    def no_false_complete(self):
        if self.complete and (self.permanentGap or self.dropped or self.fallbackCount or self.memoryCount or self.activeIO):
            raise ValueError("Pending or lost audit cannot be complete")
        return self


class MetricsCoverage(ClosedMetricsModel):
    auditStartedAt: float | None = None
    agentStartedAt: float | None = None
    historicalAttemptsBackfilled: Literal[False] = False
    historicalRunsBackfilled: Literal[False] = False
    windowStartsBeforeAudit: bool | None = None
    windowStartsBeforeAgent: bool | None = None
    processAudit: MetricsProcessAudit | None = None
    state: Literal["complete", "partial", "unknown"] = "unknown"

    @field_validator("auditStartedAt", "agentStartedAt", mode="before")
    @classmethod
    def known_start(cls, value):
        return None if value is None else _stamp(value)

    @field_validator("historicalAttemptsBackfilled", "historicalRunsBackfilled", mode="before")
    @classmethod
    def no_backfill(cls, value):
        if value is not False:
            raise ValueError("Historical coverage cannot be manufactured")
        return value

    @model_validator(mode="after")
    def no_false_complete(self):
        if self.state == "complete" and (self.auditStartedAt is None or self.agentStartedAt is None
            or self.windowStartsBeforeAudit is not False or self.windowStartsBeforeAgent is not False
            or self.processAudit is None or not self.processAudit.complete):
            raise ValueError("Complete coverage needs known post-epoch window and process status")
        return self


class MetricsGroup(MetricsGroupKey):
    counts: MetricsCounts


class MetricsPage(ClosedMetricsModel):
    schemaVersion: Literal[3] = 3
    consistency: Literal["fixed_window_live_snapshot"] = "fixed_window_live_snapshot"
    query: MetricsQuery
    summary: MetricsSummary
    coverage: MetricsCoverage
    groups: Annotated[tuple[MetricsGroup, ...], Field(max_length=100)] = ()
    nextCursor: Annotated[str, Field(min_length=1, max_length=2048)] | None = None

    @model_validator(mode="after")
    def page_bound(self):
        if len(self.groups) > self.query.limit or self.nextCursor is not None and not self.groups:
            raise ValueError("Page length or lookahead cursor mismatch")
        observation = self.summary.postPublicationRegression
        if isinstance(observation, MetricsObservedRegression) and observation.windowStartsBeforeCoverage != (
            self.query.start < observation.sourceCoverageStart):
            raise ValueError("Observation coverage must match the query window")
        return self


class MetricsExport(ClosedMetricsModel):
    schemaVersion: Literal[3] = 3
    window: MetricsWindow
    filters: MetricsFilters
    summary: MetricsSummary
    coverage: MetricsCoverage
    groups: Annotated[tuple[MetricsGroup, ...], Field(max_length=100)]
    complete: Literal[True] = True
    generatedAt: float

    @model_validator(mode="after")
    def observation_window_binding(self):
        observation = self.summary.postPublicationRegression
        if isinstance(observation, MetricsObservedRegression) and observation.windowStartsBeforeCoverage != (
            self.window.start < observation.sourceCoverageStart):
            raise ValueError("Observation coverage must match the exported window")
        return self

    @field_validator("complete", mode="before")
    @classmethod
    def full_only(cls, value):
        if value is not True:
            raise ValueError("Only complete snapshots can be exported")
        return value

    @field_validator("generatedAt", mode="before")
    @classmethod
    def generated_stamp(cls, value):
        return _stamp(value)


def _checked(model, value):
    # A copied/injected frozen model is not itself a validation boundary.
    if isinstance(value, BaseModel):
        value = value.model_dump(mode="python", warnings="error")
    return model.model_validate(value)


def _cursor_body(query, key):
    query = _checked(MetricsQuery, query)
    key = _checked(MetricsGroupKey, key)
    bucket = datetime.fromisoformat(key.day).replace(tzinfo=timezone.utc).timestamp()
    if not bucket < query.end or not bucket + 86400 > query.start:
        raise ValueError("Cursor day is outside the half-open window")
    for name in ("soupId", "puzzleVersion", "ruleVersion"):
        value = getattr(query, name)
        if value is not None and getattr(key, name) != value:
            raise ValueError("Cursor key must match its filters")
    return {"schemaVersion": 1, "query": query.model_dump(exclude={"cursor"}), "key": key.model_dump()}


def encode_metrics_cursor(query: MetricsQuery, key: MetricsGroupKey) -> str:
    try:
        raw = baselines.canonical_json(_cursor_body(query, key)).encode("utf-8")
        cursor = base64.urlsafe_b64encode(raw).decode().rstrip("=")
        if len(cursor) > 2048:
            raise ValueError("Cursor is too large")
        return cursor
    except Exception:
        raise MetricsError() from None


def decode_metrics_cursor(value: str) -> tuple[MetricsQuery, MetricsGroupKey]:
    try:
        if type(value) is not str or not 1 <= len(value) <= 2048 or not re.fullmatch(r"[A-Za-z0-9_-]+", value):
            raise ValueError("Invalid cursor encoding")
        raw = base64.b64decode(value + "=" * (-len(value) % 4), altchars=b"-_", validate=True)
        fields = baselines.strict_json(raw.decode("utf-8"))
        if (type(fields) is not dict or set(fields) != {"schemaVersion", "query", "key"}
            or type(fields["schemaVersion"]) is not int or fields["schemaVersion"] != 1
            or type(fields["query"]) is not dict or "cursor" in fields["query"]):
            raise ValueError("Unknown cursor shape")
        query, key = _checked(MetricsQuery, fields["query"]), _checked(MetricsGroupKey, fields["key"])
        if encode_metrics_cursor(query, key) != value:
            raise ValueError("Noncanonical cursor")
        return query, key
    except Exception:
        raise MetricsError() from None


def parse_metrics_query(values: list[tuple[str, str]], *, now: float, export: bool = False) -> MetricsQuery:
    try:
        allowed = {"start", "end", "soupId", "puzzleVersion", "ruleVersion"}
        if not export:
            allowed |= {"limit", "cursor"}
        fields = {}
        for name, value in values:
            if name not in allowed or name in fields or type(value) is not str:
                raise ValueError("Unknown or duplicate query")
            fields[name] = value
        cursor = fields.get("cursor")
        original = decode_metrics_cursor(cursor)[0] if cursor is not None else None
        end = original.end if original is not None else _stamp(now)
        if "end" in fields:
            end = float(fields["end"])
        start = original.start if original is not None else max(0.0, end - 7 * 86400)
        if "start" in fields:
            start = float(fields["start"])
        limit = original.limit if original is not None else (100 if export else 50)
        if "limit" in fields:
            if not re.fullmatch(r"[0-9]+", fields["limit"]):
                raise ValueError("Integer page length required")
            limit = int(fields["limit"])
        body = {"start": start, "end": end, "limit": limit, "cursor": cursor}
        for name in ("soupId", "puzzleVersion", "ruleVersion"):
            body[name] = fields.get(name, getattr(original, name) if original is not None else None)
        query = MetricsQuery(**body)
        if original is not None and query.model_dump(exclude={"cursor"}) != original.model_dump(exclude={"cursor"}):
            raise ValueError("Cursor query mismatch")
        return query
    except Exception:
        raise MetricsError() from None


def export_projection(page: MetricsPage, *, generated_at: float) -> MetricsExport:
    try:
        # Refuse the lookahead before revalidation: partial is not complete.
        if getattr(page, "nextCursor", None) is not None:
            raise MetricsError("metrics_export_too_large", 409)
        page = _checked(MetricsPage, page)
        query = page.query
        output = MetricsExport(window=MetricsWindow(start=query.start, end=query.end),
            filters=MetricsFilters(**{name: getattr(query, name) for name in ("soupId", "puzzleVersion", "ruleVersion")}),
            summary=page.summary, coverage=page.coverage, groups=page.groups, generatedAt=generated_at)
        if len(output.model_dump_json(warnings="error").encode("utf-8")) > MAX_EXPORT_BYTES:
            raise MetricsError("metrics_export_too_large", 409)
        return output
    except MetricsError:
        raise
    except Exception:
        raise MetricsError("metrics_unavailable", 503) from None
