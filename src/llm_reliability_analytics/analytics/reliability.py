from collections import Counter, defaultdict

from pydantic import BaseModel, Field

from llm_reliability_analytics.models.domain import TestResult


class ReliabilityReport(BaseModel):
    total_test_cases: int = Field(ge=0)
    passed: int = Field(ge=0)
    failed: int = Field(ge=0)
    accuracy: float = Field(ge=0.0, le=1.0)
    average_latency_ms: float = Field(ge=0.0)
    category_wise_accuracy: dict[str, float] = Field(default_factory=dict)
    error_distribution: dict[str, int] = Field(default_factory=dict)
    consistency_score: float = Field(ge=0.0, le=1.0)
    overall_reliability_score: float = Field(ge=0.0, le=1.0)


def compute_reliability_report(
    results: list[TestResult],
    latency_slo_ms: float = 1000.0,
) -> ReliabilityReport:
    """Compute reliability analytics from a list of TestResult objects.

    Explicit formulas used:
    - total_test_cases = len(results)
    - passed = count(is_correct == True)
    - failed = total_test_cases - passed
    - accuracy = passed / total_test_cases
    - average_latency_ms = sum(latency_ms) / total_test_cases
    - category accuracy = passed_in_category / total_in_category
    - consistency_score (placeholder) = max(0, 1 - stddev(scores))
    - latency_score = max(0, 1 - average_latency_ms / latency_slo_ms)
    - overall_reliability_score = 0.6*accuracy + 0.3*consistency_score + 0.1*latency_score
    """
    total_test_cases = len(results)
    if total_test_cases == 0:
        return ReliabilityReport(
            total_test_cases=0,
            passed=0,
            failed=0,
            accuracy=0.0,
            average_latency_ms=0.0,
            category_wise_accuracy={},
            error_distribution={},
            consistency_score=0.0,
            overall_reliability_score=0.0,
        )

    passed = sum(1 for result in results if result.is_correct)
    failed = total_test_cases - passed

    accuracy = passed / total_test_cases
    average_latency_ms = sum(result.latency_ms for result in results) / total_test_cases

    category_wise_accuracy = _compute_category_wise_accuracy(results)
    error_distribution = dict(Counter(result.error_type for result in results if result.error_type))

    consistency_score = _compute_consistency_placeholder(results)
    latency_score = _compute_latency_score(average_latency_ms=average_latency_ms, latency_slo_ms=latency_slo_ms)

    overall_reliability_score = _clamp01(
        (0.6 * accuracy) + (0.3 * consistency_score) + (0.1 * latency_score)
    )

    return ReliabilityReport(
        total_test_cases=total_test_cases,
        passed=passed,
        failed=failed,
        accuracy=accuracy,
        average_latency_ms=average_latency_ms,
        category_wise_accuracy=category_wise_accuracy,
        error_distribution=error_distribution,
        consistency_score=consistency_score,
        overall_reliability_score=overall_reliability_score,
    )


def _compute_category_wise_accuracy(results: list[TestResult]) -> dict[str, float]:
    grouped: dict[str, list[bool]] = defaultdict(list)

    for result in results:
        category = result.category or "unknown"
        grouped[category].append(result.is_correct)

    category_accuracy: dict[str, float] = {}
    for category, outcomes in grouped.items():
        category_accuracy[category] = sum(1 for outcome in outcomes if outcome) / len(outcomes)
    return category_accuracy


def _compute_consistency_placeholder(results: list[TestResult]) -> float:
    """Placeholder consistency metric based on score variance in one run.

    Lower variance in `score` implies more stable outputs. This is not true
    multi-run consistency yet, but it is simple and explainable for demo use.
    """
    if not results:
        return 0.0

    scores = [result.score for result in results]
    mean_score = sum(scores) / len(scores)
    variance = sum((score - mean_score) ** 2 for score in scores) / len(scores)
    stddev = variance**0.5
    return _clamp01(1.0 - stddev)


def _compute_latency_score(average_latency_ms: float, latency_slo_ms: float) -> float:
    if latency_slo_ms <= 0:
        return 0.0
    return _clamp01(1.0 - (average_latency_ms / latency_slo_ms))


def _clamp01(value: float) -> float:
    return max(0.0, min(1.0, value))
