"""API endpoints for evaluation runs and candidate test authoring workflow."""

from typing import Any, Literal

from fastapi import APIRouter, HTTPException, Query
from fastapi.responses import Response
from pydantic import BaseModel

from llm_reliability_analytics.runner.llm_client import (
    LLMModelNotFoundError,
    LLMRequestError,
    LLMServiceUnavailableError,
    RECOMMENDED_OLLAMA_MODELS,
)
from llm_reliability_analytics.runner.ollama_client import OllamaLLMClient
from llm_reliability_analytics.storage.evaluation_job_repository import (
    EvaluationJob,
    EvaluationJobCreate,
    EvaluationJobStatus,
)
from llm_reliability_analytics.storage.duckdb_store import fetch_attempt_counts
from llm_reliability_analytics.workflow.evaluation_jobs import (
    EvaluationJobCancelRequest,
    EvaluationJobClientReportPayload,
    EvaluationJobConflictError,
    EvaluationJobQueueScheduleResult,
    EvaluationJobFailedCase,
    EvaluationJobFailedCasesResult,
    EvaluationJobListResult,
    EvaluationJobNotFoundError,
    EvaluationJobQueueProcessResult,
    EvaluationJobQueueStatsResult,
    EvaluationJobReportPayload,
    EvaluationJobRunResult,
    EvaluationJobSummaryResult,
    EvaluationJobTracesResult,
    EvaluationJobRetryRequest,
    create_job,
    duplicate_job,
    get_job_failed_cases,
    get_job_failed_cases_csv,
    job_progress,
    schedule_queued_jobs,
    start_job,
    get_job_report_payload,
    get_job_client_report_payload,
    get_job,
    get_job_summary,
    get_job_traces,
    list_jobs,
    process_queued_jobs,
    retry_job,
    cancel_job,
    queue_stats,
    queue_job,
    run_job,
)
from llm_reliability_analytics.workflow.evaluation_job_options import (
    EvaluationJobOptionsResponse,
    get_evaluation_job_options,
)
from llm_reliability_analytics.workflow.service import RunNotFoundError

router = APIRouter()


class EvaluationJobView(EvaluationJob):
    """A job plus outcome counts of its run and live progress while this process executes it."""
    attempts: int | None = None
    passed_attempts: int | None = None
    progress_done: int | None = None
    progress_total: int | None = None
    stop_requested: bool = False


def _job_views(jobs: list[EvaluationJob]) -> list[EvaluationJobView]:
    counts = fetch_attempt_counts([job.linked_run_id for job in jobs if job.linked_run_id])
    views = []
    for job in jobs:
        attempts, passed_attempts = counts.get(job.linked_run_id or "", (None, None))
        done, total, stop = job_progress(job.job_id) or (None, None, False)
        views.append(EvaluationJobView(**job.model_dump(), attempts=attempts, passed_attempts=passed_attempts,
                                       progress_done=done, progress_total=total, stop_requested=stop))
    return views


class EvaluationJobListResponse(BaseModel):
    total: int
    limit: int
    offset: int
    items: list[EvaluationJobView]


class EvaluationJobFailedCasesResponse(BaseModel):
    total: int
    limit: int
    offset: int
    items: list[EvaluationJobFailedCase]


class EvaluationJobTracesResponse(BaseModel):
    total: int
    limit: int
    offset: int
    items: list[dict[str, Any]]


class ModelsResponse(BaseModel):
    provider: str = "ollama"
    ollama_reachable: bool
    installed_models: list[str]
    recommended_models: list[str]
    available_models: list[str]
    error: str | None = None


@router.get("/health")
def healthcheck() -> dict[str, str]:
    return {"status": "ok"}


@router.get("/models", response_model=ModelsResponse)
def models_endpoint() -> ModelsResponse:
    client = OllamaLLMClient(model_name=RECOMMENDED_OLLAMA_MODELS[0], timeout_seconds=5.0)
    try:
        installed = client.list_installed_models()
        available = sorted(set([*RECOMMENDED_OLLAMA_MODELS, *installed]))
        return ModelsResponse(
            ollama_reachable=True,
            installed_models=installed,
            recommended_models=RECOMMENDED_OLLAMA_MODELS,
            available_models=available,
            error=None,
        )
    except (LLMServiceUnavailableError, LLMRequestError) as exc:
        return ModelsResponse(
            ollama_reachable=False,
            installed_models=[],
            recommended_models=RECOMMENDED_OLLAMA_MODELS,
            available_models=RECOMMENDED_OLLAMA_MODELS,
            error=str(exc),
        )


