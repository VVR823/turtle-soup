"""Model JSON has five typed tools, never privileged server execution identity."""
import json
from uuid import uuid4

import pytest


def draft_body(**changes):
    body = dict(schemaVersion=1, type="exact_qa", operation="add", targetRuleDigest=None,
        soupId="synthetic", puzzleVersion="p1:" + "a" * 64, baseRuleVersion="r1:" + "b" * 64,
        question="小明是凶手吗？", normalizationVersion="exact-v1", answer="是",
        factIds=["f1:" + "c" * 64], evidenceSummary="Synthetic reference; support still unproven")
    return {**body, **changes}


def action_body(tool="run_regression", **argument_changes):
    args = {"get_turn_trace": {"turnId": str(uuid4())},
        "retrieve_truth": {"soupId": "synthetic", "puzzleVersion": "p1:" + "a" * 64, "query": "小明"},
        "find_rule_conflicts": {"baseRuleVersion": "r1:" + "b" * 64, "draft": draft_body()},
        "run_regression": {"draft": draft_body()},
        "save_candidate_rule": {"draft": draft_body(), "regressionReportId": str(uuid4())}}
    return dict(action="tool", tool=tool, arguments={**args.get(tool, {}), **argument_changes})


@pytest.mark.parametrize("tool", ["get_turn_trace", "retrieve_truth", "find_rule_conflicts", "run_regression", "save_candidate_rule"])
def test_each_tool_has_its_own_validated_arguments(tool):
    from app.agents.contracts import parse_tool_action
    body = action_body(tool)
    action = parse_tool_action(json.dumps(body))
    assert action.tool == tool and action.arguments.model_dump(mode="json") == body["arguments"]
    assert not hasattr(action, "leaseToken") and not hasattr(action, "runId")


@pytest.mark.parametrize("tool", ["shell", "python", "sql", "web_search", "approve", "publish", "rollback", "read_file"])
def test_unknown_or_privileged_tool_cannot_become_an_action(tool):
    from app.agents.contracts import AgentError, parse_tool_action
    with pytest.raises(AgentError): parse_tool_action(json.dumps(action_body(tool)))


@pytest.mark.parametrize("key,value", [("path", "synthetic-private-path"), ("command", "rm"),
    ("datasetPath", "holdout.json"), ("role", "admin"), ("report", {"passed": True}),
    ("maxCalls", 100), ("leaseToken", str(uuid4())), ("runId", str(uuid4()))])
def test_tool_arguments_cannot_choose_authority_tests_or_reports(key, value):
    from app.agents.contracts import AgentError, parse_tool_action
    with pytest.raises(AgentError): parse_tool_action(json.dumps(action_body(**{key: value})))


@pytest.mark.parametrize("field,value", [("schemaVersion", True), ("type", "regex"), ("operation", "delete"),
    ("question", " "), ("question", "x" * 501), ("answer", "不确定"), ("factIds", []),
    ("factIds", ["f1:" + "c" * 64] * 2), ("targetRuleDigest", "d" * 64),
    ("operation", "replace"), ("normalizationVersion", "fuzzy-v1"),
    ("reportId", str(uuid4())), ("confirmedContext", True), ("answerSupported", True)])
def test_draft_rejects_unknown_authority_or_invalid_exact_rule(field, value):
    from app.agents.contracts import AgentError, checked_draft
    with pytest.raises(AgentError): checked_draft(json.dumps(draft_body(**{field: value})))


@pytest.mark.parametrize("raw", [
    '{"action":"tool","action":"finish","tool":"run_regression","arguments":{}}',
    '{"action":"tool","tool":"run_regression","arguments":{"draft":NaN}}',
    '{"action":"tool","tool":"run_regression","arguments":{"draft":Infinity}}',
    '[]', 'null', '"synthetic-private-string"', 'x' * 32769], ids=["duplicate", "nan", "infinity", "array", "null", "string", "oversize"])
def test_raw_json_duplicates_nonfinite_and_size_are_not_silently_coerced(raw):
    from app.agents.contracts import AgentError, parse_tool_action
    with pytest.raises(AgentError) as caught: parse_tool_action(raw)
    assert "synthetic-private" not in str(caught.value)


def test_model_copy_consumer_refuses_quietly_without_private_serializer_warning():
    import warnings
    from app.agents.contracts import AgentError, checked_draft
    legal = checked_draft(json.dumps(draft_body()))
    corrupt = legal.model_copy(update={"answer": {"synthetic-private": "secret"}})
    with warnings.catch_warnings(record=True) as caught:
        warnings.simplefilter("always")
        with pytest.raises(AgentError) as error: checked_draft(corrupt)
    assert not caught and "synthetic-private" not in str(error.value)


