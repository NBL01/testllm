"""API endpoints for evaluation runs and candidate test authoring workflow."""

from typing import Any, Literal

from fastapi import APIRouter, HTTPException, Query
from pydantic import BaseModel, Field

from llm_reliability_analytics.analytics.reliability import ReliabilityReport
from llm_reliability_analytics.runner.client_factory import build_llm_client
from llm_reliability_analytics.runner.llm_client import (
    LLMModelNotFoundError,
    LLMRequestError,
    LLMServiceUnavailableError,
)
from llm_reliability_analytics.storage.candidate_repository import (
    CandidateReviewEvent,
    get_candidate_test_case,
    list_candidate_review_events,
    list_candidate_test_cases,
    update_candidate_status,
    upsert_candidate_test_cases,
)
from llm_reliability_analytics.storage.evaluation_job_repository import (
    EvaluationJob,
    EvaluationJobCreate,
    EvaluationJobStatus,
)
from llm_reliability_analytics.storage.duckdb_store import RunAggregatedSummary
from llm_reliability_analytics.test_authoring.models import CandidateStatus, CandidateTestCase
from llm_reliability_analytics.test_authoring.service import CandidateAuthoringService
from llm_reliability_analytics.workflow.evaluation_jobs import (
    EvaluationJobCancelRequest,
    EvaluationJobFailedCase,
    EvaluationJobNotFoundError,
    EvaluationJobQueueProcessResult,
    EvaluationJobQueueStatsResult,
    EvaluationJobReportPayload,
    EvaluationJobRunResult,
    EvaluationJobSummaryResult,
    create_job,
    get_job_failed_cases,
    get_job_report_payload,
    get_job,
    get_job_summary,
    get_job_traces,
    list_jobs,
    process_queued_jobs,
    cancel_job,
    queue_stats,
    queue_job,
    run_job,
)
from llm_reliability_analytics.workflow.evaluation_job_options import (
    EvaluationJobOptionsResponse,
    get_evaluation_job_options,
)
from llm_reliability_analytics.workflow.service import (
    RunNotFoundError,
    load_cases_to_storage,
    run_batch_workflow,
    run_report_workflow,
)

router = APIRouter()


class LoadTestCasesRequest(BaseModel):
    input_path: str = "sample_test_cases.jsonl"


class LoadTestCasesResponse(BaseModel):
    input_path: str
    total_rows: int
    valid_rows: int
    invalid_rows: int
    dataset_versions: list[str]
    test_source_distribution: dict[str, int]
    category_distribution: dict[str, int]
    oracle_type_distribution: dict[str, int]
    stored_test_cases: int


class RunBatchRequest(BaseModel):
    input_path: str = "sample_test_cases.jsonl"
    run_name: str = "demo-run"
    run_label: str | None = None
    model_name: str = "mock-baseline"
    provider: Literal["mock", "ollama", "local"] = "mock"
    model_version: str = "n/a"
    dataset_version: str | None = None
    evaluation_mode: Literal["regression", "exploratory", "adversarial", "trace_replay"] = "regression"
    temperature: float = 0.0
    max_output_tokens: int = Field(default=128, ge=1, le=1024)
    timeout_seconds: float = Field(default=30.0, ge=1.0, le=300.0)
    run_mode: Literal["mock", "real_local", "offline_replay", "real"] = "mock"
    notes: str = ""
    run_group_id: str | None = None
    mock_mode: Literal["deterministic", "semi_random"] = "deterministic"
    mode: Literal["deterministic", "semi_random"] = "deterministic"
    seed: int = 42
    limit: int | None = Field(default=None, ge=1)
    repeats_per_case: int = Field(default=1, ge=1)


class RunBatchResponse(BaseModel):
    run_id: str
    loaded_test_cases: int
    executed_test_cases: int
    report: ReliabilityReport
    storage_summary: RunAggregatedSummary


class RunReportResponse(BaseModel):
    run_id: str
    storage_summary: RunAggregatedSummary
    report: ReliabilityReport


