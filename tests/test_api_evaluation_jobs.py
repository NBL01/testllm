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


def test_evaluation_job_queue_and_process(monkeypatch, tmp_path) -> None:
    db_path = tmp_path / "api_eval_jobs_queue.duckdb"
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
            "limit": 2,
        },
    )
    assert create_response.status_code == 201
    job_id = create_response.json()["job_id"]

    queue_response = client.post(f"/evaluation-jobs/{job_id}/queue")
    assert queue_response.status_code == 200
    queue_payload = queue_response.json()
    assert queue_payload["status"] == "queued"

    process_response = client.post("/evaluation-jobs/process-queue?max_jobs=5")
    assert process_response.status_code == 200
    process_payload = process_response.json()
    assert process_payload["processed_count"] == 1
    assert process_payload["requested_max_jobs"] == 5
    assert process_payload["results"][0]["job"]["job_id"] == job_id
    assert process_payload["results"][0]["job"]["status"] == "completed"
    assert process_payload["results"][0]["job"]["linked_run_id"] is not None

    get_response = client.get(f"/evaluation-jobs/{job_id}")
    assert get_response.status_code == 200
    get_payload = get_response.json()
    assert get_payload["status"] == "completed"

    requeue_response = client.post(f"/evaluation-jobs/{job_id}/queue")
    assert requeue_response.status_code == 400
    assert "cannot be queued" in requeue_response.json()["detail"]


def test_evaluation_job_queue_stats_and_empty_processor(monkeypatch, tmp_path) -> None:
    db_path = tmp_path / "api_eval_jobs_stats.duckdb"
    monkeypatch.setenv("LLM_RELIABILITY_DB_PATH", str(db_path))
    client = TestClient(app)

    empty_process_response = client.post("/evaluation-jobs/process-queue?max_jobs=3")
    assert empty_process_response.status_code == 200
    empty_process_payload = empty_process_response.json()
    assert empty_process_payload["requested_max_jobs"] == 3
    assert empty_process_payload["processed_count"] == 0
    assert empty_process_payload["results"] == []

    create_response = client.post(
        "/evaluation-jobs",
        json={
            "input_path": "sample_test_cases.jsonl",
            "provider": "mock",
            "model_name": "mock-baseline",
            "evaluation_mode": "regression",
            "oracle_profile": "default",
            "repeat_count": 1,
            "limit": 1,
        },
    )
    assert create_response.status_code == 201
    job_id = create_response.json()["job_id"]

    stats_after_create = client.get("/evaluation-jobs/queue/stats")
    assert stats_after_create.status_code == 200
    create_stats_payload = stats_after_create.json()
    assert create_stats_payload["total"] == 1
    assert create_stats_payload["by_status"]["draft"] == 1
    assert create_stats_payload["by_status"]["queued"] == 0
    assert create_stats_payload["by_status"]["completed"] == 0

    queue_response = client.post(f"/evaluation-jobs/{job_id}/queue")
    assert queue_response.status_code == 200

    stats_after_queue = client.get("/evaluation-jobs/queue/stats")
    assert stats_after_queue.status_code == 200
    queue_stats_payload = stats_after_queue.json()
    assert queue_stats_payload["total"] == 1
    assert queue_stats_payload["by_status"]["draft"] == 0
    assert queue_stats_payload["by_status"]["queued"] == 1

    process_response = client.post("/evaluation-jobs/process-queue?max_jobs=1")
    assert process_response.status_code == 200
    assert process_response.json()["processed_count"] == 1

    stats_after_process = client.get("/evaluation-jobs/queue/stats")
    assert stats_after_process.status_code == 200
    process_stats_payload = stats_after_process.json()
    assert process_stats_payload["total"] == 1
    assert process_stats_payload["by_status"]["queued"] == 0
    assert process_stats_payload["by_status"]["completed"] == 1


def test_evaluation_job_cancel_from_draft_and_queue_blocked(monkeypatch, tmp_path) -> None:
    db_path = tmp_path / "api_eval_jobs_cancel.duckdb"
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
            "limit": 1,
        },
    )
    assert create_response.status_code == 201
    job_id = create_response.json()["job_id"]

    cancel_response = client.post(
        f"/evaluation-jobs/{job_id}/cancel",
        json={"reason": "dataset selected by mistake"},
    )
    assert cancel_response.status_code == 200
    cancel_payload = cancel_response.json()
    assert cancel_payload["status"] == "canceled"
    assert "dataset selected by mistake" in (cancel_payload["failure_reason"] or "")

    queue_response = client.post(f"/evaluation-jobs/{job_id}/queue")
    assert queue_response.status_code == 400
    assert "cannot be queued" in queue_response.json()["detail"]

    process_response = client.post("/evaluation-jobs/process-queue?max_jobs=5")
    assert process_response.status_code == 200
    process_payload = process_response.json()
    assert process_payload["processed_count"] == 0

    stats_response = client.get("/evaluation-jobs/queue/stats")
    assert stats_response.status_code == 200
    stats_payload = stats_response.json()
    assert stats_payload["by_status"]["canceled"] == 1
