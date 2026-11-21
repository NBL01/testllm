"""Backend-owned run comparison: eligibility and case changes come from persisted evidence."""

import json

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
    assert payload["case_changes"] == {"regressions": [], "improvements": [
        {"test_case_id": "case", "category": "math", "attempts": 1, "baseline_passed": 0, "candidate_passed": 1}]}


def test_real_providers_compare_across_serving_stacks_but_not_against_mock(client):
    persist(run_settings={"provider": "ollama", "mode": "real_local"})
    persist("b", model="model-b", run_settings={"provider": "openai_compatible", "mode": "real_api"})
    assert client.post("/internal/metrics/eligibility", json={"run_ids": ["a", "b"]}).json()["eligible"] is True
    persist("c", model="model-c")  # mock
    issues = client.post("/internal/metrics/eligibility", json={"run_ids": ["a", "c"]}).json()["issues"]
    assert "provider" in issues and "mode" in issues


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
    assert compared.json()["case_changes"]["regressions"]  # mock-failing fails every case mock-baseline passed


def test_run_without_results_cannot_compare(client):
    create_test_run(name="empty", run_id="empty", model_name="mock-baseline")
    eligibility = client.post("/internal/metrics/eligibility", json={"run_ids": ["empty"]})
    assert eligibility.json()["research_only"]


def test_changed_expected_answer_disqualifies_comparison(client):
    persist()
    rows = persist("b")
    rows[0].expected_answer = "5"
    insert_batch_results(rows)
    response = client.post("/internal/metrics/eligibility", json={"run_ids": ["a", "b"]})
    assert "evidence" in " ".join(response.json()["issues"])


@pytest.mark.parametrize("run_ids", [[], [" "], ["a", "a"]])
def test_invalid_metrics_selection_is_rejected_before_storage(client, run_ids):
    assert client.post("/internal/metrics/compare", json={"run_ids": run_ids}).status_code == 422