class GenerateCandidatesRequest(BaseModel):
    categories: list[str] = Field(default_factory=list)
    per_category: int = Field(default=5, ge=1, le=100)
    provider: Literal["none", "mock", "ollama"] = "none"
    model_name: str | None = None
    temperature: float = 0.1
    max_output_tokens: int = Field(default=120, ge=1, le=1024)
    timeout_seconds: float = Field(default=20.0, ge=1.0, le=300.0)


class GenerateCandidatesResponse(BaseModel):
    generated_count: int
    stored_count: int
    categories: list[str]
    candidates: list[CandidateTestCase]


class CandidateListResponse(BaseModel):
    total: int
    items: list[CandidateTestCase]


class UpdateCandidateStatusRequest(BaseModel):
    new_status: CandidateStatus
    reviewer: str = ""
    note: str = ""


class UpdateCandidateStatusResponse(BaseModel):
    candidate: CandidateTestCase


class CandidateEventsResponse(BaseModel):
    candidate_id: str
    total: int
    events: list[CandidateReviewEvent]


class EvaluationJobListResponse(BaseModel):
    total: int
    items: list[EvaluationJob]


class EvaluationJobFailedCasesResponse(BaseModel):
    total: int
    items: list[EvaluationJobFailedCase]


class EvaluationJobTracesResponse(BaseModel):
    total: int
    items: list[dict[str, Any]]


@router.get("/health")
def healthcheck() -> dict[str, str]:
    return {"status": "ok"}


@router.post("/load-test-cases", response_model=LoadTestCasesResponse)
def load_test_cases_endpoint(request: LoadTestCasesRequest) -> LoadTestCasesResponse:
    return LoadTestCasesResponse(**load_cases_to_storage(request.input_path).model_dump())


@router.post("/run-batch", response_model=RunBatchResponse)
def run_batch_endpoint(request: RunBatchRequest) -> RunBatchResponse:
    try:
        result = run_batch_workflow(
            input_path=request.input_path,
            run_name=request.run_name,
            run_label=request.run_label,
            model_name=request.model_name,
            provider=request.provider,
            model_version=request.model_version,
            dataset_version=request.dataset_version,
            evaluation_mode=request.evaluation_mode,
            temperature=request.temperature,
            max_output_tokens=request.max_output_tokens,
            timeout_seconds=request.timeout_seconds,
            run_mode=request.run_mode,
            notes=request.notes,
            run_group_id=request.run_group_id,
            mock_mode=request.mock_mode,
            mode=request.mode,
            seed=request.seed,
            limit=request.limit,
            repeats_per_case=request.repeats_per_case,
        )
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
    return RunBatchResponse(**result.model_dump())


@router.get("/report/{run_id}", response_model=RunReportResponse)
def get_report(run_id: str) -> RunReportResponse:
    try:
        report = run_report_workflow(run_id)
    except RunNotFoundError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    return RunReportResponse(**report.model_dump())


@router.post("/candidates/generate", response_model=GenerateCandidatesResponse)
def generate_candidates_endpoint(request: GenerateCandidatesRequest) -> GenerateCandidatesResponse:
    llm_client = None
    if request.provider != "none":
        resolved_model = request.model_name or ("mock-baseline" if request.provider == "mock" else None)
        llm_client = build_llm_client(
            provider=request.provider,
            run_mode="real_local" if request.provider == "ollama" else "mock",
            model_name=resolved_model,
            temperature=request.temperature,
            max_output_tokens=request.max_output_tokens,
            timeout_seconds=request.timeout_seconds,
        )

    service = CandidateAuthoringService(llm_client=llm_client)
    candidates = service.generate_candidates(
        categories=request.categories,
        per_category=request.per_category,
    )
    stored_count = upsert_candidate_test_cases(candidates)
    categories = sorted({candidate.category for candidate in candidates})

    return GenerateCandidatesResponse(
        generated_count=len(candidates),
        stored_count=stored_count,
        categories=categories,
        candidates=candidates,
    )


