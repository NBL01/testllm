import time

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
    assert list_payload["offset"] == 0
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
    assert failed_cases_payload["offset"] == 0
    for item in failed_cases_payload["items"]:
        assert item["is_correct"] is False

    traces_response = client.get(f"/evaluation-jobs/{job_id}/traces")
    assert traces_response.status_code == 200
    traces_payload = traces_response.json()
    assert traces_payload["total"] >= 0
    assert traces_payload["offset"] == 0
    for item in traces_payload["items"]:
        assert item["run_id"] == run_payload["job"]["linked_run_id"]
        assert item["is_correct"] is False

    report_response = client.get(f"/evaluation-jobs/{job_id}/report")
    assert report_response.status_code == 200
    report_payload = report_response.json()
    assert report_payload["run_id"] == run_payload["job"]["linked_run_id"]
    assert "LLM Reliability Report" in report_payload["markdown_report"]

    client_report_response = client.get(f"/evaluation-jobs/{job_id}/client-report?failed_case_limit=5")
    assert client_report_response.status_code == 200
    client_report_payload = client_report_response.json()
    assert client_report_payload["run_id"] == run_payload["job"]["linked_run_id"]
    assert "generated_at" in client_report_payload
    assert client_report_payload["failed_case_total"] >= 0
    assert len(client_report_payload["failed_cases_sample"]) <= 5
    assert "LLM Reliability Report" in client_report_payload["markdown_report"]


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


def test_evaluation_job_queue_processing_is_fifo(monkeypatch, tmp_path) -> None:
    db_path = tmp_path / "api_eval_jobs_queue_fifo.duckdb"
    monkeypatch.setenv("LLM_RELIABILITY_DB_PATH", str(db_path))
    client = TestClient(app)

    created_job_ids: list[str] = []
    for project_name in ["fifo-first", "fifo-second", "fifo-third"]:
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
                "project_name": project_name,
            },
        )
        assert create_response.status_code == 201
        job_id = create_response.json()["job_id"]
        created_job_ids.append(job_id)
        queue_response = client.post(f"/evaluation-jobs/{job_id}/queue")
        assert queue_response.status_code == 200
        time.sleep(0.01)

    process_response = client.post("/evaluation-jobs/process-queue?max_jobs=2")
    assert process_response.status_code == 200
    payload = process_response.json()
    assert payload["processed_count"] == 2
    processed_ids = [item["job"]["job_id"] for item in payload["results"]]
    assert processed_ids == created_job_ids[:2]

    remaining_response = client.get("/evaluation-jobs?status=queued&limit=10&offset=0")
    assert remaining_response.status_code == 200
    remaining_payload = remaining_response.json()
    assert remaining_payload["total"] == 1
    assert remaining_payload["items"][0]["job_id"] == created_job_ids[2]


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


def test_evaluation_job_list_can_filter_by_status(monkeypatch, tmp_path) -> None:
    db_path = tmp_path / "api_eval_jobs_filter.duckdb"
    monkeypatch.setenv("LLM_RELIABILITY_DB_PATH", str(db_path))
    client = TestClient(app)

    first_create = client.post(
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
    second_create = client.post(
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
    assert first_create.status_code == 201
    assert second_create.status_code == 201
    job_id_to_queue = first_create.json()["job_id"]

    queue_response = client.post(f"/evaluation-jobs/{job_id_to_queue}/queue")
    assert queue_response.status_code == 200

    queued_only_response = client.get("/evaluation-jobs?status=queued")
    assert queued_only_response.status_code == 200
    queued_payload = queued_only_response.json()
    assert queued_payload["total"] == 1
    assert queued_payload["items"][0]["job_id"] == job_id_to_queue
    assert queued_payload["items"][0]["status"] == "queued"

    draft_only_response = client.get("/evaluation-jobs?status=draft")
    assert draft_only_response.status_code == 200
    draft_payload = draft_only_response.json()
    assert draft_payload["total"] == 1
    assert draft_payload["items"][0]["status"] == "draft"

    all_page_one_response = client.get("/evaluation-jobs?limit=1&offset=0")
    assert all_page_one_response.status_code == 200
    all_page_one_payload = all_page_one_response.json()
    assert all_page_one_payload["total"] == 2
    assert all_page_one_payload["limit"] == 1
    assert all_page_one_payload["offset"] == 0
    assert len(all_page_one_payload["items"]) == 1

    all_page_two_response = client.get("/evaluation-jobs?limit=1&offset=1")
    assert all_page_two_response.status_code == 200
    all_page_two_payload = all_page_two_response.json()
    assert all_page_two_payload["total"] == 2
    assert all_page_two_payload["limit"] == 1
    assert all_page_two_payload["offset"] == 1
    assert len(all_page_two_payload["items"]) == 1

    created_asc_response = client.get("/evaluation-jobs?sort_by=created_at&sort_order=asc&limit=2&offset=0")
    assert created_asc_response.status_code == 200
    created_asc_payload = created_asc_response.json()
    assert created_asc_payload["total"] == 2
    assert created_asc_payload["items"][0]["job_id"] == first_create.json()["job_id"]

    updated_desc_response = client.get("/evaluation-jobs?sort_by=updated_at&sort_order=desc&limit=2&offset=0")
    assert updated_desc_response.status_code == 200
    updated_desc_payload = updated_desc_response.json()
    assert updated_desc_payload["total"] == 2
    assert updated_desc_payload["items"][0]["status"] == "queued"


def test_evaluation_job_can_be_duplicated_as_new_draft(monkeypatch, tmp_path) -> None:
    db_path = tmp_path / "api_eval_jobs_duplicate.duckdb"
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
            "repeat_count": 2,
            "limit": 3,
            "submitted_by": "qa-user",
            "team_name": "reliability",
            "client_name": "internal",
            "project_name": "duplicate-check",
        },
    )
    assert create_response.status_code == 201
    original = create_response.json()

    duplicate_response = client.post(f"/evaluation-jobs/{original['job_id']}/duplicate")
    assert duplicate_response.status_code == 201
    duplicated = duplicate_response.json()

    assert duplicated["job_id"] != original["job_id"]
    assert duplicated["status"] == "draft"
    assert duplicated["linked_run_id"] is None
    assert duplicated["input_path"] == original["input_path"]
    assert duplicated["provider"] == original["provider"]
    assert duplicated["model_name"] == original["model_name"]
    assert duplicated["evaluation_mode"] == original["evaluation_mode"]
    assert duplicated["oracle_profile"] == original["oracle_profile"]
    assert duplicated["repeat_count"] == original["repeat_count"]
    assert duplicated["limit"] == original["limit"]
    assert duplicated["submitted_by"] == original["submitted_by"]
    assert duplicated["team_name"] == original["team_name"]
    assert duplicated["client_name"] == original["client_name"]
    assert duplicated["project_name"] == original["project_name"]


