"""Serial offline evaluation over the full immutable dataset proof."""
import time
import math
from typing import Callable, Protocol
from uuid import uuid4

from app.audit_events import TokenUsage
from app.baselines import canonical_json, digest, strict_json
from app.schemas import HostVersions
from .contracts import DatasetError, EvalCase, EvalPuzzle, require_utc
from .manifest import FrozenDataset, verify_frozen_dataset
from .run_contracts import (DriverOutcome, EvaluationInput, HistoryTurn, PredictionRecord, RunManifest, RunReport, SystemSpec,
    seal_run_report, utc_timestamp)


class EvaluationDriver(Protocol):
    """Trusted program interface, not an arbitrary-Python security sandbox."""
    def decide(self, input: EvaluationInput, *, deadline: float) -> DriverOutcome: ...
    def close(self) -> bool: ...


class EvaluationSetupCancelled(KeyboardInterrupt):
    """No decision was entered; CLI may safely retain an unattempted run."""


def aggregate_usage(outcome: DriverOutcome) -> tuple[TokenUsage, str]:
    """Unknown reservations/attempt dimensions cannot be silently summed as zero."""
    if outcome.modelAttemptCount is None:
        return TokenUsage(), "unknown"
    if outcome.modelAttemptCount == 0:
        if not outcome.decisionAttempted or outcome.host is not None and outcome.host.source in {"flow", "deterministic"}:
            return TokenUsage(inputTokens=0, outputTokens=0, totalTokens=0), "known"
        return TokenUsage(), "unknown"
    observations = outcome.modelObservations
    values = {field: sum(getattr(o.usage, field) for o in observations)
        if len(observations) == outcome.modelAttemptCount and all(getattr(o.usage, field) is not None for o in observations)
        else None for field in ("inputTokens", "outputTokens", "totalTokens")}
    if any(value is not None and value.bit_length() > 63 for value in values.values()):
        return TokenUsage(), "invalid"
    present = sum(v is not None for v in values.values())
    status = "invalid" if any(o.usageStatus == "invalid" for o in observations) else "known" if present == 3 else "partial" if present else "unknown"
    return TokenUsage(**values), status


def _failure(code, *, attempted):
    return DriverOutcome(host=None, errorCode=code, modelObservations=(), modelAttemptCount=0,
        inputChars=None, contextTurnsIncluded=None, decisionAttempted=attempted, cleanupComplete=True)


def _cancelled_unknown():
    # A trusted arbitrary driver may have dispatched before raising Ctrl-C.
    # Absence of a returned reservation ledger is unknown, never known zero.
    return DriverOutcome(host=None, errorCode="cancelled", modelObservations=(), modelAttemptCount=None,
        inputChars=None, contextTurnsIncluded=None, decisionAttempted=True, cleanupComplete=False)


