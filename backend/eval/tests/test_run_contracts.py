"""Run reports bind all original labels and decisions, not just a checksum."""
from uuid import UUID

import pytest
from pydantic import ValidationError

from .test_runner_accounting import row
from .test_dataset_manifest import checked110, freeze


def system():
    from eval.run_contracts import RunBudget, SystemSpec
    return SystemSpec(name="new_system", implementationDigest="a" * 64, promptDigest="b" * 64,
        adapterId="owned-offline", providerId="fake", modelId="scripted", engineVersion="host-v3",
        normalizationVersion="exact-v1", seed=0, executionEvidence="synthetic_fixture",
        budget=RunBudget(modelAttemptsPerCase=2, caseTimeoutSeconds=45.0, maxContextTurns=12,
            maxInputChars=8000, contextPolicyVersion="context-v1", usagePolicyVersion="provider-declared-v1"))


def report(catalog):
    from app.baselines import canonical_json, digest, strict_json
    from app.schemas import HostVersions
    from eval.run_contracts import RunManifest, seal_run_report
    cases, puzzles = checked110(catalog); snapshot = freeze(cases, puzzles)
    rows = tuple(row(n).model_copy(update={"caseId": c.caseId, "soupId": c.soupId,
        "expectedLabel": c.review.expectedLabel,
        "resultVersions": HostVersions(puzzleVersion=c.puzzleVersion,
            ruleVersion=next(p.ruleSnapshot.ruleVersion for p in puzzles if p.soupId == c.soupId))})
        for n, c in enumerate(sorted(cases, key=lambda c: c.caseId)))
    body = dict(schemaVersion=1, runId=str(UUID(int=999)), datasetDigest=snapshot.manifest.datasetDigest,
        puzzleVersions=list(snapshot.manifest.puzzleVersions), ruleVersions=list(snapshot.manifest.ruleVersions),
        system=system().model_dump(mode="json"), startedAt="2026-10-09T00:00:00Z", finishedAt="2026-10-09T00:00:01Z",
        inputCaseIds=list(snapshot.manifest.inputCaseIds), inputCount=110, repeatIndex=0, repeatCount=1,
        runnerVersion="eval-runner-v1", metricsVersion="full-denominator-v1", attemptAccounting="local-reservations-v1")
    manifest = RunManifest.model_validate_json(canonical_json({**body, "manifestDigest": digest(body)}))
    return seal_run_report(snapshot, manifest, rows, True)


@pytest.mark.parametrize("field,value", [("modelAttemptsPerCase", True), ("modelAttemptsPerCase", 0),
    ("modelAttemptsPerCase", 3), ("caseTimeoutSeconds", float("nan")), ("caseTimeoutSeconds", 46.0),
    ("maxContextTurns", 13), ("maxInputChars", 8001)])
def test_run_budget_refuses_coerced_unbounded_or_different_context_policy(field, value):
    from eval.run_contracts import RunBudget
    with pytest.raises(ValidationError): RunBudget.model_validate({**system().budget.model_dump(mode="python"), field: value})


@pytest.mark.parametrize("field,value", [("durationMs", -1.0), ("durationMs", float("inf")),
    ("durationMs", False), ("actualAnswer", "不是"), ("errorCode", "private-raw-error"),
    ("modelAttemptCount", 3), ("usageStatus", "known")])
def test_prediction_boundary_refuses_inconsistent_or_unsafe_results(field, value):
    from eval.run_contracts import PredictionRecord
    with pytest.raises(ValidationError): PredictionRecord.model_validate({**row(0).model_dump(mode="python"), field: value})


@pytest.mark.parametrize("field", ["expectedLabel", "review", "proposedLabel", "proposedFactIds", "rawLegacyExpected", "sourceGroup"])
def test_driver_input_does_not_accept_gold_review_or_provenance_extras(catalog, field):
    from eval.run_contracts import EvaluationInput
    puzzle = catalog[0]
    values = dict(caseId=str(UUID(int=1)), soupId=puzzle.soupId, puzzleVersion=puzzle.puzzleVersion,
        question="Was the light switched off?", puzzle=puzzle, history=(), system=system())
    assert EvaluationInput(**values).question == values["question"]
    with pytest.raises(ValidationError): EvaluationInput(**values, **{field: "synthetic-private-claim"})


def test_full_report_keeps_every_decision_and_original_private_dataset_proof(catalog):
    from eval.run_contracts import verify_run_report
    original = report(catalog)
    assert original.manifest.inputCount == original.metrics.total == len(original.records) == 110
    assert original.metrics.correct == 110 and original.manifest.system.executionEvidence == "synthetic_fixture"
    assert verify_run_report(original) == original
    assert original.datasetProof.manifest.datasetDigest == original.manifest.datasetDigest


