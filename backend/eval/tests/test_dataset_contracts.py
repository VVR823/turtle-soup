"""Mutations of input/review/proof must invalidate evaluation eligibility."""
import json
import socket
from pathlib import Path

import pytest
from pydantic import ValidationError


def test_pending_proposal_is_preserved_but_cannot_be_confirmed(pending, catalog):
    from eval.contracts import DatasetError, validate_reviewed_case
    assert pending.review is None and pending.reviewState == "pending"
    assert pending.proposedLabel.answer == "是"
    with pytest.raises(DatasetError):
        validate_reviewed_case(pending, catalog=catalog)


def test_complete_synthetic_review_is_frozen_and_source_bound(reviewed, catalog):
    from eval.catalog import validate_catalog
    from eval.contracts import validate_reviewed_case
    assert validate_catalog(catalog) == catalog
    assert validate_reviewed_case(reviewed, catalog=catalog) == reviewed
    with pytest.raises(ValidationError):
        reviewed.question = "Changed"
    with pytest.raises(ValidationError):
        reviewed.review.expectedLabel.answer = "不是"


@pytest.mark.parametrize("field,value", [
    ("schemaVersion", True), ("schemaVersion", "1"), ("split", "unknown"),
    ("authorRole", "model_confirmed"), ("caseId", "D0000000-0000-4000-8000-000000000001"),
    ("question", ""), ("question", " " * 10), ("question", "x" * 501),
    ("categories", ("x",) * 9), ("categories", ("same", "same")),
    ("origin", "legacy"), ("visibility", "public_authorized"),
    ("contextIndex", True), ("conversationId", "orphan"), ("reviewState", "reviewed"),
], ids=["schema-bool", "schema-string", "split", "author", "uuid", "empty", "blank", "size",
        "category-size", "category-duplicate", "legacy-holdout", "public-holdout", "index-bool", "orphan", "no-review"])
def test_case_contract_rejects_unknown_coerced_or_inconsistent_material(pending, field, value):
    from eval.contracts import EvalCase
    body = pending.model_dump(mode="python"); body[field] = value
    with pytest.raises(ValidationError):
        EvalCase.model_validate(body)


@pytest.mark.parametrize("body", [
    {"kind": "answer", "answer": None}, {"kind": "answer", "answer": "不知道"},
    {"kind": "reminder", "answer": "是"}, {"kind": "system_error", "answer": None},
])
def test_expected_label_cannot_accept_failure_or_mismatched_answer(body):
    from eval.contracts import ExpectedLabel
    with pytest.raises(ValidationError):
        ExpectedLabel.model_validate(body)


def test_reminder_requires_no_answer_but_a_review_reason(pending, catalog):
    from eval.contracts import ExpectedLabel, ReviewRecord, case_digest, validate_reviewed_case
    item = pending.model_copy(update={"proposedLabel": ExpectedLabel(kind="reminder", answer=None), "caseType": "control"})
    receipt = ReviewRecord(operatorId="synthetic-test-only", reviewedAt="2026-10-09T00:00:00Z",
        caseDigest=case_digest(item), expectedLabel=item.proposedLabel, factIds=(),
        reviewNote="Synthetic non yes/no request.", humanConfirmed=True)
    assert validate_reviewed_case(item.model_copy(update={"reviewState": "reviewed", "review": receipt}), catalog=catalog).review.factIds == ()
    with pytest.raises(ValidationError):
        ReviewRecord.model_validate({**receipt.model_dump(mode="python"), "reviewNote": "   "})


@pytest.mark.parametrize("field,value", [
    ("question", "Was a different light switched off?"), ("familyGroup", "another-family"),
    ("sourceGroup", "another-source"), ("evidenceSourceDigest", "b" * 64),
    ("puzzleVersion", "p1:" + "b" * 64), ("proposedLabel", None),
    ("categories", ("changed",)), ("rawLegacyExpected", "not-original"),
    ("conversationId", "new-context"),
], ids=["question", "family", "source", "source-digest", "p1", "proposal", "category", "raw-claim", "context"])
def test_review_is_invalid_after_model_copy_changes_business_fields(reviewed, catalog, field, value):
    from eval.contracts import DatasetError, validate_reviewed_case
    with pytest.raises(DatasetError):
        validate_reviewed_case(reviewed.model_copy(update={field: value}), catalog=catalog)


