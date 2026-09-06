"""Workflow helpers for product-level evaluation jobs."""

from __future__ import annotations

from datetime import datetime, timezone
import hashlib
import json
import re
from uuid import uuid4
from typing import Any, Literal, cast

from pydantic import BaseModel

from llm_reliability_analytics.analytics.reliability import ReliabilityReport
from llm_reliability_analytics.ingestion.loader import resolve_input_path, load_test_cases
from llm_reliability_analytics.models.domain import TestCase
from llm_reliability_analytics.storage.db import get_connection
from llm_reliability_analytics.reporting.markdown import generate_run_markdown_report
from llm_reliability_analytics.storage.duckdb_store import RunAggregatedSummary, fetch_results_for_run, create_test_run
from llm_reliability_analytics.storage.evaluation_job_repository import (
    EvaluationJob,
    EvaluationJobCreate,
    EvaluationJobStatus,
    count_evaluation_jobs,
    create_evaluation_job,
    evaluation_job_status_counts,
    get_evaluation_job,
    list_evaluation_jobs,
    update_evaluation_job,
)
from llm_reliability_analytics.storage.trace_repository import fetch_traces_page
from llm_reliability_analytics.workflow.service import (
    RunBatchWorkflowResult,
    RunReportResult,
    run_batch_workflow,
    run_report_workflow,
)


class EvaluationJobRunResult(BaseModel):
    job: EvaluationJob
    result: RunBatchWorkflowResult


class EvaluationJobQueueProcessResult(BaseModel):
    requested_max_jobs: int
    processed_count: int
    results: list[EvaluationJobRunResult]
    failures: list[dict[str, str]] = []


class EvaluationJobQueueStatsResult(BaseModel):
    total: int
    by_status: dict[str, int]


class EvaluationJobCancelRequest(BaseModel):
    reason: str = ""


class EvaluationJobRetryRequest(BaseModel):
    queue: bool = False


class EvaluationJobListResult(BaseModel):
    total: int
    limit: int
    offset: int
    items: list[EvaluationJob]


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


class EvaluationJobClientReportPayload(BaseModel):
    job: EvaluationJob
    run_id: str
    generated_at: datetime
    storage_summary: RunAggregatedSummary
    report: ReliabilityReport
    failed_case_total: int
    failed_cases_sample: list[EvaluationJobFailedCase]
    markdown_report: str


class EvaluationJobFailedCasesResult(BaseModel):
    total: int
    limit: int
    offset: int
    items: list[EvaluationJobFailedCase]


class EvaluationJobTracesResult(BaseModel):
    total: int
    limit: int
    offset: int
    items: list[dict[str, Any]]


class EvaluationJobNotFoundError(ValueError):
    """Raised when a requested job does not exist."""


def create_job(payload: EvaluationJobCreate) -> EvaluationJob:
    _validate_job_create_payload(payload)
    cases, summary = load_test_cases(payload.input_path)
    if not cases or summary.invalid_rows:
        raise ValueError(f"Dataset must contain valid cases only ({summary.invalid_rows} invalid rows).")
    if len({case.id for case in cases}) != len(cases):
        raise ValueError("Dataset contains duplicate test case IDs.")
    if payload.limit is not None:
        cases = cases[:payload.limit]
    if payload.dataset_version:
        for case in cases:
            case.dataset_version = payload.dataset_version
    elif len({case.dataset_version for case in cases}) != 1:
        raise ValueError("Dataset has mixed versions; provide an explicit dataset_version.")
    payload = payload.model_copy(update={"dataset_version": cases[0].dataset_version})
    snapshot = [case.model_dump(mode="json") for case in cases]
    fingerprint = hashlib.sha256(json.dumps(snapshot, sort_keys=True, separators=(",", ":")).encode()).hexdigest()
    return create_evaluation_job(payload, dataset_sha256=fingerprint, dataset_snapshot=snapshot)


