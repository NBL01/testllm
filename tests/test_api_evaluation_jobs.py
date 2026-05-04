from fastapi.testclient import TestClient

from llm_reliability_analytics.main import app


def test_evaluation_job_create_list_and_get(monkeypatch, tmp_path) -> None:
    db_path = tmp_path / "api_eval_jobs.duckdb"
    monkeypatch.setenv("LLM_RELIABILITY_DB_PATH", str(db_path))
    client = TestClient(app)

    create_response = client.post(
        "/evaluation-jobs",
        json={
            "input_path": "sample_test_cases.jsonl",
            "provider": "mock",
            "model_name": "mock-baseline",
            "evaluation_mode": "regression",
            "oracle_profile": "default",
            "submitted_by": "qa-user",
            "team_name": "reliability",
            "client_name": "internal",
            "project_name": "mvp-jobs",
            "repeat_count": 1,
        },
    )
    assert create_response.status_code == 201
    created_payload = create_response.json()
    assert created_payload["status"] == "draft"
    assert created_payload["submitted_by"] == "qa-user"
    assert created_payload["team_name"] == "reliability"
    assert created_payload["client_name"] == "internal"
    assert created_payload["project_name"] == "mvp-jobs"
    assert created_payload["linked_run_id"] is None
    job_id = created_payload["job_id"]

    list_response = client.get("/evaluation-jobs")
    assert list_response.status_code == 200
    list_payload = list_response.json()
    assert list_payload["total"] == 1
    assert list_payload["items"][0]["job_id"] == job_id

    get_response = client.get(f"/evaluation-jobs/{job_id}")
    assert get_response.status_code == 200
    get_payload = get_response.json()
    assert get_payload["job_id"] == job_id
    assert get_payload["status"] == "draft"


def test_evaluation_job_run_links_test_run(monkeypatch, tmp_path) -> None:
    db_path = tmp_path / "api_eval_jobs_run.duckdb"
    monkeypatch.setenv("LLM_RELIABILITY_DB_PATH", str(db_path))
    client = TestClient(app)

    create_response = client.post(
        "/evaluation-jobs",
        json={
            "input_path": "sample_test_cases.jsonl",
            "provider": "mock",
            "model_name": "mock-baseline",
            "evaluation_mode": "regression",
            "oracle_profile": "default",
            "repeat_count": 1,
            "limit": 3,
        },
    )
    assert create_response.status_code == 201
    job_id = create_response.json()["job_id"]

    run_response = client.post(f"/evaluation-jobs/{job_id}/run")
    assert run_response.status_code == 200
    run_payload = run_response.json()
    assert run_payload["job"]["job_id"] == job_id
    assert run_payload["job"]["status"] == "completed"
    assert run_payload["job"]["linked_run_id"] is not None
    assert run_payload["result"]["loaded_test_cases"] == 3
    assert run_payload["result"]["executed_test_cases"] == 3

    get_response = client.get(f"/evaluation-jobs/{job_id}")
    assert get_response.status_code == 200
    get_payload = get_response.json()
    assert get_payload["status"] == "completed"
    assert get_payload["linked_run_id"] == run_payload["job"]["linked_run_id"]

    rerun_response = client.post(f"/evaluation-jobs/{job_id}/run")
    assert rerun_response.status_code == 400
    assert "already executed" in rerun_response.json()["detail"]

    summary_response = client.get(f"/evaluation-jobs/{job_id}/summary")
    assert summary_response.status_code == 200
    summary_payload = summary_response.json()
    assert summary_payload["job"]["job_id"] == job_id
    assert summary_payload["report"]["total_test_cases"] == 3
    assert summary_payload["storage_summary"]["total_test_cases"] == 3

    failed_cases_response = client.get(f"/evaluation-jobs/{job_id}/failed-cases")
    assert failed_cases_response.status_code == 200
    failed_cases_payload = failed_cases_response.json()
    assert failed_cases_payload["total"] >= 0
    for item in failed_cases_payload["items"]:
        assert item["is_correct"] is False

    traces_response = client.get(f"/evaluation-jobs/{job_id}/traces")
    assert traces_response.status_code == 200
    traces_payload = traces_response.json()
    assert traces_payload["total"] >= 0
    for item in traces_payload["items"]:
        assert item["run_id"] == run_payload["job"]["linked_run_id"]
        assert item["is_correct"] is False

    report_response = client.get(f"/evaluation-jobs/{job_id}/report")
    assert report_response.status_code == 200
    report_payload = report_response.json()
    assert report_payload["run_id"] == run_payload["job"]["linked_run_id"]
    assert "LLM Reliability Report" in report_payload["markdown_report"]
