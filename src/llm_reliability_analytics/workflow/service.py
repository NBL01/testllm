"""Core workflow orchestration.

This module keeps the architecture easy to explain:
1) load validated test cases
2) run prompts through selected LLM provider (mock or local Ollama)
3) score outputs with oracles
4) store results in DuckDB
5) compute and return analytics report
"""

import json
from typing import Literal

from pydantic import BaseModel, Field

from llm_reliability_analytics.analytics.reliability import (
    ReliabilityReport,
    compute_reliability_report,
)
from llm_reliability_analytics.datasets.trace_loader import load_trace_replay_test_cases
from llm_reliability_analytics.ingestion.loader import load_test_cases
from llm_reliability_analytics.models.domain import (
    ErrorTaxonomy,
    TestCase,
    TestResult,
)
from llm_reliability_analytics.oracles import evaluate_with_oracle, normalize_answer
from llm_reliability_analytics.runner.client_factory import build_llm_client
from llm_reliability_analytics.runner.llm_client import (
    DEFAULT_LOCAL_MODEL,
    LLMModelNotFoundError,
    resolve_execution_mode,
)
from llm_reliability_analytics.runner.ollama_client import OllamaLLMClient
from llm_reliability_analytics.runner.test_runner import TestRunner
from llm_reliability_analytics.storage.duckdb_store import (
    RunAggregatedSummary,
    create_test_run,
    fetch_aggregated_summaries,
    fetch_results_for_run,
    initialize_storage_schema,
    upsert_test_cases,
    insert_batch_results,
)
from llm_reliability_analytics.storage.trace_repository import capture_traces_for_run


class RunNotFoundError(ValueError):
    """Raised when run_id does not exist in storage."""


class LoadCasesResult(BaseModel):
    input_path: str
    total_rows: int
    valid_rows: int
    invalid_rows: int
    dataset_versions: list[str] = Field(default_factory=list)
    test_source_distribution: dict[str, int] = Field(default_factory=dict)
    category_distribution: dict[str, int] = Field(default_factory=dict)
    oracle_type_distribution: dict[str, int] = Field(default_factory=dict)
    stored_test_cases: int


class RunBatchWorkflowResult(BaseModel):
    run_id: str
    loaded_test_cases: int
    executed_test_cases: int
    report: ReliabilityReport
    storage_summary: RunAggregatedSummary


class RunReportResult(BaseModel):
    run_id: str
    storage_summary: RunAggregatedSummary
    report: ReliabilityReport


def load_cases_to_storage(input_path: str) -> LoadCasesResult:
    initialize_storage_schema()
    test_cases, summary = load_test_cases(input_path)
    stored_test_cases = upsert_test_cases(test_cases)
    return LoadCasesResult(
        input_path=input_path,
        total_rows=summary.total_rows,
        valid_rows=summary.valid_rows,
        invalid_rows=summary.invalid_rows,
        dataset_versions=summary.dataset_versions,
        test_source_distribution=summary.test_source_distribution,
        category_distribution=summary.category_distribution,
        oracle_type_distribution=summary.oracle_type_distribution,
        stored_test_cases=stored_test_cases,
    )


def run_batch_workflow(
    input_path: str,
    run_name: str,
    model_name: str | None = None,
    run_label: str | None = None,
    provider: str = "mock",
    model_version: str = "n/a",
    dataset_version: str | None = None,
    evaluation_mode: Literal["regression", "exploratory", "adversarial", "trace_replay"] = "regression",
    temperature: float = 0.0,
    max_output_tokens: int = 128,
    timeout_seconds: float = 30.0,
    run_mode: Literal["mock", "real_local", "offline_replay", "real"] = "mock",
    notes: str = "",
    run_group_id: str | None = None,
    mock_mode: Literal["deterministic", "semi_random"] = "deterministic",
    mode: Literal["deterministic", "semi_random"] | None = None,
    seed: int = 42,
    limit: int | None = None,
    repeats_per_case: int = 1,
) -> RunBatchWorkflowResult:
    if repeats_per_case < 1:
        raise ValueError("repeats_per_case must be >= 1")

    initialize_storage_schema()
    test_cases, _summary = load_test_cases(input_path)
    if limit is not None:
        test_cases = test_cases[:limit]
    if not test_cases:
        raise ValueError("No valid test cases available to run")
    return _run_prepared_test_cases(
        test_cases=test_cases,
        input_path=input_path,
        run_name=run_name,
        model_name=model_name,
        run_label=run_label,
        provider=provider,
        model_version=model_version,
        dataset_version=dataset_version,
        evaluation_mode=evaluation_mode,
        temperature=temperature,
        max_output_tokens=max_output_tokens,
        timeout_seconds=timeout_seconds,
        run_mode=run_mode,
        notes=notes,
        run_group_id=run_group_id,
        mock_mode=mock_mode,
        mode=mode,
        seed=seed,
        repeats_per_case=repeats_per_case,
    )