@pytest.mark.parametrize("change", ["missing-fact", "unknown-fact", "false-human", "coerced-human", "pending-receipt"])
def test_tampered_review_cannot_grant_eligibility(reviewed, catalog, change):
    from eval.contracts import DatasetError, validate_reviewed_case
    if change == "pending-receipt":
        modified = reviewed.model_copy(update={"reviewState": "pending"})
    else:
        update = {"missing-fact": {"factIds": ()}, "unknown-fact": {"factIds": ("f1:" + "b" * 64,)},
                  "false-human": {"humanConfirmed": False}, "coerced-human": {"humanConfirmed": 1}}[change]
        modified = reviewed.model_copy(update={"review": reviewed.review.model_copy(update=update)})
    with pytest.raises(DatasetError):
        validate_reviewed_case(modified, catalog=catalog)


def test_digest_excludes_only_review_transition(pending, reviewed):
    from eval.contracts import case_digest
    assert case_digest(pending) == case_digest(reviewed)
    assert case_digest(pending.model_copy(update={"authorRole": "human"})) != case_digest(pending)


@pytest.mark.parametrize("index", [1, 2, 3])
def test_context_accepts_only_explicit_three_round_metadata(pending, index):
    from eval.contracts import EvalCase
    body = pending.model_dump(mode="python")
    body.update(caseType="context", conversationId="group-one", contextIndex=index)
    assert EvalCase.model_validate(body).contextIndex == index
    body["contextIndex"] = 4
    with pytest.raises(ValidationError):
        EvalCase.model_validate(body)


@pytest.mark.parametrize("field,value", [("reviewedAt", "2026-10-09T00:00:00"),
    ("reviewedAt", "2026-02-30T00:00:00Z"), ("operatorId", " "), ("reviewNote", "x" * 1001)])
def test_manual_receipt_requires_bounded_identity_and_real_utc(reviewed, field, value):
    from eval.contracts import ReviewRecord
    body = reviewed.review.model_dump(mode="python"); body[field] = value
    with pytest.raises(ValidationError):
        ReviewRecord.model_validate(body)


def test_source_digest_preserves_complete_unique_case_id_inventory(pending):
    from eval.contracts import SourceDigest
    body = dict(sourceId="new-file", sourceDigest="a" * 64, questionSourceGroup="batch-one",
        origin="new_authoring", collectedAt="2026-10-09T00:00:00Z", visibility="private", caseIds=(pending.caseId,))
    assert SourceDigest(**body).caseIds == (pending.caseId,)
    with pytest.raises(ValidationError):
        SourceDigest(**{**body, "caseIds": (pending.caseId, pending.caseId)})


def test_duplicate_json_keys_nonfinite_values_and_extra_fields_are_refused(pending):
    from eval.contracts import EvalCase
    raw = pending.model_dump_json()
    with pytest.raises((ValidationError, ValueError)):
        EvalCase.model_validate_json(raw[:-1] + ',"question":"second"}')
    with pytest.raises((ValidationError, ValueError)):
        EvalCase.model_validate_json(raw[:-1] + ',"extra":NaN}')
    with pytest.raises(ValidationError):
        EvalCase.model_validate_json(raw[:-1] + ',"extra":1}')


