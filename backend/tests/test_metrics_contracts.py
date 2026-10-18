"""Literal boundary expectations for private aggregate query contracts."""
import base64
from importlib import import_module
import json

import pytest
from pydantic import ValidationError


def api():
    try:
        return import_module("app.metrics_contracts")
    except ModuleNotFoundError as error:
        if error.name == "app.metrics_contracts":
            pytest.fail("TS16 closed metrics contract is not implemented")
        raise


def test_default_seven_days_and_fifty_groups_and_early_epoch_clamp():
    contract = api()
    query = contract.parse_metrics_query([], now=1_000_000.0)
    assert (query.start, query.end, query.limit) == (395200.0, 1_000_000.0, 50)
    assert (query.soupId, query.puzzleVersion, query.ruleVersion, query.cursor) == (None, None, None, None)
    assert contract.parse_metrics_query([], now=60.0).start == 0.0


@pytest.mark.parametrize("pairs", [
    [("start", "0"), ("end", "2678400"), ("limit", "100")],
    [("start", "0"), ("end", "0"), ("limit", "1")],
    [("start", "253402300799"), ("end", "253402300799")],
])
def test_closed_window_boundaries_are_valid(pairs):
    query = api().parse_metrics_query(pairs, now=1_000_000.0)
    assert 0 <= query.end - query.start <= 2678400
    assert 1 <= query.limit <= 100


@pytest.mark.parametrize("pairs", [
    [("start", "0"), ("end", "2678401")], [("start", "2"), ("end", "1")],
    [("start", "-1")], [("start", "nan")], [("end", "inf")], [("end", "253402300800")],
    [("start", "true")], [("limit", "0")], [("limit", "101")], [("limit", "1.0")],
    [("start", "1"), ("start", "1")], [("unrecognized", "PRIVATE VALUE")],
    [("soupId", "")], [("soupId", "   ")], [("soupId", "x" * 201)],
    [("puzzleVersion", "r1:" + "a" * 64)], [("ruleVersion", "p1:" + "b" * 64)],
    [("cursor", "")], [("cursor", "x" * 2049)],
])
def test_invalid_queries_reject_without_reflecting_values(pairs):
    contract = api()
    with pytest.raises(contract.MetricsError) as caught:
        contract.parse_metrics_query(pairs, now=1_000_000.0)
    assert (caught.value.code, caught.value.status) == ("metrics_query_invalid", 422)
    assert "PRIVATE VALUE" not in str(caught.value)


@pytest.mark.parametrize("values", [{"start": True, "end": 1.0}, {"start": 0.0, "end": False},
    {"start": 0.0, "end": 1.0, "limit": True}, {"start": 0.0, "end": float("nan")},
    {"start": 0.0, "end": 1.0, "unknown": "PRIVATE"}])
def test_direct_models_are_not_a_query_validation_bypass(values):
    with pytest.raises(ValidationError):
        api().MetricsQuery(**values)


def cursor_fixture():
    contract = api()
    query = contract.MetricsQuery(start=86400.0, end=172800.0, soupId="synthetic", limit=100)
    key = contract.MetricsGroupKey(day="1970-01-02", soupId="synthetic", puzzleVersion=None, ruleVersion=None)
    cursor = contract.encode_metrics_cursor(query, key)
    return contract, query, key, cursor


def test_cursor_restores_fixed_window_filters_and_limit_without_sensitive_ids():
    contract, original, key, cursor = cursor_fixture()
    query = contract.parse_metrics_query([("cursor", cursor)], now=9_000_000.0)
    assert (query.start, query.end, query.soupId, query.limit) == (86400.0, 172800.0, "synthetic", 100)
    decoded_query, decoded_key = contract.decode_metrics_cursor(cursor)
    assert decoded_query == original and decoded_key == key
    body = json.loads(base64.urlsafe_b64decode(cursor + "=" * (-len(cursor) % 4)))
    assert set(body) == {"schemaVersion", "query", "key"}
    assert set(body["key"]) == {"day", "soupId", "puzzleVersion", "ruleVersion"}
    assert not any(name in json.dumps(body) for name in ("sessionId", "turnId", "runId", "requestId"))


@pytest.mark.parametrize("pair", [("start", "86401"), ("end", "172801"), ("soupId", "other"),
    ("limit", "50"), ("puzzleVersion", "p1:" + "a" * 64)])
def test_cursor_mismatch_is_rejected(pair):
    contract, _, _, cursor = cursor_fixture()
    with pytest.raises(contract.MetricsError):
        contract.parse_metrics_query([("cursor", cursor), pair], now=9_000_000.0)


@pytest.mark.parametrize("mutation", ["bool_schema", "extra", "wrong_day", "out_of_window", "unknown_key", "noncanonical", "duplicate"])
def test_cursor_tampering_is_closed_and_canonical(mutation):
    contract, _, _, cursor = cursor_fixture()
    raw = base64.urlsafe_b64decode(cursor + "=" * (-len(cursor) % 4)).decode()
    body = json.loads(raw)
    if mutation == "bool_schema": body["schemaVersion"] = True
    elif mutation == "extra": body["privateId"] = "PRIVATE"
    elif mutation == "wrong_day": body["key"]["day"] = "1970-02-31"
    elif mutation == "out_of_window": body["key"]["day"] = "1970-01-03"
    elif mutation == "unknown_key": body["key"]["turnId"] = "PRIVATE"
    if mutation == "duplicate":
        forged = raw[:-1] + ',"schemaVersion":1}'
    elif mutation == "noncanonical":
        forged = json.dumps(body, indent=2)
    else:
        forged = json.dumps(body, separators=(",", ":"), sort_keys=True)
    encoded = base64.urlsafe_b64encode(forged.encode()).decode().rstrip("=")
    with pytest.raises(contract.MetricsError):
        contract.decode_metrics_cursor(encoded)


