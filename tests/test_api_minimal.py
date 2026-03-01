from fastapi.testclient import TestClient

from llm_reliability_analytics.main import app


def test_minimal_api_flow(monkeypatch, tmp_path) -> None:
    db_path = tmp_path / "api_flow.duckdb"
    monkeypatch.setenv("LLM_RELIABILITY_DB_PATH", str(db_path))
    client = TestClient(app)

    health_response = client.get("/health")
    assert health_response.status_code == 200
    assert health_response.json() == {"status": "ok"}

    load_response = client.post(
        "/load-test-cases",
        json={"input_path": "sample_test_cases.jsonl"},
    )
    assert load_response.status_code == 200
    load_payload = load_response.json()
    assert load_payload["valid_rows"] == 20
    assert load_payload["stored_test_cases"] == 20
    assert "v1" in load_payload["dataset_versions"]

    run_response = client.post(
        "/run-batch",
        json={
            "input_path": "sample_test_cases.jsonl",
            "mode": "deterministic",
            "seed": 42,
            "limit": 5,
            "run_name": "api-test-run",
            "model_name": "mock-client",
            "dataset_version": "v1",
            "run_group_id": "api-baseline",
            "repeats_per_case": 2,
        },
    )
    assert run_response.status_code == 200
    payload = run_response.json()
    assert payload["loaded_test_cases"] == 5
    assert payload["executed_test_cases"] == 10
    assert payload["report"]["unique_test_cases"] == 5
    assert payload["report"]["attempts_per_case"] == 2.0
    assert payload["storage_summary"]["dataset_version"] == "v1"
    assert payload["storage_summary"]["repetition_index"] == 1
    run_id = payload["run_id"]

    report_response = client.get(f"/report/{run_id}")
    assert report_response.status_code == 200
    report_payload = report_response.json()
    assert report_payload["run_id"] == run_id
    assert report_payload["storage_summary"]["total_test_cases"] == 10