def run_trace_replay_workflow(
    source_run_id: str,
    run_name: str,
    model_name: str | None = None,
    dataset_version: str = "trace_replay_v1",
    provider: str = "mock",
    run_label: str | None = None,
    notes: str = "",
    only_failed: bool = True,
    max_cases: int = 200,
    repeats_per_case: int = 1,
    temperature: float = 0.0,
    max_output_tokens: int = 128,
    timeout_seconds: float = 30.0,
    run_mode: Literal["mock", "real_local", "offline_replay", "real"] = "mock",
    mock_mode: Literal["deterministic", "semi_random"] = "deterministic",
    seed: int = 42,
) -> RunBatchWorkflowResult:
    initialize_storage_schema()
    test_cases = load_trace_replay_test_cases(
        source_run_id=source_run_id,
        dataset_version=dataset_version,
        only_failed=only_failed,
        max_cases=max_cases,
    )
    if not test_cases:
        raise ValueError("No trace replay test cases were generated from selected source run.")

    replay_notes = f"trace_replay_from={source_run_id}"
    if notes.strip():
        replay_notes = f"{notes.strip()} | {replay_notes}"

    return _run_prepared_test_cases(
        test_cases=test_cases,
        input_path=f"trace://{source_run_id}",
        run_name=run_name,
        model_name=model_name,
        run_label=run_label,
        provider=provider,
        model_version="trace-replay",
        dataset_version=dataset_version,
        evaluation_mode="trace_replay",
        temperature=temperature,
        max_output_tokens=max_output_tokens,
        timeout_seconds=timeout_seconds,
        run_mode=run_mode,
        notes=replay_notes,
        run_group_id=f"trace-replay:{source_run_id}",
        mock_mode=mock_mode,
        mode=mock_mode,
        seed=seed,
        repeats_per_case=repeats_per_case,
    )


def run_report_workflow(run_id: str) -> RunReportResult:
    summaries = fetch_aggregated_summaries(run_id)
    if not summaries:
        raise RunNotFoundError(f"Run '{run_id}' not found")

    results = fetch_results_for_run(run_id)
    return RunReportResult(
        run_id=run_id,
        storage_summary=summaries[0],
        report=compute_reliability_report(
            results,
            run_id=run_id,
            dataset_version=summaries[0].dataset_version,
            repetition_index=summaries[0].repetition_index,
        ),
    )


