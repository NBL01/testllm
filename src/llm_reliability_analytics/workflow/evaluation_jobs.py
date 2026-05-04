"""Workflow helpers for product-level evaluation jobs."""

from __future__ import annotations

from datetime import datetime, timezone
from typing import Any, Literal, cast

from pydantic import BaseModel

from llm_reliability_analytics.analytics.reliability import ReliabilityReport
from llm_reliability_analytics.reporting.markdown import generate_run_markdown_report
from llm_reliability_analytics.storage.duckdb_store import RunAggregatedSummary, fetch_results_for_run
from llm_reliability_analytics.storage.evaluation_job_repository import (
    EvaluationJob,
    EvaluationJobCreate,
    EvaluationJobStatus,
    create_evaluation_job,
    get_evaluation_job,
    list_evaluation_jobs,
    update_evaluation_job,
)
from llm_reliability_analytics.storage.trace_repository import fetch_traces
from llm_reliability_analytics.workflow.service import (
    RunBatchWorkflowResult,
    RunReportResult,
    run_batch_workflow,
    run_report_workflow,
)


class EvaluationJobRunResult(BaseModel):
    job: EvaluationJob
    result: RunBatchWorkflowResult


class EvaluationJobSummaryResult(BaseModel):
    job: EvaluationJob
    storage_summary: RunAggregatedSummary
    report: ReliabilityReport


class EvaluationJobFailedCase(BaseModel):
    test_case_id: str
    attempt_index: int
    category: str | None = None
    test_source: str | None = None
    oracle_type: str | None = None
    expected_answer: str | None = None
    actual_answer: str | None = None
    is_correct: bool
    score: float
    error_type: str | None = None
    explanation: str | None = None
    latency_ms: float


class EvaluationJobReportPayload(BaseModel):
    job: EvaluationJob
    run_id: str
    markdown_report: str
    storage_summary: RunAggregatedSummary
    report: ReliabilityReport


class EvaluationJobNotFoundError(ValueError):
    """Raised when a requested job does not exist."""


def create_job(payload: EvaluationJobCreate) -> EvaluationJob:
    return create_evaluation_job(payload)


def list_jobs(limit: int = 100, status: EvaluationJobStatus | None = None) -> list[EvaluationJob]:
    normalized_status = status.strip() if isinstance(status, str) else None
    if normalized_status not in {"draft", "queued", "running", "completed", "failed"}:
        normalized_status = None
    return list_evaluation_jobs(limit=limit, status=cast(EvaluationJobStatus | None, normalized_status))


def get_job(job_id: str) -> EvaluationJob:
    job = get_evaluation_job(job_id)
    if job is None:
        raise EvaluationJobNotFoundError(f"Evaluation job not found: {job_id}")
    return job


def run_job(job_id: str) -> EvaluationJobRunResult:
    job = get_evaluation_job(job_id)
    if job is None:
        raise EvaluationJobNotFoundError(f"Evaluation job not found: {job_id}")

    if job.status == "running":
        raise ValueError(f"Evaluation job is already running: {job_id}")
    if job.linked_run_id:
        raise ValueError(f"Evaluation job already executed: {job_id}")

    started_at = datetime.now(timezone.utc)
    update_evaluation_job(job_id, status="running", started_at=started_at, failure_reason=None)
    refreshed = get_evaluation_job(job_id)
    if refreshed is None:
        raise EvaluationJobNotFoundError(f"Evaluation job not found after update: {job_id}")

    run_name = refreshed.project_name.strip() or f"evaluation-job-{job_id[:8]}"
    run_group_id = f"evaluation-job:{job_id}"
    evaluation_mode = cast(
        Literal["regression", "exploratory", "adversarial", "trace_replay"],
        refreshed.evaluation_mode,
    )
    try:
        result = run_batch_workflow(
            input_path=refreshed.input_path,
            run_name=run_name,
            model_name=refreshed.model_name,
            provider=refreshed.provider,
            dataset_version=refreshed.dataset_version,
            evaluation_mode=evaluation_mode,
            temperature=refreshed.temperature,
            max_output_tokens=refreshed.max_output_tokens,
            timeout_seconds=refreshed.timeout_seconds,
            run_mode="real_local" if refreshed.provider in {"ollama", "local"} else "mock",
            notes=refreshed.notes,
            run_group_id=run_group_id,
            limit=refreshed.limit,
            repeats_per_case=refreshed.repeat_count,
        )
    except Exception as exc:  # noqa: BLE001 - state transition must be persisted before bubbling error
        failed = update_evaluation_job(
            job_id,
            status="failed",
            failure_reason=str(exc)[:1000],
            completed_at=datetime.now(timezone.utc),
        )
        if failed is None:
            raise EvaluationJobNotFoundError(f"Evaluation job not found after failure update: {job_id}") from exc
        raise

    completed = update_evaluation_job(
        job_id,
        status="completed",
        linked_run_id=result.run_id,
        failure_reason=None,
        completed_at=datetime.now(timezone.utc),
    )
    if completed is None:
        raise EvaluationJobNotFoundError(f"Evaluation job not found after completion update: {job_id}")

    return EvaluationJobRunResult(job=completed, result=result)


def get_job_summary(job_id: str) -> EvaluationJobSummaryResult:
    job = get_job(job_id)
    run_id = _require_run_id(job)
    run_report = run_report_workflow(run_id)
    return EvaluationJobSummaryResult(
        job=job,
        storage_summary=run_report.storage_summary,
        report=run_report.report,
    )


def get_job_failed_cases(job_id: str, limit: int = 200) -> list[EvaluationJobFailedCase]:
    job = get_job(job_id)
    run_id = _require_run_id(job)
    results = fetch_results_for_run(run_id)
    failed = [result for result in results if not result.is_correct]
    failed_sorted = sorted(
        failed,
        key=lambda result: (result.score, result.latency_ms, result.test_case_id, result.attempt_index),
    )[:limit]
    return [
        EvaluationJobFailedCase(
            test_case_id=result.test_case_id,
            attempt_index=result.attempt_index,
            category=result.category,
            test_source=result.test_source,
            oracle_type=result.oracle_type,
            expected_answer=result.expected_answer,
            actual_answer=result.actual_answer,
            is_correct=result.is_correct,
            score=result.score,
            error_type=result.error_type,
            explanation=result.explanation,
            latency_ms=result.latency_ms,
        )
        for result in failed_sorted
    ]


def get_job_traces(job_id: str, limit: int = 200, only_failed: bool = True) -> list[dict[str, Any]]:
    job = get_job(job_id)
    run_id = _require_run_id(job)
    return fetch_traces(run_id=run_id, only_failed=only_failed, max_rows=limit)


def get_job_report_payload(job_id: str) -> EvaluationJobReportPayload:
    job = get_job(job_id)
    run_id = _require_run_id(job)
    run_report: RunReportResult = run_report_workflow(run_id)
    markdown_report = generate_run_markdown_report(run_id)
    return EvaluationJobReportPayload(
        job=job,
        run_id=run_id,
        markdown_report=markdown_report,
        storage_summary=run_report.storage_summary,
        report=run_report.report,
    )


def _require_run_id(job: EvaluationJob) -> str:
    run_id = (job.linked_run_id or "").strip()
    if not run_id:
        raise ValueError(f"Evaluation job is not completed yet: {job.job_id}")
    return run_id
