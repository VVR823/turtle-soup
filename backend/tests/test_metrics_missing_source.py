"""Absence of authoritative post-publication observations is not a zero count."""
import json

import pytest
from pydantic import ValidationError

from app.metrics_contracts import MetricsPage, MetricsSummary
from .test_metrics_http import metrics_api, ADMIN

UNKNOWN = dict(state="unknown", failedRuns=None, observedRuns=None, reason="source_not_integrated")


@pytest.mark.parametrize("path", ["/api/metrics/admin", "/api/metrics/admin/export"])
def test_actual_private_page_and_complete_export_mark_unintegrated_source_unknown(metrics_api, path):
    response = metrics_api[1].get(path, params={"start": 1000, "end": 1100}, headers=ADMIN)
    assert response.status_code == 200, response.text
    body = response.json()
    assert body["schemaVersion"] == 3
    assert body["summary"].get("postPublicationRegression") == {**UNKNOWN, 'reason': 'schema_5_required'}
    assert body["summary"]["counts"]["sessionsCreated"] == 0  # Known counter still has a real zero.
    if path.endswith("/export"):
        assert body["complete"] is True and body["groups"] == []
    assert metrics_api[0].state.runtime.model.calls == []


def test_default_summary_does_not_manufacture_regression_zero_or_coverage():
    assert MetricsSummary().model_dump().get("postPublicationRegression") == UNKNOWN


def test_private_v3_page_can_be_revalidated_before_complete_export(metrics_api):
    response = metrics_api[1].get("/api/metrics/admin", params={"start": 1000, "end": 1100}, headers=ADMIN)
    assert response.status_code == 200
    checked = MetricsPage.model_validate_json(response.content)
    checked = MetricsPage.model_validate(checked.model_dump())
    assert checked.schemaVersion == 3
    assert checked.summary.postPublicationRegression.failedRuns is None


@pytest.mark.parametrize("version", [1, 2, True, 3.0, "3"])
def test_private_v3_page_rejects_old_or_coerced_wire_version(metrics_api, version):
    response = metrics_api[1].get("/api/metrics/admin", params={"start": 1000, "end": 1100}, headers=ADMIN)
    assert response.status_code == 200
    body = {**response.json(), "schemaVersion": version}
    with pytest.raises(ValidationError):
        MetricsPage.model_validate_json(json.dumps(body))


@pytest.mark.parametrize("change", [{"failedRuns": 0}, {"observedRuns": 0}, {"failedRuns": False},
    {"state": "complete"}, {"reason": "verified_real_source"}, {"privateReport": "PRIVATE_CANARY"}])
def test_unintegrated_source_cannot_accept_unproven_count_or_private_provenance(change):
    value = {**UNKNOWN, **change}
    with pytest.raises(ValidationError):
        MetricsSummary(postPublicationRegression=value)
