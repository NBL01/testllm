from fastapi.testclient import TestClient

from llm_reliability_analytics.main import app


def test_evaluation_job_options_endpoint_returns_core_choices(monkeypatch, tmp_path) -> None:
    db_path = tmp_path / "api_eval_job_options.duckdb"
    monkeypatch.setenv("LLM_RELIABILITY_DB_PATH", str(db_path))
    client = TestClient(app)

    response = client.get("/evaluation-jobs/options")
    assert response.status_code == 200
    payload = response.json()

    assert "mock" in payload["providers"]
    assert "ollama" in payload["providers"]
    assert "local" in payload["providers"]
    assert "mock-baseline" in payload["models_by_provider"]["mock"]
    assert "default" in payload["oracle_profiles"]
    assert "regression" in payload["evaluation_modes"]
    assert "exact_match" in payload["oracle_types"]
    assert any(path.endswith("sample_test_cases.jsonl") for path in payload["dataset_paths"])
    assert "v1" in payload["dataset_versions"]


def test_evaluation_job_options_endpoint_supports_oracle_profile_env_override(monkeypatch, tmp_path) -> None:
    db_path = tmp_path / "api_eval_job_options_oracle_profiles.duckdb"
    monkeypatch.setenv("LLM_RELIABILITY_DB_PATH", str(db_path))
    monkeypatch.setenv("LLM_RELIABILITY_ORACLE_PROFILES", "default,strict,finance-risk")
    client = TestClient(app)

    response = client.get("/evaluation-jobs/options")
    assert response.status_code == 200
    payload = response.json()

    assert "default" in payload["oracle_profiles"]
    assert payload["oracle_profiles"] == ["default"]