@pytest.mark.parametrize("question,want", [(" 小明是凶手吗？？ ", "小明是凶手吗"),
    ("小明不是凶手吗？", "小明不是凶手吗"), ("小王是凶手吗？", "小王是凶手吗"),
    ("故事里有2个人吗？", "故事里有2个人吗"), ("如果下雨，小明死了吗？", "如果下雨，小明死了吗")])
def test_canonical_key_preserves_subject_negation_count_and_condition(question, want):
    from app.agents.contracts import checked_draft
    draft = checked_draft(json.dumps(draft_body(question=question)))
    assert draft.canonicalQuestionKey == want


def test_draft_digest_binds_target_answer_question_and_evidence():
    from app.agents.contracts import checked_draft, draft_digest
    original = checked_draft(json.dumps(draft_body()))
    digests = {draft_digest(original)}
    for changes in ({"answer": "不是"}, {"question": "小王是凶手吗？"}, {"factIds": ["f1:" + "d" * 64]},
        {"operation": "replace", "targetRuleDigest": "e" * 64}, {"evidenceSummary": "Different synthetic claim"}):
        digests.add(draft_digest(checked_draft(json.dumps(draft_body(**changes)))))
    assert len(digests) == 6


@pytest.mark.parametrize("body", [{"modelAttemptsUsed": 11}, {"toolAttemptsUsed": 9},
    {"modelAttemptsUsed": True}, {"modelAttemptLimit": 11}, {"deadlineAt": 200.0},
    {"firstStartedAt": 100.0, "deadlineAt": 281.0}, {"firstStartedAt": float("inf"), "deadlineAt": float("inf")},
    {"modelAttemptsUsed": 1}])
def test_checkpoint_cannot_refresh_expand_or_fabricate_started_budget(body):
    from pydantic import ValidationError
    from app.agents.contracts import AgentCheckpoint
    with pytest.raises(ValidationError): AgentCheckpoint(**body)


def test_started_checkpoint_and_exhausted_budget_remain_valid_records():
    from app.agents.contracts import AgentCheckpoint
    value = AgentCheckpoint(modelAttemptsUsed=10, toolAttemptsUsed=8, firstStartedAt=100.0, deadlineAt=280.0)
    assert value.modelAttemptsUsed == 10 and value.deadlineAt == 280.0
    assert AgentCheckpoint().firstStartedAt is None


@pytest.mark.parametrize("body", [{"action": "finish", "candidateId": str(uuid4()), "needsHumanReason": "unclear"},
    {"action": "finish"}, {"action": "finish", "publish": True},
    {"action": "finish", "candidateId": "foreign-format"}])
def test_finish_is_exactly_candidate_or_human_reason_not_publication(body):
    from app.agents.contracts import AgentError, parse_agent_action
    with pytest.raises(AgentError): parse_agent_action(json.dumps(body))


def test_finish_actions_are_typed_but_do_not_attest_candidate_ownership():
    from app.agents.contracts import parse_agent_action
    candidate = str(uuid4())
    assert parse_agent_action(json.dumps({"action": "finish", "candidateId": candidate})).candidateId == candidate
    assert parse_agent_action(json.dumps({"action": "finish", "needsHumanReason": "Evidence insufficient"})).candidateId is None


def report_body(**changes):
    body = dict(schemaVersion=1, reportId=str(uuid4()), runId=str(uuid4()),
        draftDigest="a" * 64, contextDigest="b" * 64, suiteManifestDigest="c" * 64,
        puzzleVersion="p1:" + "d" * 64, baseRuleVersion="r1:" + "e" * 64,
        evidenceKind="synthetic_fixture", status="complete", inputCaseCount=1,
        attemptedCaseCount=1, passedCaseCount=1, elapsedSeconds=0.1,
        truncated=False, cleanupConfirmed=True,
        caseResults=[dict(caseId=str(uuid4()), suite="fixed_safety", passed=True, code="passed")])
    return {**body, **changes}


@pytest.mark.parametrize("changes", [{"schemaVersion": True}, {"inputCaseCount": True},
    {"inputCaseCount": 0}, {"attemptedCaseCount": 0}, {"passedCaseCount": 0},
    {"truncated": True}, {"cleanupConfirmed": False}, {"elapsedSeconds": 5.1},
    {"elapsedSeconds": float("inf")}, {"stdout": "synthetic-private-output"},
    {"answerSupported": True}, {"humanApproved": True}])
def test_complete_report_cannot_fabricate_denominators_timing_cleanup_or_approval(changes):
    from app.agents.contracts import AgentError, RegressionReport, checked_model
    with pytest.raises(AgentError): checked_model(RegressionReport, report_body(**changes))


