"""Persisted-data metrics boundary; frontend frames cannot supply report truth."""

import ast
import json
from pathlib import Path

import pandas as pd
import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from llm_reliability_analytics.models.domain import TestResult as Result
from llm_reliability_analytics.storage.duckdb_store import create_test_run, insert_batch_results


@pytest.fixture
def client(monkeypatch, tmp_path):
    monkeypatch.setenv("LLM_RELIABILITY_DB_PATH", str(tmp_path / "metrics.duckdb"))
    from llm_reliability_analytics.api.internal import router
    app = FastAPI()
    app.include_router(router)
    with TestClient(app) as client:
        yield client


def persist(run_id="a", *, metadata=None, config=None, correct=True, model="model-a", attempts=1, run_settings=None):
    if metadata is None:
        metadata = {"dataset_sha256": "a" * 64, "configuration": {
            "oracle_profile": "default", "timeout_seconds": 30, "seed": 42}}
    settings = {"provider": "mock", "mode": "mock", "repeat_count": attempts, **(run_settings or {})}
    create_test_run(name=run_id, run_id=run_id, model_name=model, metadata=metadata, **settings)
    results = [Result(run_id=run_id, test_case_id="case", attempt_index=i, category="math",
                      test_source="regression", oracle_type="exact_match", prompt="2 + 2?",
                      expected_answer="4", actual_answer="4" if correct else "5",
                      is_correct=correct, score=float(correct), latency_ms=10,
                      latency_source="mock_simulated", error_type=None if correct else "wrong_answer",
                      oracle_details_json=json.dumps({"input_config": {} if config is None else config}))
               for i in range(1, attempts + 1)]
    insert_batch_results(results)
    return results


def test_report_and_insights_use_persisted_results(client):
    persist(correct=False)
    response = client.get("/internal/metrics/runs/a")
    assert response.status_code == 200, response.text
    assert response.json()["failed"] == 1
    assert response.json()["metric_version"] == "legacy-v1"
    insights = client.get("/internal/metrics/runs/a/insights")
    assert insights.status_code == 200, insights.text
    assert insights.json()["weakest_category"] == "math"
    assert insights.json()["most_frequent_error_type"] == "wrong_answer"
    assert "Promote" not in insights.json()["promotion_hint"]
    assert client.get("/internal/metrics/runs/missing").status_code == 404


def test_matched_stored_configuration_allows_comparison(client):
    persist(correct=False)
    persist("b", model="model-b")
    response = client.post("/internal/metrics/compare", json={"run_ids": ["a", "b"]})
    assert response.status_code == 200, response.text
    payload = response.json()
    assert payload["eligibility"] == {"eligible": True, "research_only": False, "issues": []}
    assert payload["baseline_report"]["accuracy"] == 0
    assert payload["candidate_report"]["accuracy"] == 1
    assert payload["comparison_report"]["compared_runs"] == 2


@pytest.mark.parametrize("change,expected", [
    ({"metadata": {"dataset_sha256": "b" * 64, "configuration": {
        "oracle_profile": "default", "timeout_seconds": 30, "seed": 42}}}, "dataset_sha256"),
    ({"config": {"strict_exact": True}}, "input_config"),
    ({"metadata": {}}, "unknown"),
    ({"metadata": {"dataset_sha256": "a" * 64, "configuration": {
        "oracle_profile": "default", "timeout_seconds": 60, "seed": 42}}}, "timeout_seconds"),
    ({"attempts": 2}, "repeat_count"),
    ({"run_settings": {"provider": "ollama"}}, "provider"),
    ({"run_settings": {"dataset_version": "v2"}}, "dataset_version"),
    ({"run_settings": {"temperature": 0.9}}, "temperature"),
    ({"run_settings": {"max_output_tokens": 256}}, "max_output_tokens"),
    ({"run_settings": {"evaluation_mode": "adversarial"}}, "evaluation_mode"),
])
def test_mismatched_or_unknown_evidence_is_research_only(client, change, expected):
    persist()
    persist("b", **change)
    eligibility = client.post("/internal/metrics/eligibility", json={"run_ids": ["a", "b"]})
    assert eligibility.status_code == 200, eligibility.text
    assert eligibility.json()["research_only"] is True
    assert expected in " ".join(eligibility.json()["issues"])
    assert client.post("/internal/metrics/compare", json={"run_ids": ["a", "b"]}).status_code == 409
    models = client.post("/internal/metrics/models", json={"run_ids": ["a", "b"]})
    assert models.status_code == 409
    improvement = client.post("/internal/metrics/improvement", json={"run_id": "b", "previous_run_id": "a"})
    assert improvement.status_code == 200
    assert improvement.json()["status"] == "research_only"