@pytest.mark.parametrize("mutation", ["soup-body", "rule-proof", "duplicate-soup", "unknown-soup-field", "noncanonical"])
def test_catalog_rechecks_complete_source_and_rule_proof(catalog, mutation):
    from eval.catalog import validate_catalog
    from eval.contracts import DatasetError
    from app.baselines import canonical_json
    item = catalog[0]
    if mutation == "duplicate-soup":
        changed = (item, item)
    elif mutation == "rule-proof":
        rule = item.ruleSnapshot.model_copy(update={"releaseRulesJson": "{}"})
        changed = (item.model_copy(update={"ruleSnapshot": rule}),)
    else:
        payload = json.loads(item.soupJson)
        if mutation == "soup-body": payload["bottom"] = "Changed truth"
        if mutation == "unknown-soup-field": payload["unknown"] = "must not be ignored"
        raw = json.dumps(payload) if mutation == "noncanonical" else canonical_json(payload)
        changed = (item.model_copy(update={"soupJson": raw}),)
    with pytest.raises(DatasetError):
        validate_catalog(changed)


def test_eval_tests_keep_root_network_and_runtime_file_guards():
    from testing.guards import TestAccessBlocked
    with pytest.raises(TestAccessBlocked):
        socket.getaddrinfo("example.com", 443)
    with pytest.raises(TestAccessBlocked):
        (Path(__file__).resolve().parents[3] / "backend" / "data" / "guard-probe.json").read_bytes()


@pytest.mark.parametrize("body", [
    {"authorRole": "legacy"}, {"authorRole": "synthetic"},
    {"categories": ("  ",)}, {"split": "holdout"},
])
def test_pending_source_cannot_misrepresent_author_or_formal_holdout(pending, body):
    from eval.contracts import EvalCase
    with pytest.raises(ValidationError):
        EvalCase.model_validate({**pending.model_dump(mode="python"), **body})


@pytest.mark.parametrize("field,value", [("schemaVersion", True), ("humanConfirmed", 1),
    ("factIds", ("f1:" + "a" * 64,) * 9), ("factIds", ("f1:" + "a" * 64,) * 2)])
def test_review_receipt_schema_confirmation_and_fact_limits_are_real(reviewed, field, value):
    from eval.contracts import ReviewRecord
    with pytest.raises(ValidationError):
        ReviewRecord.model_validate({**reviewed.review.model_dump(mode="python"), field: value})


def test_changed_context_index_invalidates_a_prior_context_receipt(pending, reviewed, catalog):
    from eval.contracts import DatasetError, EvalCase, case_digest, validate_reviewed_case, review_context_digest
    body = pending.model_dump(mode="python")
    body.update(caseType="context", conversationId="context-review", contextIndex=1)
    item = EvalCase.model_validate(body)
    receipt = reviewed.review.model_copy(update={"caseDigest": case_digest(item)})
    item = item.model_copy(update={"reviewState": "reviewed", "review": receipt})
    group = tuple(item.model_copy(update={"caseId": f"d0000000-0000-4000-8000-{n:012d}", "contextIndex": n}) for n in (1, 2, 3))
    group = tuple(c.model_copy(update={"review": receipt.model_copy(update={"caseDigest": case_digest(c)})}) for c in group)
    group = tuple(c.model_copy(update={"review": c.review.model_copy(update={"contextDigest": review_context_digest(c, group)})}) for c in group)
    item = group[0]
    assert validate_reviewed_case(item, catalog=catalog, context_cases=group).contextIndex == 1
    with pytest.raises(DatasetError):
        validate_reviewed_case(item.model_copy(update={"contextIndex": 2}), catalog=catalog, context_cases=group)


def test_fact_existence_does_not_mean_the_pipeline_certifies_semantics(reviewed, catalog):
    from eval.contracts import ExpectedLabel, validate_reviewed_case
    # A deliberately wrong synthetic human declaration is still a declaration.
    # Code verifies provenance; a real human must verify semantic entailment.
    receipt = reviewed.review.model_copy(update={"expectedLabel": ExpectedLabel(kind="answer", answer="不是")})
    assert validate_reviewed_case(reviewed.model_copy(update={"review": receipt}), catalog=catalog).review.expectedLabel.answer == "不是"