def duplicate_job(job_id: str) -> EvaluationJob:
    source = get_job(job_id)
    payload = EvaluationJobCreate(
        input_path=source.input_path,
        provider=cast(Literal["mock", "ollama", "local"], source.provider),
        model_name=source.model_name,
        dataset_version=source.dataset_version,
        evaluation_mode=cast(
            Literal["regression", "exploratory", "adversarial", "trace_replay"],
            source.evaluation_mode,
        ),
        oracle_profile=source.oracle_profile,
        temperature=source.temperature,
        max_output_tokens=source.max_output_tokens,
        timeout_seconds=source.timeout_seconds,
        repeat_count=source.repeat_count,
        limit=source.limit,
        notes=source.notes,
        submitted_by=source.submitted_by,
        team_name=source.team_name,
        client_name=source.client_name,
        project_name=source.project_name,
    )
    if not source.dataset_snapshot:
        return create_job(payload)
    duplicated = create_evaluation_job(payload, dataset_sha256=source.dataset_sha256,
                                      dataset_snapshot=source.dataset_snapshot, source_job_id=source.job_id)
    return duplicated


def retry_job(job_id: str, queue: bool = False) -> EvaluationJob:
    duplicated = duplicate_job(job_id)
    if queue:
        queued = queue_job(duplicated.job_id)
        if queued is None:
            raise EvaluationJobNotFoundError(f"Evaluation job not found after retry queue update: {duplicated.job_id}")
        return queued
    return duplicated


def list_jobs(
    limit: int = 100,
    status: EvaluationJobStatus | None = None,
    offset: int = 0,
    sort_by: str = "created_at",
    sort_order: str = "desc",
    search_query: str | None = None,
) -> EvaluationJobListResult:
    normalized_status = status.strip() if isinstance(status, str) else None
    if normalized_status not in {"draft", "queued", "running", "completed", "failed", "canceled"}:
        normalized_status = None
    normalized_sort_by = sort_by.strip().lower()
    if normalized_sort_by not in {"created_at", "updated_at"}:
        normalized_sort_by = "created_at"
    normalized_sort_order = sort_order.strip().lower()
    if normalized_sort_order not in {"asc", "desc"}:
        normalized_sort_order = "desc"
    effective_offset = max(0, int(offset))
    normalized = cast(EvaluationJobStatus | None, normalized_status)
    items = list_evaluation_jobs(
        limit=limit,
        status=normalized,
        offset=effective_offset,
        sort_by=normalized_sort_by,
        sort_order=normalized_sort_order,
        search_query=search_query,
    )
    total = count_evaluation_jobs(status=normalized, search_query=search_query)
    return EvaluationJobListResult(
        total=total,
        limit=limit,
        offset=effective_offset,
        items=items,
    )


def get_job(job_id: str) -> EvaluationJob:
    job = get_evaluation_job(job_id)
    if job is None:
        raise EvaluationJobNotFoundError(f"Evaluation job not found: {job_id}")
    return job


