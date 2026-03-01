"""Core MVP workflow.

This module keeps the architecture easy to explain:
1) load validated test cases
2) run batch with mock LLM + oracle scoring
3) store results in DuckDB
4) compute and return analytics report
"""

from typing import Literal

from pydantic import BaseModel, Field

from llm_reliability_analytics.analytics.reliability import (
    ReliabilityReport,
    compute_reliability_report,
)
from llm_reliability_analytics.ingestion.loader import load_test_cases
from llm_reliability_analytics.models.domain import ErrorTaxonomy, TestCase, TestResult
from llm_reliability_analytics.oracles import evaluate_with_oracle, normalize_answer
from llm_reliability_analytics.runner.mock_client import MockLLMClient
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


class RunNotFoundError(ValueError):
    """Raised when run_id does not exist in storage."""


class LoadCasesResult(BaseModel):
    input_path: str
    total_rows: int
    valid_rows: int
    invalid_rows: int
    dataset_versions: list[str] = Field(default_factory=list)
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
        category_distribution=summary.category_distribution,
        oracle_type_distribution=summary.oracle_type_distribution,
        stored_test_cases=stored_test_cases,
    )


def run_batch_workflow(
    input_path: str,
    run_name: str,
    model_name: str,
    dataset_version: str | None = None,
    run_group_id: str | None = None,
    mode: Literal["deterministic", "semi_random"] = "deterministic",
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

    resolved_dataset_version = dataset_version or test_cases[0].dataset_version
    for test_case in test_cases:
        test_case.dataset_version = resolved_dataset_version

    upsert_test_cases(test_cases)
    run = create_test_run(
        name=run_name,
        model_name=model_name,
        dataset_version=resolved_dataset_version,
        run_group_id=run_group_id,
    )

    runner = TestRunner(llm_client=MockLLMClient(mode=mode, seed=seed))
    results = runner.run(test_cases, run_id=run.id, repeats_per_case=repeats_per_case)
    score_results_with_oracles(test_cases=test_cases, results=results)
    insert_batch_results(results)

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
            result.error_taxonomy = ErrorTaxonomy.VALIDATION
            continue

        result.dataset_version = test_case.dataset_version
        result.oracle_type = test_case.oracle_type.value
        result.expected_answer_normalized = normalize_answer(test_case.expected_answer)
        result.actual_answer_normalized = normalize_answer(result.actual_answer)
        result.error_taxonomy = _taxonomy_from_error_type(result.error_type)

        oracle_type = oracle_mapping.get(test_case.oracle_type.value, "exact_match")
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
            if result.error_type is None:
                result.error_taxonomy = ErrorTaxonomy.NONE
        except Exception as exc:  # noqa: BLE001 - batch should continue on single-case failures
            result.is_correct = False
            result.score = 0.0
            result.error_type = result.error_type or f"oracle_{type(exc).__name__}"
            result.error_taxonomy = ErrorTaxonomy.ORACLE


def _taxonomy_from_error_type(error_type: str | None) -> ErrorTaxonomy:
    if error_type is None:
        return ErrorTaxonomy.NONE

    normalized = error_type.strip().lower()
    if normalized in {"wrong_answer", "incorrect_answer"}:
        return ErrorTaxonomy.NONE
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