def test_missing_oracle_config_on_both_sides_is_not_equality(client):
    persist()
    persist("b")
    from llm_reliability_analytics.storage.db import get_connection
    conn = get_connection()
    try:
        conn.execute("UPDATE test_results SET oracle_details_json = '{}' ")
    finally:
        conn.close()
    response = client.post("/internal/metrics/eligibility", json={"run_ids": ["a", "b"]})
    assert response.status_code == 200, response.text
    assert response.json()["research_only"]
    assert "input_config" in " ".join(response.json()["issues"])


def test_canonical_config_key_order_and_attempt_coverage(client):
    persist(config={"schema": {"type": "object", "required": ["x"]}})
    persist("b", config={"schema": {"required": ["x"], "type": "object"}})
    assert client.post("/internal/metrics/eligibility", json={"run_ids": ["a", "b"]}).json()["eligible"]
    from llm_reliability_analytics.storage.db import get_connection
    conn = get_connection()
    try:
        conn.execute("UPDATE test_results SET attempt_index = 2 WHERE run_id = 'b'")
    finally:
        conn.close()
    response = client.post("/internal/metrics/eligibility", json={"run_ids": ["a", "b"]})
    assert "evidence" in " ".join(response.json()["issues"])


def test_model_medians_are_computed_on_backend_and_disclosed(client):
    persist(correct=False)
    persist("b", correct=True)
    response = client.post("/internal/metrics/models", json={"run_ids": ["a", "b"]})
    assert response.status_code == 200, response.text
    models = response.json()["models"]
    assert len(models) == 1
    assert models[0]["model_name"] == "model-a"
    assert set(models[0]["run_ids"]) == {"a", "b"}
    assert models[0]["report"]["accuracy"] == 1
    assert models[0]["report"]["latency_sources"] == {"median_aggregated": 1}
    assert models[0]["report"]["error_distribution"] == {}
    assert "synthetic" in " ".join(models[0]["report"]["measurement_notes"]).lower()


def test_frontend_uses_http_despite_forged_dataframe_and_report(client, monkeypatch):
    from frontend.services.api_client import APIClient
    from frontend.services.metrics_adapter import MetricsAdapter
    persist(correct=False)
    calls = []

    def request(self, method, path, **kwargs):
        calls.append((method, path, kwargs))
        response = client.request(method, path, **kwargs)
        assert response.is_success, response.text
        return response.json()

    monkeypatch.setattr(APIClient, "request", request)
    fake = pd.DataFrame([{"run_id": "a", "score": 1, "is_correct": True}])
    report = MetricsAdapter().build_report_for_run(fake, "a")
    assert report.failed == 1
    assert dict(report.error_distribution.items()) == {"wrong_answer": 1}
    assert report.oracle_type_pass_rate.get("exact_match") == 0
    report.accuracy = 1
    insights = MetricsAdapter().build_insights(report, "improved", fake)
    assert insights.most_frequent_error_type == "wrong_answer"
    assert calls[0][1] == "/internal/metrics/runs/a"
    assert all("score" not in str(kwargs) for _, _, kwargs in calls)