def run_dataset(snapshot: FrozenDataset, *, system: SystemSpec, driver: EvaluationDriver,
                repeat_index: int, repeat_count: int, clock: Callable[[], float] = time.monotonic,
                utc_now: Callable[[], str] = utc_timestamp) -> RunReport:
    rows = []; histories = {}; stopped = False; all_attempted = True; last_tick = None; clean = False
    ordered = (); started = None; active_case = None; decision_entered = False; begin = None; outcome = None
    def tick():
        nonlocal last_tick
        value = clock()
        if type(value) not in {int, float} or not math.isfinite(value) or last_tick is not None and value < last_tick:
            raise DatasetError("eval_clock_invalid")
        last_tick = value
        return float(value)
    try:
        snapshot = verify_frozen_dataset(snapshot)
        system = SystemSpec.model_validate_json(system.model_dump_json(warnings="error"))
        if type(repeat_index) is not int or type(repeat_count) is not int or not 0 <= repeat_index < repeat_count <= 10:
            raise DatasetError("eval_repeat_invalid")
        cases = tuple(EvalCase.model_validate_json(canonical_json(c)) for c in strict_json(snapshot.casesJson))
        puzzles = {(p.soupId, p.puzzleVersion): p for p in
            (EvalPuzzle.model_validate_json(canonical_json(p)) for p in strict_json(snapshot.catalogJson))}
        ordered = sorted(cases, key=lambda c: (c.soupId, c.puzzleVersion, c.conversationId is None,
            c.conversationId or "", c.contextIndex or 0, c.caseId))
        started = require_utc(utc_now())
        for case in ordered:
            active_case = case.caseId; decision_entered = False; outcome = None; begin = None
            begin = tick(); puzzle = puzzles[(case.soupId, case.puzzleVersion)]
            key = (case.soupId, case.puzzleVersion, case.sourceGroup, case.familyGroup, case.split, case.conversationId)
            history = tuple(histories.get(key, ())) if case.caseType == "context" else ()
            input = EvaluationInput(caseId=case.caseId, soupId=case.soupId, puzzleVersion=case.puzzleVersion,
                question=case.question, puzzle=puzzle, history=history, system=system)
            deadline = begin + system.budget.caseTimeoutSeconds
            if stopped:
                outcome = _failure("driver_unavailable", attempted=False)
            elif tick() >= deadline:
                outcome = _failure("budget_exhausted", attempted=False)
            else:
                try:
                    decision_entered = True
                    raw = driver.decide(input, deadline=deadline)
                except KeyboardInterrupt:
                    outcome = _cancelled_unknown()
                except Exception:
                    outcome = _failure("driver_error", attempted=True)
                else:
                    try:
                        if not isinstance(raw, DriverOutcome): raise ValueError("Typed outcome required")
                        outcome = DriverOutcome.model_validate_json(raw.model_dump_json(warnings="error"))
                    except Exception:
                        outcome = _failure("invalid_output", attempted=True)
                    if outcome.modelAttemptCount is not None and outcome.modelAttemptCount > system.budget.modelAttemptsPerCase:
                        # A program contract violation cannot become a valid
                        # equal-budget report by erasing observed reservations.
                        raise DatasetError("eval_driver_budget_violation")
            host, code = outcome.host, outcome.errorCode
            expected_versions = HostVersions(puzzleVersion=case.puzzleVersion, ruleVersion=puzzle.ruleSnapshot.ruleVersion,
                engineVersion=system.engineVersion, normalizationVersion=system.normalizationVersion)
            if host is not None:
                if host.versions != expected_versions: code = "version_mismatch"
                elif host.kind == "system_error": code = host.errorCode
                elif host.kind == "win": code = "unexpected_host_kind"
            prediction = "error" if code else "reminder" if host.kind == "reminder" else host.answer
            usage, usage_status = aggregate_usage(outcome)
            rows.append(PredictionRecord(caseId=case.caseId, soupId=case.soupId, repeatIndex=repeat_index,
                systemName=system.name, expectedLabel=case.review.expectedLabel, prediction=prediction,
                actualAnswer=host.answer if prediction not in {"error", "reminder"} else None, errorCode=code,
                source=host.source if host else None, resultVersions=host.versions if host else None,
                durationMs=(tick() - begin) * 1000, decisionAttempted=outcome.decisionAttempted,
                modelAttemptCount=outcome.modelAttemptCount, usage=usage, usageStatus=usage_status,
                contextTurnsIncluded=outcome.contextTurnsIncluded, inputChars=outcome.inputChars, contextPolicyVersion="context-v1"))
            all_attempted &= outcome.decisionAttempted
            stopped |= not outcome.cleanupComplete or outcome.errorCode == "cancelled"
            if case.caseType == "context" and prediction not in {"error", "reminder"}:
                histories.setdefault(key, []).append(HistoryTurn(question=case.question, answer=host.answer, versions=host.versions))
    except KeyboardInterrupt:
        if not ordered or started is None:
            raise EvaluationSetupCancelled() from None
        # Also cover Ctrl-C between cases or after a returned outcome but
        # before its row was persisted. No new driver decision is issued.
        stopped = True; all_attempted = False
        for pending in ordered[len(rows):]:
            current = pending.caseId == active_case
            preserved = outcome if current and outcome is not None else None
            attempted = current and decision_entered
            count = preserved.modelAttemptCount if preserved else None if attempted else 0
            usage, status = aggregate_usage(preserved) if preserved else (
                (TokenUsage(), "unknown") if attempted else (TokenUsage(inputTokens=0, outputTokens=0, totalTokens=0), "known"))
            rows.append(PredictionRecord(caseId=pending.caseId, soupId=pending.soupId, repeatIndex=repeat_index,
                systemName=system.name, expectedLabel=pending.review.expectedLabel, prediction="error", actualAnswer=None,
                errorCode="cancelled", source=None, resultVersions=None,
                durationMs=(tick() - begin) * 1000 if current and begin is not None else 0.0,
                decisionAttempted=bool(attempted), modelAttemptCount=count, usage=usage, usageStatus=status,
                contextTurnsIncluded=preserved.contextTurnsIncluded if preserved else None,
                inputChars=preserved.inputChars if preserved else None, contextPolicyVersion="context-v1"))
    except DatasetError:
        raise
    except Exception:
        raise DatasetError("eval_run_invalid") from None
    finally:
        try: clean = driver.close() is True
        except (Exception, KeyboardInterrupt): clean = False
    def seal(complete):
        try:
            body = dict(schemaVersion=1, runId=str(uuid4()), datasetDigest=snapshot.manifest.datasetDigest,
                puzzleVersions=list(snapshot.manifest.puzzleVersions), ruleVersions=list(snapshot.manifest.ruleVersions),
                system=system.model_dump(mode="json", warnings="error"), startedAt=started, finishedAt=require_utc(utc_now()),
                inputCaseIds=list(snapshot.manifest.inputCaseIds), inputCount=snapshot.manifest.inputCount,
                repeatIndex=repeat_index, repeatCount=repeat_count, runnerVersion="eval-runner-v1",
                metricsVersion="full-denominator-v1", attemptAccounting="local-reservations-v1")
            manifest = RunManifest.model_validate_json(canonical_json({**body, "manifestDigest": digest(body)}))
            return seal_run_report(snapshot, manifest, tuple(rows), complete)
        except DatasetError:
            raise
        except Exception:
            raise DatasetError("eval_run_invalid") from None
    try:
        return seal(bool(all_attempted and clean and not stopped))
    except KeyboardInterrupt:
        # One ordinary interrupt while encoding/sealing still owns all rows;
        # never replace executed rows with a fresh zero-attempt placeholder.
        return seal(False)
    except DatasetError:
        raise
    except Exception:
        raise DatasetError("eval_run_invalid") from None
