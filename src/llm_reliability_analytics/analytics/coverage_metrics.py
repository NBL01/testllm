"""Coverage-oriented metrics for hybrid evaluation datasets."""

from __future__ import annotations

from collections import Counter, defaultdict
from dataclasses import dataclass

from llm_reliability_analytics.models.domain import TestResult

REGRESSION_EXPECTED_CATEGORIES = {
    "factual_qa",
    "classification",
    "information_extraction",
    "numeric_reasoning",
    "format_constrained_json",
    "instruction_following",
    "consistency_check",
}

ADVERSARIAL_EXPECTED_CATEGORIES = {
    "safety_boundary",
    "format_breaking",
    "prompt_override",
    "ambiguous_instruction",
    "refusal_check",
}

EXPECTED_CATEGORIES_BY_SOURCE: dict[str, set[str]] = {
    "regression": REGRESSION_EXPECTED_CATEGORIES,
    "synthetic": REGRESSION_EXPECTED_CATEGORIES,
    "adversarial": ADVERSARIAL_EXPECTED_CATEGORIES,
}


@dataclass
class CoverageMetrics:
    category_coverage: float
    source_coverage: int
    failure_concentration: float
    zero_score_categories: int
    low_score_cases: int
    source_distribution: dict[str, int]
    failure_by_source: dict[str, int]


def compute_coverage_metrics(
    results: list[TestResult],
    low_score_threshold: float = 0.3,
    expected_categories: set[str] | None = None,
) -> CoverageMetrics:
    if not results:
        return CoverageMetrics(
            category_coverage=0.0,
            source_coverage=0,
            failure_concentration=0.0,
            zero_score_categories=0,
            low_score_cases=0,
            source_distribution={},
            failure_by_source={},
        )

    categories_present = {result.category or "unknown" for result in results}
    expected = expected_categories or _resolve_expected_categories(results)
    total_expected = max(1, len(expected))
    category_coverage = len(categories_present.intersection(expected)) / total_expected

    sources = [result.test_source or "regression" for result in results]
    source_distribution = dict(Counter(sources))
    source_coverage = len(source_distribution)

    low_score_cases = sum(1 for result in results if result.score < low_score_threshold)

    category_stats: dict[str, list[bool]] = defaultdict(list)
    failures_by_category: Counter[str] = Counter()
    failures_by_source: Counter[str] = Counter()
    total_failures = 0

    for result in results:
        category = result.category or "unknown"
        source = result.test_source or "regression"
        category_stats[category].append(result.is_correct)
        if not result.is_correct:
            total_failures += 1
            failures_by_category[category] += 1
            failures_by_source[source] += 1

    zero_score_categories = sum(
        1
        for values in category_stats.values()
        if values and (sum(1 for value in values if value) / len(values)) == 0.0
    )

    if total_failures == 0:
        failure_concentration = 0.0
    else:
        failure_concentration = max(failures_by_category.values()) / total_failures

    return CoverageMetrics(
        category_coverage=category_coverage,
        source_coverage=source_coverage,
        failure_concentration=failure_concentration,
        zero_score_categories=zero_score_categories,
        low_score_cases=low_score_cases,
        source_distribution=source_distribution,
        failure_by_source=dict(failures_by_source),
    )


def _resolve_expected_categories(results: list[TestResult]) -> set[str]:
    sources = {str(result.test_source or "regression").strip().lower() for result in results}
    expected: set[str] = set()
    for source in sources:
        expected.update(EXPECTED_CATEGORIES_BY_SOURCE.get(source, set()))

    if expected:
        return expected
    return {result.category or "unknown" for result in results}
