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
    assert load_response.json()["valid_rows"] == 20
    assert load_response.json()["stored_test_cases"] == 20

    run_response = client.post(
        "/run-batch",
        json={
            "input_path": "sample_test_cases.jsonl",
            "mode": "deterministic",
            "seed": 42,
            "limit": 5,
            "run_name": "api-test-run",
            "model_name": "mock-client",
        },
    )
    assert run_response.status_code == 200
    payload = run_response.json()
    assert payload["loaded_test_cases"] == 5
    assert payload["executed_test_cases"] == 5
    run_id = payload["run_id"]

    report_response = client.get(f"/report/{run_id}")
    assert report_response.status_code == 200
    report_payload = report_response.json()
    assert report_payload["run_id"] == run_id
    assert report_payload["storage_summary"]["total_test_cases"] == 5