@router.post("/evaluation-jobs", response_model=EvaluationJob, status_code=201)
def create_evaluation_job_endpoint(request: EvaluationJobCreate) -> EvaluationJob:
    try:
        return create_job(request)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc


class EvaluationJobDuplicateRequest(BaseModel):
    """Optional model swap; everything else, including the frozen dataset, is copied."""
    provider: Literal["mock", "ollama", "local", "openai_compatible"] | None = None
    model_name: str | None = None


@router.post("/evaluation-jobs/{job_id}/duplicate", response_model=EvaluationJob, status_code=201)
def duplicate_evaluation_job_endpoint(job_id: str, request: EvaluationJobDuplicateRequest | None = None) -> EvaluationJob:
    try:
        return duplicate_job(job_id, provider=request.provider if request else None,
                             model_name=request.model_name if request else None)
    except EvaluationJobNotFoundError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc


@router.post("/evaluation-jobs/{job_id}/retry", response_model=EvaluationJob, status_code=201)
def retry_evaluation_job_endpoint(job_id: str, request: EvaluationJobRetryRequest) -> EvaluationJob:
    try:
        return retry_job(job_id=job_id, queue=request.queue)
    except EvaluationJobNotFoundError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    except EvaluationJobConflictError as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc
    except ValueError as exc:  # e.g. a legacy job whose settings fail current validation
        raise HTTPException(status_code=400, detail=str(exc)) from exc


@router.get("/evaluation-jobs", response_model=EvaluationJobListResponse)
def list_evaluation_jobs_endpoint(
    status: EvaluationJobStatus | None = Query(default=None),
    limit: int = Query(default=100, ge=1, le=5000),
    offset: int = Query(default=0, ge=0),
    sort_by: Literal["created_at", "updated_at"] = Query(default="created_at"),
    sort_order: Literal["asc", "desc"] = Query(default="desc"),
    q: str | None = Query(default=None),
) -> EvaluationJobListResponse:
    result: EvaluationJobListResult = list_jobs(
        limit=limit,
        status=status,
        offset=offset,
        sort_by=sort_by,
        sort_order=sort_order,
        search_query=q,
    )
    return EvaluationJobListResponse(
        total=result.total,
        limit=result.limit,
        offset=result.offset,
        items=_job_views(result.items),
    )


@router.get("/evaluation-jobs/options", response_model=EvaluationJobOptionsResponse)
def evaluation_job_options_endpoint() -> EvaluationJobOptionsResponse:
    return get_evaluation_job_options()


@router.get("/evaluation-jobs/{job_id}", response_model=EvaluationJobView)
def get_evaluation_job_endpoint(job_id: str) -> EvaluationJobView:
    try:
        return _job_views([get_job(job_id)])[0]
    except EvaluationJobNotFoundError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc


WAIT_DESCRIPTION = "Block until execution finishes (CLI/tests). By default the job is scheduled and 202 returns at once."


@router.post("/evaluation-jobs/{job_id}/run", response_model=EvaluationJobRunResult | EvaluationJob, status_code=202)
def run_evaluation_job_endpoint(
    job_id: str, response: Response, wait: bool = Query(default=False, description=WAIT_DESCRIPTION),
) -> EvaluationJobRunResult | EvaluationJob:
    try:
        if not wait:
            return start_job(job_id)
        response.status_code = 200
        return run_job(job_id)
    except EvaluationJobNotFoundError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    except EvaluationJobConflictError as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    except LLMServiceUnavailableError as exc:
        raise HTTPException(status_code=503, detail=str(exc)) from exc
    except LLMModelNotFoundError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    except LLMRequestError as exc:
        raise HTTPException(status_code=502, detail=str(exc)) from exc
    except RuntimeError as exc:
        raise HTTPException(status_code=500, detail=str(exc)) from exc


@router.post("/evaluation-jobs/{job_id}/queue", response_model=EvaluationJob)
def queue_evaluation_job_endpoint(job_id: str) -> EvaluationJob:
    try:
        return queue_job(job_id)
    except EvaluationJobNotFoundError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    except EvaluationJobConflictError as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc


@router.post("/evaluation-jobs/process-queue",
             response_model=EvaluationJobQueueProcessResult | EvaluationJobQueueScheduleResult, status_code=202)
