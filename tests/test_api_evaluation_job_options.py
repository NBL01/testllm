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


def test_every_dataset_preset_creates_a_valid_frozen_job(monkeypatch, tmp_path) -> None:
    monkeypatch.setenv("LLM_RELIABILITY_DB_PATH", str(tmp_path / "presets.duckdb"))
    client = TestClient(app)
    presets = client.get("/evaluation-jobs/options").json()["datasets"]
    assert {"llm_eval_v2_300", "all_oracles_smoke"} <= {preset["id"] for preset in presets}
    for preset in presets:
        response = client.post("/evaluation-jobs", json={
            "input_path": preset["input_path"], "dataset_version": preset["dataset_version"],
            "evaluation_mode": preset["evaluation_mode"], "limit": 2})
        assert response.status_code == 201, (preset["id"], response.text)
        assert response.json()["dataset_sha256"] and response.json()["dataset_version"] == preset["dataset_version"]