def test_evaluation_job_retry_creates_new_queued_job(monkeypatch, tmp_path) -> None:
    db_path = tmp_path / "api_eval_jobs_retry.duckdb"
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
            "project_name": "retry-source",
        },
    )
    assert create_response.status_code == 201
    source_job = create_response.json()

    run_response = client.post(f"/evaluation-jobs/{source_job['job_id']}/run")
    assert run_response.status_code == 200

    retry_response = client.post(
        f"/evaluation-jobs/{source_job['job_id']}/retry",
        json={"queue": True},
    )
    assert retry_response.status_code == 201
    retried = retry_response.json()
    assert retried["job_id"] != source_job["job_id"]
    assert retried["status"] == "queued"
    assert retried["linked_run_id"] is None
    assert retried["project_name"] == source_job["project_name"]
    assert retried["input_path"] == source_job["input_path"]


def test_evaluation_job_traces_can_filter_by_test_case_id(monkeypatch, tmp_path) -> None:
    db_path = tmp_path / "api_eval_jobs_trace_filter.duckdb"
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
            "limit": 4,
        },
    )
    assert create_response.status_code == 201
    job_id = create_response.json()["job_id"]

    run_response = client.post(f"/evaluation-jobs/{job_id}/run")
    assert run_response.status_code == 200

    unfiltered_response = client.get(f"/evaluation-jobs/{job_id}/traces?limit=100&only_failed=false")
    assert unfiltered_response.status_code == 200
    unfiltered_payload = unfiltered_response.json()
    assert unfiltered_payload["total"] > 0
    target_test_case_id = unfiltered_payload["items"][0]["test_case_id"]

    filtered_response = client.get(
        f"/evaluation-jobs/{job_id}/traces?limit=100&only_failed=false&test_case_id={target_test_case_id}"
    )
    assert filtered_response.status_code == 200
    filtered_payload = filtered_response.json()
    assert filtered_payload["total"] > 0
    assert all(item["test_case_id"] == target_test_case_id for item in filtered_payload["items"])

    paged_filtered_response = client.get(
        f"/evaluation-jobs/{job_id}/traces?limit=1&offset=0&only_failed=false&test_case_id={target_test_case_id}"
    )
    assert paged_filtered_response.status_code == 200
    paged_filtered_payload = paged_filtered_response.json()
    assert paged_filtered_payload["limit"] == 1
    assert paged_filtered_payload["offset"] == 0
    assert paged_filtered_payload["total"] >= 1
    assert len(paged_filtered_payload["items"]) == 1


def test_evaluation_job_create_rejects_missing_dataset_path(monkeypatch, tmp_path) -> None:
    db_path = tmp_path / "api_eval_jobs_invalid_path.duckdb"
    monkeypatch.setenv("LLM_RELIABILITY_DB_PATH", str(db_path))
    client = TestClient(app)

    create_response = client.post(
        "/evaluation-jobs",
        json={
            "input_path": "does-not-exist.jsonl",
            "provider": "mock",
            "model_name": "mock-baseline",
            "evaluation_mode": "regression",
            "oracle_profile": "default",
            "repeat_count": 1,
        },
    )
    assert create_response.status_code == 400
    assert "Input file not found" in create_response.json()["detail"]


def test_evaluation_job_create_rejects_empty_local_model_name(monkeypatch, tmp_path) -> None:
    db_path = tmp_path / "api_eval_jobs_invalid_local_model.duckdb"
    monkeypatch.setenv("LLM_RELIABILITY_DB_PATH", str(db_path))
    client = TestClient(app)

    create_response = client.post(
        "/evaluation-jobs",
        json={
            "input_path": "sample_test_cases.jsonl",
            "provider": "local",
            "model_name": "   ",
            "evaluation_mode": "regression",
            "oracle_profile": "default",
            "repeat_count": 1,
        },
    )
    assert create_response.status_code == 400
    assert "model_name is required when provider=local" in create_response.json()["detail"]