def _run_prepared_test_cases(
    test_cases: list[TestCase],
    input_path: str,
    run_name: str,
    model_name: str | None,
    run_label: str | None,
    provider: str,
    model_version: str,
    dataset_version: str | None,
    evaluation_mode: Literal["regression", "exploratory", "adversarial", "trace_replay"],
    temperature: float,
    max_output_tokens: int,
    timeout_seconds: float,
    run_mode: Literal["mock", "real_local", "offline_replay", "real"],
    notes: str,
    run_group_id: str | None,
    mock_mode: Literal["deterministic", "semi_random"],
    mode: Literal["deterministic", "semi_random"] | None,
    seed: int,
    repeats_per_case: int,
) -> RunBatchWorkflowResult:
    effective_mock_mode = mode if mode is not None else mock_mode
    execution_mode = resolve_execution_mode(provider=provider, mode=run_mode)
    normalized_provider = "ollama" if execution_mode == "real_local" else "mock"
    resolved_model_name = (model_name or "").strip() or (
        DEFAULT_LOCAL_MODEL if execution_mode == "real_local" else "mock-baseline"
    )
    normalized_run_mode = "real_local" if execution_mode == "real_local" else "mock"

    resolved_dataset_version = dataset_version or test_cases[0].dataset_version
    for test_case in test_cases:
        test_case.dataset_version = resolved_dataset_version

    upsert_test_cases(test_cases)
    run = create_test_run(
        name=run_name,
        model_name=resolved_model_name,
        run_label=run_label,
        provider=normalized_provider,
        model_version=model_version,
        dataset_version=resolved_dataset_version,
        evaluation_mode=evaluation_mode,
        temperature=temperature,
        max_output_tokens=max_output_tokens,
        repeat_count=repeats_per_case,
        mode=normalized_run_mode,
        notes=notes,
        run_group_id=run_group_id,
        metadata={
            "input_path": input_path,
            "provider": normalized_provider,
            "requested_mode": run_mode,
            "mock_mode": effective_mock_mode,
            "timeout_seconds": timeout_seconds,
            "max_output_tokens": max_output_tokens,
            "evaluation_mode": evaluation_mode,
        },
    )

    llm_client = build_llm_client(
        provider=normalized_provider,
        run_mode=normalized_run_mode,
        model_name=resolved_model_name,
        temperature=temperature,
        max_output_tokens=max_output_tokens,
        timeout_seconds=timeout_seconds,
        mock_mode=effective_mock_mode,
        seed=seed,
    )
    _validate_local_model_availability(
        llm_client=llm_client,
        execution_mode=normalized_run_mode,
        model_name=resolved_model_name,
    )

    runner = TestRunner(llm_client=llm_client)
    results = runner.run(test_cases, run_id=run.id, repeats_per_case=repeats_per_case)
    latency_source = "mock_simulated" if normalized_run_mode == "mock" else "observed"
    for result in results:
        if normalized_run_mode == "mock":
            result.latency_source = latency_source
        elif result.latency_source in {"", None}:
            result.latency_source = latency_source

    score_results_with_oracles(test_cases=test_cases, results=results)
    insert_batch_results(results)
    capture_traces_for_run(results)

    summaries = fetch_aggregated_summaries(run.id)
    if not summaries:
        raise RuntimeError("Run completed but storage summary was not found")

    return RunBatchWorkflowResult(
        run_id=run.id,
        loaded_test_cases=len(test_cases),
        executed_test_cases=len(results),
        report=compute_reliability_report(
            results,
            run_id=run.id,
            dataset_version=run.dataset_version,
            repetition_index=run.repetition_index,
        ),
        storage_summary=summaries[0],
    )