def test_report_partial_results_keep_full_input_and_failed_results_are_not_passes():
    from app.agents.contracts import RegressionReport, checked_model
    partial = checked_model(RegressionReport, report_body(status="incomplete", inputCaseCount=2, truncated=True))
    assert partial.inputCaseCount == 2 and partial.attemptedCaseCount == 1 and partial.truncated
    body = report_body(status="failed", passedCaseCount=0)
    body["caseResults"][0].update(passed=False, code="counterexample")
    failed = checked_model(RegressionReport, body)
    assert failed.passedCaseCount == 0 and failed.caseResults[0].passed is False


def test_report_case_rows_are_unique_and_actual_pass_count_is_recomputed():
    from app.agents.contracts import AgentError, RegressionReport, checked_model
    body = report_body(inputCaseCount=2, attemptedCaseCount=2, passedCaseCount=2)
    body["caseResults"] *= 2
    with pytest.raises(AgentError): checked_model(RegressionReport, body)
    body["caseResults"][1] = {**body["caseResults"][0], "caseId": str(uuid4()), "passed": False, "code": "counterexample"}
    with pytest.raises(AgentError): checked_model(RegressionReport, body)


def test_execution_identity_is_internal_only_and_has_bounded_sequence():
    from app.agents.contracts import AgentError, ExecutionIdentity, checked_model, parse_tool_action
    body = dict(runId=str(uuid4()), operationKey=str(uuid4()), leaseToken=str(uuid4()), seq=0)
    identity = checked_model(ExecutionIdentity, body)
    assert identity.seq == 0
    with pytest.raises(AgentError): checked_model(ExecutionIdentity, {**body, "seq": True})
    with pytest.raises(AgentError): checked_model(ExecutionIdentity, {**body, "seq": 9223372036854775808})
    with pytest.raises(AgentError): parse_tool_action(json.dumps({**action_body(), **body}))


def test_candidate_record_is_pending_and_binds_exact_draft_report_and_run():
    from app.agents.contracts import AgentError, CandidateRecord, checked_draft, checked_model, candidate_digest
    draft = checked_draft(json.dumps(draft_body()))
    body = dict(schemaVersion=1, id=str(uuid4()), runId=str(uuid4()), draft=draft.model_dump(mode="json"),
        regressionReportId=str(uuid4()), reportDigest="d" * 64, status="pending", createdAt=100.0)
    body["candidateDigest"] = candidate_digest(draft, run_id=body["runId"],
        report_id=body["regressionReportId"], report_digest=body["reportDigest"])
    record = checked_model(CandidateRecord, body)
    assert record.status == "pending"
    for changed in ({"status": "approved"}, {"reportDigest": "e" * 64}, {"runId": str(uuid4())},
        {"regressionReportId": str(uuid4())}, {"draft": draft_body(answer="不是")}, {"schemaVersion": True}):
        with pytest.raises(AgentError): checked_model(CandidateRecord, {**body, **changed})


def test_checkpoint_retry_history_cannot_double_key_or_hide_attempts():
    from pydantic import ValidationError
    from app.agents.contracts import AgentCheckpoint, RetryCount
    retry = RetryCount(kind="tool", keyDigest="a" * 64, used=1)
    for changes in ({"retryCounts": (retry, retry)}, {"toolAttemptsUsed": 0, "retryCounts": (retry,)},
        {"totalSeconds": True}, {"firstStartedAt": True}):
        body = dict(firstStartedAt=100.0, deadlineAt=280.0, toolAttemptsUsed=1)
        with pytest.raises(ValidationError): AgentCheckpoint(**{**body, **changes})


def test_report_copy_is_revalidated_instead_of_trusting_immutable_class_name():
    from app.agents.contracts import AgentError, RegressionReport, checked_model
    legal = checked_model(RegressionReport, report_body())
    with pytest.raises(AgentError): checked_model(RegressionReport, legal.model_copy(update={"truncated": True}))


def test_candidate_digest_refuses_invalid_id_or_digest_without_echoing_input():
    from app.agents.contracts import AgentError, candidate_digest, checked_draft
    draft = checked_draft(json.dumps(draft_body()))
    body = dict(run_id=str(uuid4()), report_id=str(uuid4()), report_digest="d" * 64)
    for field in body:
        with pytest.raises(AgentError) as caught:
            candidate_digest(draft, **{**body, field: "synthetic-private-bad-value"})
        assert "synthetic-private" not in str(caught.value)


def test_multibyte_input_is_byte_bounded_not_only_character_bounded():
    from app.agents.contracts import AgentError, parse_tool_action
    body = action_body("retrieve_truth", query="中文" * 8000)
    raw = json.dumps(body, ensure_ascii=False)
    assert len(raw) < 32768 < len(raw.encode("utf-8"))
    with pytest.raises(AgentError): parse_tool_action(raw)
