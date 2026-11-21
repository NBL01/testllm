"""Run metrics computed from stored attempts.

Attempt-level counts (pass rate, failure types, category and oracle pass rates) count every
attempt; pass@k and pass^k count unique cases. Nothing here is a composite score: each number
answers one question and is shown with its denominator.
"""

from collections import Counter, defaultdict
from math import ceil

from pydantic import BaseModel, Field

from llm_reliability_analytics.models.domain import CategoryLevelReport, TestResult


class ReliabilityReport(BaseModel):
    run_id: str = "unknown-run"
    dataset_version: str = "v1"
    total_test_cases: int = Field(ge=0, description="Attempts (cases x repeats).")
    unique_test_cases: int = Field(default=0, ge=0)
    passed: int = Field(ge=0)
    failed: int = Field(ge=0)
    accuracy: float = Field(ge=0.0, le=1.0, description="Pass rate over attempts.")
    # None means "not measurable", never zero.
    repeat_k: int | None = Field(default=None, ge=2)
    pass_at_k: float | None = Field(default=None, ge=0.0, le=1.0)
    pass_hat_k: float | None = Field(default=None, ge=0.0, le=1.0)
    schema_case_count: int = Field(default=0, ge=0)
    schema_attempt_count: int = Field(default=0, ge=0)
    schema_pass_rate: float | None = Field(default=None, ge=0.0, le=1.0)
    average_latency_ms: float = Field(default=0.0, ge=0.0)
    p50_latency_ms: float = Field(default=0.0, ge=0.0)
    p95_latency_ms: float = Field(default=0.0, ge=0.0)
    latency_sources: dict[str, int] = Field(default_factory=dict)
    category_reports: list[CategoryLevelReport] = Field(default_factory=list)
    oracle_type_pass_rate: dict[str, float] = Field(default_factory=dict)
    error_distribution: dict[str, int] = Field(default_factory=dict)
    measurement_notes: list[str] = Field(default_factory=list)


def compute_reliability_report(
    results: list[TestResult],
    run_id: str | None = None,
    dataset_version: str | None = None,
) -> ReliabilityReport:
    resolved_run_id = run_id or (results[0].run_id if results else "unknown-run")
    resolved_dataset_version = dataset_version or (results[0].dataset_version if results else "v1") or "v1"
    if not results:
        return ReliabilityReport(run_id=resolved_run_id, dataset_version=resolved_dataset_version,
                                 total_test_cases=0, passed=0, failed=0, accuracy=0.0,
                                 measurement_notes=["No attempts were recorded for this run."])

    total = len(results)
    passed = sum(1 for result in results if result.is_correct)
    schema_results = [result for result in results if result.oracle_type == "json_schema"]
    latencies = [result.latency_ms for result in results]
    repeat_k, pass_at_k, pass_hat_k = _compute_pass_k(results)
    latency_sources = dict(sorted(Counter(result.latency_source or "unknown" for result in results).items()))
    return ReliabilityReport(
        run_id=resolved_run_id,
        dataset_version=resolved_dataset_version,
        total_test_cases=total,
        unique_test_cases=len({result.test_case_id for result in results}),
        passed=passed,
        failed=total - passed,
        accuracy=passed / total,
        repeat_k=repeat_k,
        pass_at_k=pass_at_k,
        pass_hat_k=pass_hat_k,
        schema_case_count=len({result.test_case_id for result in schema_results}),
        schema_attempt_count=len(schema_results),
        schema_pass_rate=(sum(result.is_correct for result in schema_results) / len(schema_results)) if schema_results else None,
        average_latency_ms=sum(latencies) / total,
        p50_latency_ms=_nearest_rank(latencies, 0.50),
        p95_latency_ms=_nearest_rank(latencies, 0.95),
        latency_sources=latency_sources,
        category_reports=_compute_category_reports(results),
        oracle_type_pass_rate=_pass_rates(results, lambda result: result.oracle_type or "unknown"),
        error_distribution=dict(Counter(result.error_type for result in results if result.error_type)),
        measurement_notes=_measurement_notes(repeat_k, bool(schema_results), latency_sources),
    )


def _measurement_notes(repeat_k: int | None, has_schema: bool, latency_sources: dict[str, int]) -> list[str]:
    notes = ["Pass rate, failure types and category rates count attempts; pass@k and pass^k count unique cases."]
    if repeat_k is None:
        notes.append("pass@k and pass^k need the same number of attempts (2 or more) for every case.")
    if not has_schema:
        notes.append("No json_schema cases: the schema-only pass rate is not measured.")
    if "mock_simulated" in latency_sources:
        notes.append("Mock latency is simulated, not real model performance.")
    return notes


def _compute_category_reports(results: list[TestResult]) -> list[CategoryLevelReport]:
    grouped: dict[str, list[TestResult]] = defaultdict(list)
    for result in results:
        grouped[result.category or "unknown"].append(result)
    reports = []
    for category, rows in sorted(grouped.items()):
        passed = sum(1 for result in rows if result.is_correct)
        reports.append(CategoryLevelReport(
            category=category, total_test_cases=len(rows), passed=passed, failed=len(rows) - passed,
            accuracy=passed / len(rows), average_latency_ms=sum(result.latency_ms for result in rows) / len(rows),
        ))
    return reports


def _pass_rates(results: list[TestResult], key) -> dict[str, float]:
    grouped: dict[str, list[bool]] = defaultdict(list)
    for result in results:
        grouped[key(result)].append(result.is_correct)
    return {name: sum(outcomes) / len(outcomes) for name, outcomes in sorted(grouped.items())}


def _nearest_rank(values: list[float], quantile: float) -> float:
    if not values:
        return 0.0
    sorted_values = sorted(values)
    return float(sorted_values[max(1, ceil(quantile * len(sorted_values))) - 1])


def _compute_pass_k(results: list[TestResult]) -> tuple[int | None, float | None, float | None]:
    """pass@k (any of k attempts passes) and pass^k (all k pass) over unique cases.

    Only defined when every case has the same k >= 2 attempts; partial or single-attempt
    runs return None rather than mixing different k values.
    """
    outcomes: dict[str, list[bool]] = defaultdict(list)
    for result in results:
        outcomes[result.test_case_id].append(result.is_correct)
    attempt_counts = {len(case) for case in outcomes.values()}
    if len(attempt_counts) != 1 or (k := attempt_counts.pop()) < 2:
        return None, None, None
    cases = len(outcomes)
    return k, sum(any(case) for case in outcomes.values()) / cases, sum(all(case) for case in outcomes.values()) / cases