def score_results_with_oracles(test_cases: list[TestCase], results: list[TestResult]) -> None:
    """Apply oracle scoring in one place for consistent evaluation behavior."""
    oracle_mapping = {
        "exact_match": "exact_match",
        "semantic_match": "semantic_similarity",
        "custom": "composite_rule",
    }

    test_cases_by_id = {test_case.id: test_case for test_case in test_cases}

    for result in results:
        test_case = test_cases_by_id.get(result.test_case_id)
        if test_case is None:
            result.is_correct = False
            result.score = 0.0
            result.error_type = result.error_type or "missing_test_case"
            result.explanation = "Test case not found for this result."
            result.oracle_details_json = json.dumps({"evaluation_skipped": True, "reason": "missing_test_case"})
            result.error_taxonomy = ErrorTaxonomy.VALIDATION
            continue

        result.dataset_version = test_case.dataset_version
        result.test_source = test_case.test_source.value
        result.oracle_type = test_case.oracle_type.value
        result.prompt = test_case.prompt
        result.expected_answer = test_case.expected_answer
        result.raw_output = result.actual_answer
        result.expected_answer_normalized = normalize_answer(test_case.expected_answer)
        result.actual_answer_normalized = normalize_answer(result.actual_answer)
        result.normalized_output = result.actual_answer_normalized
        result.normalized_answer = result.actual_answer_normalized
        result.error_taxonomy = _taxonomy_from_error_type(result.error_type)
        result.critical_error_flag = result.error_taxonomy in {
            ErrorTaxonomy.RUNTIME,
            ErrorTaxonomy.ORACLE,
            ErrorTaxonomy.TIMEOUT,
            ErrorTaxonomy.UNKNOWN,
        }

        # If generation failed, keep that failure trace and skip oracle execution.
        if result.error_type is not None and not (result.actual_answer or "").strip():
            result.is_correct = False
            result.score = 0.0
            result.explanation = f"Model generation failed before oracle evaluation: {result.error_type}"
            result.oracle_details_json = json.dumps(
                {
                    "evaluation_skipped": True,
                    "reason": "model_generation_error",
                    "error_type": result.error_type,
                }
            )
            result.error_taxonomy = _taxonomy_from_error_type(result.error_type)
            result.critical_error_flag = result.error_taxonomy in {
                ErrorTaxonomy.RUNTIME,
                ErrorTaxonomy.ORACLE,
                ErrorTaxonomy.TIMEOUT,
                ErrorTaxonomy.UNKNOWN,
            }
            continue

        # Keep legacy aliases, but preserve direct oracle types (regex_match, json_schema, etc.).
        oracle_type = oracle_mapping.get(test_case.oracle_type.value, test_case.oracle_type.value)
        metadata = dict(test_case.metadata)

        if oracle_type == "semantic_similarity":
            metadata.setdefault("similarity_threshold", 0.6)
            metadata.setdefault("valid_answers", [test_case.expected_answer])

        # For demo datasets, custom cases default to simple "must contain expected answer" rule.
        if oracle_type == "composite_rule":
            metadata.setdefault("must_contain", [test_case.expected_answer])
            metadata.setdefault("forbidden_keywords", [])
            metadata.setdefault("regex_constraints", [])

        try:
            evaluation = evaluate_with_oracle(
                oracle_type=oracle_type,
                expected_answer=test_case.expected_answer,
                actual_answer=result.actual_answer or "",
                metadata=metadata,
            )
            result.is_correct = evaluation.is_correct
            result.score = evaluation.score
            result.explanation = evaluation.explanation
            result.oracle_details_json = json.dumps(evaluation.details, ensure_ascii=True)
            result.error_type = evaluation.error_type
            if result.error_type is None:
                result.error_taxonomy = ErrorTaxonomy.NONE
                result.critical_error_flag = False
            else:
                result.error_taxonomy = _taxonomy_from_error_type(result.error_type)
                result.critical_error_flag = result.error_taxonomy in {
                    ErrorTaxonomy.RUNTIME,
                    ErrorTaxonomy.ORACLE,
                    ErrorTaxonomy.TIMEOUT,
                    ErrorTaxonomy.UNKNOWN,
                }
        except Exception as exc:  # noqa: BLE001 - batch should continue on single-case failures
            result.is_correct = False
            result.score = 0.0
            result.error_type = result.error_type or f"oracle_{type(exc).__name__}"
            result.explanation = f"Oracle evaluation failed: {exc}"
            result.oracle_details_json = json.dumps(
                {"evaluation_error": type(exc).__name__, "message": str(exc)},
                ensure_ascii=True,
            )
            result.error_taxonomy = ErrorTaxonomy.ORACLE
            result.critical_error_flag = True


def _taxonomy_from_error_type(error_type: str | None) -> ErrorTaxonomy:
    if error_type is None:
        return ErrorTaxonomy.NONE

    normalized = error_type.strip().lower()
    if normalized in {"wrong_answer", "incorrect_answer"}:
        return ErrorTaxonomy.NONE
    if normalized in {"json_parse_error", "json_schema_validation_error", "numeric_parse_error"}:
        return ErrorTaxonomy.PARSING
    if normalized in {"invalid_regex_pattern", "invalid_oracle_config"}:
        return ErrorTaxonomy.VALIDATION
    if "timeout" in normalized:
        return ErrorTaxonomy.TIMEOUT
    if normalized.startswith("oracle_"):
        return ErrorTaxonomy.ORACLE
    if "validation" in normalized:
        return ErrorTaxonomy.VALIDATION
    if "json" in normalized or "parse" in normalized:
        return ErrorTaxonomy.PARSING
    if "runtime" in normalized or "error" in normalized or "exception" in normalized:
        return ErrorTaxonomy.RUNTIME
    return ErrorTaxonomy.UNKNOWN


def _validate_local_model_availability(
    llm_client: object,
    execution_mode: str,
    model_name: str,
) -> None:
    if execution_mode != "real_local":
        return

    if not isinstance(llm_client, OllamaLLMClient):
        return

    installed_models = llm_client.list_installed_models()
    if model_name not in installed_models:
        raise LLMModelNotFoundError(
            f"Ollama model '{model_name}' is not installed. Install it with `ollama pull {model_name}`."
        )
