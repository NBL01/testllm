from __future__ import annotations

import pytest

from llm_reliability_analytics.storage.evaluation_job_repository import EvaluationJobCreate, update_evaluation_job
from llm_reliability_analytics.workflow import evaluation_jobs as workflow


def _create_default_job() -> workflow.EvaluationJob:
    return workflow.create_job(
        EvaluationJobCreate(
            input_path="sample_test_cases.jsonl",
            provider="mock",
            model_name="mock-baseline",
            evaluation_mode="regression",
            oracle_profile="default",
            repeat_count=1,
            limit=1,
        )
    )


def test_run_job_marks_failed_when_batch_workflow_raises(monkeypatch, tmp_path) -> None:
    db_path = tmp_path / "workflow_eval_jobs_run_failure.duckdb"
    monkeypatch.setenv("LLM_RELIABILITY_DB_PATH", str(db_path))
    job = _create_default_job()

    def _raise(*args, **kwargs):  # noqa: ANN002, ANN003 - test stub
        raise RuntimeError("forced workflow failure for test")

    monkeypatch.setattr(workflow, "run_batch_workflow", _raise)

    with pytest.raises(RuntimeError, match="forced workflow failure for test"):
        workflow.run_job(job.job_id)

    failed = workflow.get_job(job.job_id)
    assert failed.status == "failed"
    assert failed.linked_run_id is None
    assert failed.failure_reason is not None
    assert "forced workflow failure for test" in failed.failure_reason
    assert failed.started_at is not None
    assert failed.completed_at is not None


def test_cancel_job_rejects_running_status(monkeypatch, tmp_path) -> None:
    db_path = tmp_path / "workflow_eval_jobs_cancel_running.duckdb"
    monkeypatch.setenv("LLM_RELIABILITY_DB_PATH", str(db_path))
    job = _create_default_job()

    updated = update_evaluation_job(job.job_id, status="running")
    assert updated is not None
    assert updated.status == "running"

    with pytest.raises(ValueError, match="running; stop worker first"):
        workflow.cancel_job(job.job_id, reason="stop it")


def test_retry_job_can_create_new_draft_copy(monkeypatch, tmp_path) -> None:
    db_path = tmp_path / "workflow_eval_jobs_retry_copy.duckdb"
    monkeypatch.setenv("LLM_RELIABILITY_DB_PATH", str(db_path))
    source = workflow.create_job(
        EvaluationJobCreate(
            input_path="sample_test_cases.jsonl",
            provider="mock",
            model_name="mock-baseline",
            evaluation_mode="regression",
            oracle_profile="strict",
            repeat_count=2,
            limit=5,
            submitted_by="qa-user",
            team_name="reliability",
            client_name="internal",
            project_name="retry-service-test",
        )
    )

    retried = workflow.retry_job(source.job_id, queue=False)
    assert retried.job_id != source.job_id
    assert retried.status == "draft"
    assert retried.linked_run_id is None
    assert retried.oracle_profile == source.oracle_profile
    assert retried.repeat_count == source.repeat_count
    assert retried.limit == source.limit
    assert retried.submitted_by == source.submitted_by
    assert retried.team_name == source.team_name
    assert retried.client_name == source.client_name
    assert retried.project_name == source.project_name


def test_process_queued_jobs_zero_or_negative_max_defaults_to_one(monkeypatch, tmp_path) -> None:
    db_path = tmp_path / "workflow_eval_jobs_process_defaults.duckdb"
    monkeypatch.setenv("LLM_RELIABILITY_DB_PATH", str(db_path))
    first = _create_default_job()
    second = _create_default_job()
    workflow.queue_job(first.job_id)
    workflow.queue_job(second.job_id)

    result = workflow.process_queued_jobs(max_jobs=0)
    assert result.requested_max_jobs == 1
    assert result.processed_count == 1
    assert len(result.results) == 1

