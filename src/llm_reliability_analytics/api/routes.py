"""Minimal API endpoints for the first defense demo."""

from typing import Literal

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel, Field

from llm_reliability_analytics.analytics.reliability import ReliabilityReport
from llm_reliability_analytics.runner.llm_client import (
    LLMModelNotFoundError,
    LLMRequestError,
    LLMServiceUnavailableError,
)
from llm_reliability_analytics.storage.duckdb_store import RunAggregatedSummary
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