def run_job(job_id: str) -> EvaluationJobRunResult:
    job = get_evaluation_job(job_id)
    if job is None:
        raise EvaluationJobNotFoundError(f"Evaluation job not found: {job_id}")

    if job.status not in {"draft", "queued"} or job.linked_run_id:
        raise ValueError(f"Evaluation job cannot run from status={job.status}: {job_id}")
    if not job.dataset_snapshot:
        raise ValueError("Legacy job has no dataset snapshot. Duplicate it to validate current inputs.")
    run_id = str(uuid4())
    started_at = datetime.now(timezone.utc)
    conn = get_connection()
    try:
        conn.execute("BEGIN TRANSACTION")
        claimed = conn.execute(
            "UPDATE evaluation_jobs SET status='running', linked_run_id=?, started_at=?, "
            "updated_at=?, failure_reason=NULL, completed_at=NULL "
            "WHERE job_id=? AND status IN ('draft','queued') AND linked_run_id IS NULL RETURNING job_id",
            [run_id, started_at, started_at, job_id]).fetchone()
        if not claimed:
            raise ValueError("Job was already claimed or canceled. Reload its status.")
        execution_run = create_test_run(
            name=job.project_name.strip() or f"evaluation-job-{job_id[:8]}", model_name=job.model_name,
            provider="ollama" if job.provider in {"ollama", "local"} else "mock",
            dataset_version=job.dataset_version or "v1", evaluation_mode=job.evaluation_mode,
            temperature=job.temperature, max_output_tokens=job.max_output_tokens,
            repeat_count=job.repeat_count, mode="real_local" if job.provider in {"ollama", "local"} else "mock",
            notes=job.notes, run_group_id=f"evaluation-job:{job_id}", repetition_index=1,
            metadata={"job_id": job_id, "dataset_sha256": job.dataset_sha256,
                      "configuration": job.model_dump(mode="json", exclude={"dataset_snapshot"}),
                      "dataset_snapshot": job.dataset_snapshot},
            run_id=run_id, connection=conn)
        conn.execute("COMMIT")
    except Exception:
        conn.execute("ROLLBACK")
        raise
    finally:
        conn.close()
    refreshed = get_job(job_id)

    run_name = refreshed.project_name.strip() or f"evaluation-job-{job_id[:8]}"
    run_group_id = f"evaluation-job:{job_id}"
    evaluation_mode = cast(
        Literal["regression", "exploratory", "adversarial", "trace_replay"],
        refreshed.evaluation_mode,
    )
    try:
        result = run_batch_workflow(
            input_path=refreshed.input_path,
            prepared_cases=[TestCase.model_validate(case) for case in refreshed.dataset_snapshot],
            execution_run=execution_run,
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
    except Exception as exc:  # noqa: BLE001 - persist failure before bubbling error
        _finish_run(run_id, "failed")
        failed = update_evaluation_job(
            job_id,
            status="failed",
            failure_reason=str(exc)[:1000],
            completed_at=datetime.now(timezone.utc),
        )
        if failed is None:
            raise EvaluationJobNotFoundError(f"Evaluation job not found after failure update: {job_id}") from exc
        raise

    _finish_run(run_id, "completed")
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


def queue_job(job_id: str) -> EvaluationJob:
    job = get_job(job_id)
    if job.linked_run_id:
        raise ValueError(f"Evaluation job cannot be queued after execution: {job_id}")
    if job.status in {"running", "completed", "failed", "canceled"}:
        raise ValueError(f"Evaluation job cannot be queued from status={job.status}: {job_id}")
    if job.status == "queued":
        return job
    queued = update_evaluation_job(job_id, status="queued", queued_at=datetime.now(timezone.utc), expected_statuses=("draft",))
    if queued is None:
        raise EvaluationJobNotFoundError(f"Evaluation job not found after queue update: {job_id}")
    return queued


def process_queued_jobs(max_jobs: int = 10) -> EvaluationJobQueueProcessResult:
    effective_max = max(1, int(max_jobs))
    queued_jobs = list_evaluation_jobs(
        limit=effective_max,
        status="queued",
        sort_by="queued_at",
        sort_order="asc",
    )
    results: list[EvaluationJobRunResult] = []
    failures = []
    for job in queued_jobs:
        try:
            results.append(run_job(job.job_id))
        except Exception as exc:
            failures.append({"job_id": job.job_id, "error": str(exc)[:1000]})
    return EvaluationJobQueueProcessResult(
        requested_max_jobs=effective_max,
        processed_count=len(results) + len(failures),
        results=results,
        failures=failures,
    )


def queue_stats() -> EvaluationJobQueueStatsResult:
    counts = evaluation_job_status_counts()
    total = sum(counts.values())
    return EvaluationJobQueueStatsResult(total=total, by_status=counts)


def cancel_job(job_id: str, reason: str = "") -> EvaluationJob:
    job = get_job(job_id)
    if job.status in {"completed", "failed"} or job.linked_run_id:
        raise ValueError(f"Evaluation job cannot be canceled from status={job.status}: {job_id}")
    if job.status == "running":
        raise ValueError(f"Evaluation job running; stop worker first: {job_id}")
    if job.status == "canceled":
        return job

    cancel_reason = reason.strip() or "Canceled by user."
    canceled = update_evaluation_job(
        job_id,
        status="canceled",
        failure_reason=cancel_reason[:1000],
        expected_statuses=("draft", "queued"),
        completed_at=datetime.now(timezone.utc),
    )
    if canceled is None:
        raise EvaluationJobNotFoundError(f"Evaluation job not found after cancel update: {job_id}")
    return canceled


def get_job_summary(job_id: str) -> EvaluationJobSummaryResult:
    job = get_job(job_id)
    run_id = _require_run_id(job)
    run_report = run_report_workflow(run_id)
    return EvaluationJobSummaryResult(
        job=job,
        storage_summary=run_report.storage_summary,
        report=run_report.report,
    )


def get_job_failed_cases(job_id: str, limit: int = 200, offset: int = 0) -> EvaluationJobFailedCasesResult:
    job = get_job(job_id)
    run_id = _require_run_id(job)
    effective_offset = max(0, int(offset))
    results = fetch_results_for_run(run_id)
    failed = [result for result in results if not result.is_correct]
    failed_sorted = sorted(
        failed,
        key=lambda result: (result.score, result.latency_ms, result.test_case_id, result.attempt_index),
    )
    paged = failed_sorted[effective_offset : effective_offset + limit]
    items = [
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
        for result in paged
    ]
    return EvaluationJobFailedCasesResult(
        total=len(failed_sorted),
        limit=limit,
        offset=effective_offset,
        items=items,
    )


def get_job_traces(
    job_id: str,
    limit: int = 200,
    offset: int = 0,
    only_failed: bool = True,
    test_case_id: str | None = None,
) -> EvaluationJobTracesResult:
    job = get_job(job_id)
    run_id = _require_run_id(job)
    normalized_test_case_id = (test_case_id or "").strip() or None
    effective_offset = max(0, int(offset))
    total, items = fetch_traces_page(
        run_id=run_id,
        only_failed=only_failed,
        test_case_id=normalized_test_case_id,
        max_rows=limit,
        offset=effective_offset,
    )
    return EvaluationJobTracesResult(
        total=total,
        limit=limit,
        offset=effective_offset,
        items=items,
    )


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


def get_job_client_report_payload(job_id: str, failed_case_limit: int = 20) -> EvaluationJobClientReportPayload:
    job = get_job(job_id)
    run_id = _require_run_id(job)
    run_report: RunReportResult = run_report_workflow(run_id)
    markdown_report = generate_run_markdown_report(run_id)
    failed_cases = get_job_failed_cases(job_id, limit=failed_case_limit, offset=0)
    return EvaluationJobClientReportPayload(
        job=job,
        run_id=run_id,
        generated_at=datetime.now(timezone.utc),
        storage_summary=run_report.storage_summary,
        report=run_report.report,
        failed_case_total=failed_cases.total,
        failed_cases_sample=failed_cases.items,
        markdown_report=markdown_report,
    )


def _require_run_id(job: EvaluationJob) -> str:
    run_id = (job.linked_run_id or "").strip()
    if not run_id:
        raise ValueError(f"Evaluation job is not completed yet: {job.job_id}")
    return run_id


def _validate_job_create_payload(payload: EvaluationJobCreate) -> None:
    try:
        path = resolve_input_path(payload.input_path)
        if not path.is_file() or path.suffix.lower() not in {".jsonl", ".csv"}:
            raise ValueError("Dataset must be a JSONL or CSV file.")
        if payload.provider == "mock" and payload.model_name not in {"mock-baseline", "mock-noisy", "mock-failing"}:
            raise ValueError("Unsupported mock model.")
        if payload.provider in {"ollama", "local"} and not re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9._:/-]*", payload.model_name):
            raise ValueError("Invalid Ollama model identifier; use a model tag such as llama3.2:1b.")
    except FileNotFoundError as exc:
        raise ValueError(str(exc)) from exc

    if payload.provider in {"ollama", "local"} and not payload.model_name.strip():
        raise ValueError(f"model_name is required when provider={payload.provider}")


def _finish_run(run_id: str, status: str) -> None:
    conn = get_connection()
    try:
        conn.execute("UPDATE test_runs SET status=?, finished_at=? WHERE id=?",
                     [status, datetime.now(timezone.utc), run_id])
    finally:
        conn.close()


def recover_interrupted_jobs() -> int:
    """Called once at startup of the single supported DB-owning API process."""
    conn = get_connection()
    now = datetime.now(timezone.utc)
    try:
        conn.execute("BEGIN TRANSACTION")
        rows = conn.execute("UPDATE evaluation_jobs SET status='failed', "
                            "failure_reason='Backend stopped during execution; retry as a new job.', "
                            "completed_at=?, updated_at=? WHERE status='running' RETURNING linked_run_id",
                            [now, now]).fetchall()
        conn.execute("UPDATE test_runs SET status='failed', finished_at=? WHERE status='running'", [now])
        conn.execute("COMMIT")
        return len(rows)
    except Exception:
        conn.execute("ROLLBACK")
        raise
    finally:
        conn.close()
