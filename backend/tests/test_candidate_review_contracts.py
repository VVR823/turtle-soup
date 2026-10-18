"""Closed human-review intent contracts; no database/model/human acceptance."""
from importlib import import_module
from uuid import uuid4

import pytest
from pydantic import ValidationError


def body(kind):
    value = dict(operationKey=str(uuid4()))
    if kind == "CandidateRollback":
        return {**value, "targetRuleVersion": "r1:" + "b" * 64,
            "expectedRuleVersion": "r1:" + "c" * 64, "expectedPointerVersion": 0,
            "reason": "Synthetic reviewed rollback"}
    value["expectedReviewVersion"] = 0
    if kind in {"CandidateApprove", "CandidateReject"}:
        value["reviewNote"] = "Synthetic independent review"
    if kind in {"CandidateApprove", "CandidatePublish"}:
        value["expectedProofDigest"] = "a" * 64
    if kind == "CandidateApprove":
        value.update(answerSupported=True, contextIndependent=True)
    if kind == "CandidatePublish":
        value.update(expectedRuleVersion="r1:" + "c" * 64, expectedPointerVersion=0)
    return value


def contracts():
    return import_module("app.candidate_review_contracts")


@pytest.mark.parametrize("kind", ["CandidateApprove", "CandidateReject", "CandidatePublish", "CandidateRollback"])
def test_closed_review_intent_preserves_exact_valid_body_without_adding_authority(kind):
    module = contracts()
    value = body(kind)
    parsed = module.checked_candidate_request(getattr(module, kind), value)
    assert parsed.operationKey == value["operationKey"]
    assert all(parsed.model_dump(mode="json")[key] == item for key, item in value.items())
    assert not hasattr(parsed, "draft") and not hasattr(parsed, "reviewReceipt")


@pytest.mark.parametrize("kind,field", [("CandidateApprove", "reviewNote"),
    ("CandidateReject", "reviewNote"), ("CandidateRollback", "reason")])
@pytest.mark.parametrize("note", ["", " \t\n\u3000", "字" * 1001], ids=["empty", "whitespace", "too-long"])
def test_review_reason_is_nonblank_and_not_silently_truncated(kind, field, note):
    module = contracts()
    value = {**body(kind), field: note}
    with pytest.raises(ValidationError):
        getattr(module, kind).model_validate(value)


@pytest.mark.parametrize("field", ["answerSupported", "contextIndependent"])
@pytest.mark.parametrize("value", [False, 1, "true", None])
def test_approval_requires_both_actual_human_true_values_not_coercion(field, value):
    module = contracts()
    with pytest.raises(ValidationError):
        module.CandidateApprove.model_validate({**body("CandidateApprove"), field: value})


@pytest.mark.parametrize("kind,field", [("CandidateApprove", "expectedReviewVersion"),
    ("CandidatePublish", "expectedPointerVersion"), ("CandidateRollback", "expectedPointerVersion")])
@pytest.mark.parametrize("value", [True, -1, 9223372036854775808, "0"])
def test_expected_versions_are_real_bounded_integers(kind, field, value):
    module = contracts()
    with pytest.raises(ValidationError):
        getattr(module, kind).model_validate({**body(kind), field: value})


@pytest.mark.parametrize("extra", ["draft", "reviewReceipt", "approved", "trafficClass"])
def test_client_cannot_supply_server_or_approval_authority(extra):
    module = contracts()
    with pytest.raises(module.CandidateReviewError) as caught:
        module.checked_candidate_request(module.CandidateApprove, {**body("CandidateApprove"), extra: "PRIVATE synthetic"})
    assert caught.value.code == "candidate_input_invalid" and "PRIVATE" not in str(caught.value)


def test_request_consumer_revalidates_forged_copy_and_duplicate_json():
    module = contracts()
    original = module.CandidateApprove.model_validate(body("CandidateApprove"))
    forged = original.model_copy(update={"answerSupported": 1})
    for value in (forged, '{"operationKey":"first","operationKey":"second"}'):
        with pytest.raises(module.CandidateReviewError) as caught:
            module.checked_candidate_request(module.CandidateApprove, value)
        assert caught.value.status == 422


def test_review_note_exact_unicode_limit_preserves_text_and_maximum_version():
    module = contracts()
    value = body("CandidateApprove")
    value.update(reviewNote="证" * 1000, expectedReviewVersion=9223372036854775807)
    parsed = module.checked_candidate_request(module.CandidateApprove, value)
    assert parsed.reviewNote == "证" * 1000 and parsed.expectedReviewVersion == 9223372036854775807