def process_evaluation_jobs_queue_endpoint(
    response: Response,
    max_jobs: int = Query(default=10, ge=1, le=500),
    wait: bool = Query(default=False, description=WAIT_DESCRIPTION),
) -> EvaluationJobQueueProcessResult | EvaluationJobQueueScheduleResult:
    if not wait:
        return schedule_queued_jobs(max_jobs=max_jobs)
    response.status_code = 200
    try:
        return process_queued_jobs(max_jobs=max_jobs)
    except EvaluationJobNotFoundError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    except LLMServiceUnavailableError as exc:
        raise HTTPException(status_code=503, detail=str(exc)) from exc
    except LLMModelNotFoundError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    except LLMRequestError as exc:
        raise HTTPException(status_code=502, detail=str(exc)) from exc
    except RuntimeError as exc:
        raise HTTPException(status_code=500, detail=str(exc)) from exc


@router.post("/evaluation-jobs/{job_id}/cancel", response_model=EvaluationJob)
def cancel_evaluation_job_endpoint(
    job_id: str,
    request: EvaluationJobCancelRequest,
) -> EvaluationJob:
    try:
        return cancel_job(job_id=job_id, reason=request.reason)
    except EvaluationJobNotFoundError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    except EvaluationJobConflictError as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc


@router.get("/evaluation-jobs/queue/stats", response_model=EvaluationJobQueueStatsResult)
def evaluation_jobs_queue_stats_endpoint() -> EvaluationJobQueueStatsResult:
    return queue_stats()


@router.get("/evaluation-jobs/{job_id}/summary", response_model=EvaluationJobSummaryResult)
def evaluation_job_summary_endpoint(job_id: str) -> EvaluationJobSummaryResult:
    try:
        return get_job_summary(job_id)
    except EvaluationJobNotFoundError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    except RunNotFoundError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc


@router.get("/evaluation-jobs/{job_id}/failed-cases", response_model=EvaluationJobFailedCasesResponse)
def evaluation_job_failed_cases_endpoint(
    job_id: str,
    limit: int = Query(default=200, ge=1, le=5000),
    offset: int = Query(default=0, ge=0),
    error_type: str | None = Query(default=None, description="Only failed attempts with this error type."),
    category: str | None = Query(default=None, description="Only failed attempts in this category."),
) -> EvaluationJobFailedCasesResponse:
    try:
        result: EvaluationJobFailedCasesResult = get_job_failed_cases(
            job_id, limit=limit, offset=offset, error_type=error_type, category=category)
    except EvaluationJobNotFoundError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    return EvaluationJobFailedCasesResponse(
        total=result.total,
        limit=result.limit,
        offset=result.offset,
        items=result.items,
    )


@router.get("/evaluation-jobs/{job_id}/failed-cases.csv", response_class=Response)
def evaluation_job_failed_cases_csv_endpoint(job_id: str) -> Response:
    try:
        content = get_job_failed_cases_csv(job_id)
    except EvaluationJobNotFoundError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    return Response(content=content, media_type="text/csv",
                    headers={"Content-Disposition": 'attachment; filename="failed-attempts.csv"'})


@router.get("/evaluation-jobs/{job_id}/traces", response_model=EvaluationJobTracesResponse)
def evaluation_job_traces_endpoint(
    job_id: str,
    limit: int = Query(default=200, ge=1, le=5000),
    offset: int = Query(default=0, ge=0),
    only_failed: bool = Query(default=True),
    test_case_id: str | None = Query(default=None),
) -> EvaluationJobTracesResponse:
    try:
        result: EvaluationJobTracesResult = get_job_traces(
            job_id,
            limit=limit,
            offset=offset,
            only_failed=only_failed,
            test_case_id=test_case_id,
        )
    except EvaluationJobNotFoundError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    return EvaluationJobTracesResponse(
        total=result.total,
        limit=result.limit,
        offset=result.offset,
        items=result.items,
    )


@router.get("/evaluation-jobs/{job_id}/report", response_model=EvaluationJobReportPayload)
def evaluation_job_report_endpoint(job_id: str) -> EvaluationJobReportPayload:
    try:
        return get_job_report_payload(job_id)
    except EvaluationJobNotFoundError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    except RunNotFoundError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc


@router.get("/evaluation-jobs/{job_id}/client-report", response_model=EvaluationJobClientReportPayload)
def evaluation_job_client_report_endpoint(
    job_id: str,
    failed_case_limit: int = Query(default=20, ge=1, le=200),
) -> EvaluationJobClientReportPayload:
    try:
        return get_job_client_report_payload(job_id=job_id, failed_case_limit=failed_case_limit)
    except EvaluationJobNotFoundError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    except RunNotFoundError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