def test_frontend_no_longer_executes_business_metrics():
    path = Path(__file__).resolve().parents[1] / "frontend/services/metrics_adapter.py"
    tree = ast.parse(path.read_text())
    forbidden = {"compute_reliability_report", "compute_run_comparison_report", "generate_run_insights", "TestResult"}
    for node in ast.walk(tree):
        if isinstance(node, ast.ImportFrom):
            assert not forbidden.intersection(alias.name for alias in node.names)
        if isinstance(node, ast.Call) and isinstance(node.func, ast.Name):
            assert node.func.id not in forbidden


def test_metrics_outage_has_no_local_fallback(monkeypatch):
    from frontend.services.api_client import APIClient, BackendAPIError
    from frontend.services.metrics_adapter import MetricsAdapter
    def unavailable(*args, **kwargs):
        raise BackendAPIError("offline")
    monkeypatch.setattr(APIClient, "request", unavailable)
    with pytest.raises(BackendAPIError, match="offline"):
        MetricsAdapter().build_report_for_run(pd.DataFrame(), "a")


def test_actual_jobs_ignore_identity_and_compare_per_case_oracles(client):
    from llm_reliability_analytics.storage.evaluation_job_repository import EvaluationJobCreate
    from llm_reliability_analytics.workflow.evaluation_jobs import create_job, run_job

    run_ids = []
    for model in ["mock-baseline", "mock-failing"]:
        job = create_job(EvaluationJobCreate(
            input_path="sample_test_cases.jsonl", model_name=model, project_name=model,
        ))
        run_ids.append(run_job(job.job_id).job.linked_run_id)
    compared = client.post("/internal/metrics/compare", json={"run_ids": run_ids})
    assert compared.status_code == 200, compared.text
    assert compared.json()["eligibility"]["eligible"]
    models = client.post("/internal/metrics/models", json={"run_ids": run_ids})
    assert models.status_code == 200, models.text
    assert {item["model_name"]: item["run_ids"] for item in models.json()["models"]} == {
        "mock-baseline": [run_ids[0]], "mock-failing": [run_ids[1]],
    }


def test_run_without_results_has_empty_report_and_cannot_compare(client):
    create_test_run(name="empty", run_id="empty", model_name="mock-baseline")
    response = client.get("/internal/metrics/runs/empty")
    assert response.status_code == 200, response.text
    assert response.json()["total_test_cases"] == 0
    eligibility = client.post("/internal/metrics/eligibility", json={"run_ids": ["empty"]})
    assert eligibility.json()["research_only"]


def test_changed_expected_answer_disqualifies_comparison(client):
    persist()
    rows = persist("b")
    rows[0].expected_answer = "5"
    insert_batch_results(rows)
    response = client.post("/internal/metrics/eligibility", json={"run_ids": ["a", "b"]})
    assert "evidence" in " ".join(response.json()["issues"])


def test_adapter_preserves_comparison_conflicts(monkeypatch):
    from frontend.services.api_client import APIClient, BackendAPIError
    from frontend.services.metrics_adapter import IncompatibleRunsError, MetricsAdapter

    def incompatible(*args, **kwargs):
        raise BackendAPIError("different input_config", status_code=409)

    monkeypatch.setattr(APIClient, "request", incompatible)
    runs = pd.DataFrame([{"run_id": rid, "model_name": "same", "created_at": "2026-09-20"}
                         for rid in ["a", "b"]])
    adapter = MetricsAdapter()
    with pytest.raises(IncompatibleRunsError, match="input_config"):
        adapter.compare_runs(pd.DataFrame(), runs, "a", "b")
    with pytest.raises(IncompatibleRunsError, match="input_config"):
        adapter.build_multi_run_model_reports(pd.DataFrame(), runs)


@pytest.mark.parametrize("run_ids", [[], [" "], ["a", "a"]])
def test_invalid_metrics_selection_is_rejected_before_storage(client, run_ids):
    assert client.post("/internal/metrics/compare", json={"run_ids": run_ids}).status_code == 422