def test_cursor_encoding_revalidates_model_copy_and_window_day():
    contract, query, key, _ = cursor_fixture()
    with pytest.raises(contract.MetricsError):
        contract.encode_metrics_cursor(query.model_copy(update={"limit": True}), key)
    with pytest.raises(contract.MetricsError):
        contract.encode_metrics_cursor(query, key.model_copy(update={"day": "1970-01-03"}))


@pytest.mark.parametrize("pair", [("cursor", "PRIVATE"), ("limit", "50")])
def test_export_query_cannot_request_truncated_pages(pair):
    contract = api()
    with pytest.raises(contract.MetricsError):
        contract.parse_metrics_query([pair], now=1_000_000.0, export=True)


def test_output_counts_are_closed_and_nonnegative_and_boolean_is_not_count():
    contract = api()
    counts = contract.MetricsCounts()
    assert set(counts.model_dump()) == {"sessionsCreated", "successfulChargedTurns", "httpAttempts",
        "feedbackSubmitted", "tasksCreated", "candidatesCreated", "reviewApproved", "reviewRejected",
        "candidatePublicationEvents"}
    assert all(value == 0 for value in counts.model_dump().values())
    for values in ({"httpAttempts": -1}, {"httpAttempts": True}, {"rawQuestion": "PRIVATE"}):
        with pytest.raises(ValidationError): contract.MetricsCounts(**values)


def test_summary_current_cohort_states_and_publication_denominator_are_consistent():
    contract = api()
    summary = contract.MetricsSummary(counts=contract.MetricsCounts(tasksCreated=2, candidatesCreated=1),
        taskStates=contract.MetricsTaskStates(queued=1, failed=1),
        candidateStates=contract.MetricsCandidateStates(pending=1),
        taskPublication=contract.MetricsPublication(numerator=0, denominator=2, ratio=0.0))
    assert summary.taskStates.failed == 1 and summary.taskPublication.denominator == 2
    with pytest.raises(ValidationError):
        contract.MetricsSummary(counts=contract.MetricsCounts(tasksCreated=2))
    for values in ({"numerator": 0, "denominator": 0, "ratio": 0.0},
        {"numerator": 3, "denominator": 2, "ratio": 1.5},
        {"numerator": 1, "denominator": 2, "ratio": 0.9}):
        with pytest.raises(ValidationError): contract.MetricsPublication(**values)


def test_export_projection_is_complete_closed_and_rejects_a_partial_page():
    contract = api()
    page = contract.MetricsPage(query=contract.MetricsQuery(start=0.0, end=60.0),
        summary=contract.MetricsSummary(), coverage=contract.MetricsCoverage())
    exported = contract.export_projection(page, generated_at=70.0)
    assert set(exported.model_dump()) == {"schemaVersion", "window", "filters", "summary", "coverage",
        "groups", "complete", "generatedAt"}
    assert exported.complete is True and exported.groups == ()
    assert exported.window.end == 60.0 and exported.generatedAt == 70.0
    with pytest.raises(contract.MetricsError) as caught:
        contract.export_projection(page.model_copy(update={"nextCursor": "nonempty"}), generated_at=70.0)
    assert (caught.value.code, caught.value.status) == ("metrics_export_too_large", 409)
    with pytest.raises(ValidationError):
        contract.MetricsPage(query=page.query, summary=page.summary, coverage=page.coverage,
            rawQuestion="PRIVATE")


def test_export_byte_guard_uses_encoded_utf8_and_accepts_exact_boundary(monkeypatch):
    contract = api()
    page = contract.MetricsPage(query=contract.MetricsQuery(start=0.0, end=60.0, soupId="合成公开谜题"),
        summary=contract.MetricsSummary(), coverage=contract.MetricsCoverage())
    exported = contract.export_projection(page, generated_at=70.0)
    serialized = exported.model_dump_json(warnings="error")
    encoded_size = len(serialized.encode("utf-8"))
    assert encoded_size > len(serialized)
    # Lower only the test ceiling to exercise the production guard precisely;
    # this is not a claim that this fixture reaches the actual 512 KiB cap.
    assert contract.MAX_EXPORT_BYTES == 512 * 1024
    monkeypatch.setattr(contract, "MAX_EXPORT_BYTES", encoded_size)
    assert contract.export_projection(page, generated_at=70.0) == exported
    monkeypatch.setattr(contract, "MAX_EXPORT_BYTES", encoded_size - 1)
    with pytest.raises(contract.MetricsError) as caught:
        contract.export_projection(page, generated_at=70.0)
    assert (caught.value.code, caught.value.status) == ("metrics_export_too_large", 409)