@pytest.mark.parametrize("problem", ["gold", "soup", "versions", "repeat", "duplicate", "omitted", "metrics"])
def test_rehashed_report_cannot_swap_bound_truth_scope_or_denominator(catalog, problem):
    from app.baselines import digest
    from app.schemas import HostVersions
    from eval.contracts import DatasetError, ExpectedLabel
    from eval.metrics import compute_metrics
    from eval.run_contracts import verify_run_report
    original = report(catalog); rows = original.records
    if problem == "gold":
        rows = (rows[0].model_copy(update={"expectedLabel": ExpectedLabel(kind="answer", answer="不是")}),) + rows[1:]
    elif problem == "soup": rows = (rows[0].model_copy(update={"soupId": "foreign"}),) + rows[1:]
    elif problem == "versions": rows = (rows[0].model_copy(update={"resultVersions": HostVersions(puzzleVersion="p1:" + "f" * 64, ruleVersion="r1:" + "e" * 64)}),) + rows[1:]
    elif problem == "repeat": rows = (rows[0].model_copy(update={"repeatIndex": 1}),) + rows[1:]
    elif problem == "duplicate": rows = (rows[1],) + rows[1:]
    elif problem == "omitted": rows = rows[:-1]
    metrics = original.metrics if problem == "duplicate" else compute_metrics(rows)
    if problem == "metrics": metrics = metrics.model_copy(update={"correct": 0, "accuracy": 0.0})
    changed = original.model_copy(update={"records": rows, "metrics": metrics})
    changed = changed.model_copy(update={"reportDigest": digest(changed.model_dump(mode="json", exclude={"reportDigest"}))})
    with pytest.raises(DatasetError): verify_run_report(changed)


def test_false_complete_cannot_hide_unattempted_decisions(catalog):
    from app.baselines import digest
    from eval.contracts import DatasetError
    from eval.metrics import compute_metrics
    from eval.run_contracts import verify_run_report
    original = report(catalog)
    missing = original.records[0].model_copy(update={"prediction": "error", "actualAnswer": None,
        "errorCode": "driver_unavailable", "decisionAttempted": False, "modelAttemptCount": 0})
    rows = (missing,) + original.records[1:]
    changed = original.model_copy(update={"records": rows, "metrics": compute_metrics(rows)})
    changed = changed.model_copy(update={"reportDigest": digest(changed.model_dump(mode="json", exclude={"reportDigest"}))})
    with pytest.raises(DatasetError): verify_run_report(changed)


@pytest.mark.parametrize("problem", ["manifest-digest", "dataset", "ids", "budget"])
def test_self_rehashed_report_cannot_hide_manifest_or_case_budget_mismatch(catalog, problem):
    from app.baselines import digest
    from eval.contracts import DatasetError
    from eval.run_contracts import verify_run_report
    original = report(catalog); manifest = original.manifest
    if problem == "manifest-digest": manifest = manifest.model_copy(update={"manifestDigest": "f" * 64})
    elif problem == "dataset": manifest = manifest.model_copy(update={"datasetDigest": "f" * 64})
    elif problem == "ids": manifest = manifest.model_copy(update={"inputCaseIds": manifest.inputCaseIds[:-1], "inputCount": 109})
    else:
        manifest = manifest.model_copy(update={"system": manifest.system.model_copy(update={
            "budget": manifest.system.budget.model_copy(update={"modelAttemptsPerCase": 1})})})
    if problem != "manifest-digest":
        manifest = manifest.model_copy(update={"manifestDigest": digest(manifest.model_dump(mode="json", exclude={"manifestDigest"}))})
    rows = original.records
    if problem == "budget": rows = (rows[0].model_copy(update={"modelAttemptCount": 2}),) + rows[1:]
    changed = original.model_copy(update={"manifest": manifest, "records": rows})
    changed = changed.model_copy(update={"reportDigest": digest(changed.model_dump(mode="json", exclude={"reportDigest"}))})
    with pytest.raises(DatasetError): verify_run_report(changed)


def test_prediction_json_duplicate_schema_boolean_and_unknown_gold_fields_are_refused():
    from eval.run_contracts import PredictionRecord
    original = row(0)
    with pytest.raises(ValueError): PredictionRecord.model_validate_json(original.model_dump_json()[:-1] + ',"schemaVersion":1}')
    with pytest.raises(ValidationError): PredictionRecord.model_validate({**original.model_dump(mode="python"), "schemaVersion": True})


def test_metrics_revalidates_model_copy_and_does_not_emit_sensitive_error_text():
    from eval.contracts import DatasetError
    from eval.metrics import compute_metrics
    modified = row(0).model_copy(update={"durationMs": float("nan"), "errorCode": "synthetic-private-secret"})
    with pytest.raises(DatasetError) as error: compute_metrics((modified,))
    assert str(error.value) == "eval_metrics_invalid"


def test_sealing_refuses_pending_or_corrupt_dataset_proof_even_with_matching_report(catalog):
    from eval.contracts import DatasetError
    from eval.run_contracts import verify_run_report
    original = report(catalog)
    damaged = original.datasetProof.model_copy(update={"casesJson": "[]"})
    with pytest.raises(DatasetError): verify_run_report(original.model_copy(update={"datasetProof": damaged}))


@pytest.mark.parametrize("boundary", ["metrics", "seal", "verify"])
def test_invalid_model_copy_does_not_leak_raw_value_through_serializer_warning(catalog, boundary):
    import warnings
    from eval.contracts import DatasetError
    from eval.metrics import compute_metrics
    from eval.run_contracts import seal_run_report, verify_run_report
    original = report(catalog)
    invalid = original.records[0].model_copy(update={"errorCode": "synthetic-private-secret"})
    rows = (invalid,) + original.records[1:]
    with warnings.catch_warnings(record=True) as emitted:
        warnings.simplefilter("always")
        with pytest.raises(DatasetError):
            if boundary == "metrics": compute_metrics(rows)
            elif boundary == "seal": seal_run_report(original.datasetProof, original.manifest, rows, True)
            else: verify_run_report(original.model_copy(update={"records": rows}))
    assert not emitted, "A validation refusal must not echo raw values through warning/stderr"