@router.get("/candidates", response_model=CandidateListResponse)
def list_candidates_endpoint(
    status: CandidateStatus | None = Query(default=None),
    category: str | None = Query(default=None),
    limit: int = Query(default=200, ge=1, le=5000),
) -> CandidateListResponse:
    items = list_candidate_test_cases(status=status, category=category, max_rows=limit)
    return CandidateListResponse(total=len(items), items=items)


@router.post("/candidates/{candidate_id}/status", response_model=UpdateCandidateStatusResponse)
def update_candidate_status_endpoint(
    candidate_id: str,
    request: UpdateCandidateStatusRequest,
) -> UpdateCandidateStatusResponse:
    updated = update_candidate_status(
        candidate_id=candidate_id,
        new_status=request.new_status,
        reviewer=request.reviewer,
        note=request.note,
    )
    if updated is None:
        raise HTTPException(status_code=404, detail=f"Candidate not found: {candidate_id}")
    return UpdateCandidateStatusResponse(candidate=updated)


@router.get("/candidates/{candidate_id}/events", response_model=CandidateEventsResponse)
def candidate_events_endpoint(
    candidate_id: str,
    limit: int = Query(default=100, ge=1, le=5000),
) -> CandidateEventsResponse:
    candidate = get_candidate_test_case(candidate_id)
    if candidate is None:
        raise HTTPException(status_code=404, detail=f"Candidate not found: {candidate_id}")
    events = list_candidate_review_events(candidate_id=candidate_id, max_rows=limit)
    return CandidateEventsResponse(candidate_id=candidate_id, total=len(events), events=events)


@router.post("/evaluation-jobs", response_model=EvaluationJob, status_code=201)
def create_evaluation_job_endpoint(request: EvaluationJobCreate) -> EvaluationJob:
    return create_job(request)


@router.get("/evaluation-jobs", response_model=EvaluationJobListResponse)
def list_evaluation_jobs_endpoint(
    status: EvaluationJobStatus | None = Query(default=None),
    limit: int = Query(default=100, ge=1, le=5000),
) -> EvaluationJobListResponse:
    items = list_jobs(limit=limit, status=status)
    return EvaluationJobListResponse(total=len(items), items=items)


@router.get("/evaluation-jobs/options", response_model=EvaluationJobOptionsResponse)
def evaluation_job_options_endpoint() -> EvaluationJobOptionsResponse:
    return get_evaluation_job_options()


@router.get("/evaluation-jobs/{job_id}", response_model=EvaluationJob)
def get_evaluation_job_endpoint(job_id: str) -> EvaluationJob:
    try:
        return get_job(job_id)
    except EvaluationJobNotFoundError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc


@router.post("/evaluation-jobs/{job_id}/run", response_model=EvaluationJobRunResult)
def run_evaluation_job_endpoint(job_id: str) -> EvaluationJobRunResult:
    try:
        return run_job(job_id)
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


@router.post("/evaluation-jobs/{job_id}/queue", response_model=EvaluationJob)
def queue_evaluation_job_endpoint(job_id: str) -> EvaluationJob:
    try:
        return queue_job(job_id)
    except EvaluationJobNotFoundError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc


@router.post("/evaluation-jobs/process-queue", response_model=EvaluationJobQueueProcessResult)
def process_evaluation_jobs_queue_endpoint(
    max_jobs: int = Query(default=10, ge=1, le=500),
) -> EvaluationJobQueueProcessResult:
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
) -> EvaluationJobFailedCasesResponse:
    try:
        items = get_job_failed_cases(job_id, limit=limit)
    except EvaluationJobNotFoundError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    return EvaluationJobFailedCasesResponse(total=len(items), items=items)


@router.get("/evaluation-jobs/{job_id}/traces", response_model=EvaluationJobTracesResponse)
def evaluation_job_traces_endpoint(
    job_id: str,
    limit: int = Query(default=200, ge=1, le=5000),
    only_failed: bool = Query(default=True),
) -> EvaluationJobTracesResponse:
    try:
        items = get_job_traces(job_id, limit=limit, only_failed=only_failed)
    except EvaluationJobNotFoundError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    return EvaluationJobTracesResponse(total=len(items), items=items)


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
