"""Concise textual insight helpers for hybrid evaluation runs."""

from __future__ import annotations

from typing import Any

from llm_reliability_analytics.analytics.reliability import ReliabilityReport
from llm_reliability_analytics.models.domain import TestResult


def generate_run_insights(
    report: ReliabilityReport,
    results: list[TestResult] | None = None,
    low_score_threshold: float = 0.2,
) -> dict[str, Any]:
    weakest_category = report.weakest_categories[0].category if report.weakest_categories else "n/a"
    most_common_error = report.most_frequent_error_types[0].error_type if report.most_frequent_error_types else "none"
    failure_heavy_source = (
        max(report.failure_by_source.items(), key=lambda item: item[1])[0]
        if report.failure_by_source
        else "none"
    )

    promotion_candidates: list[str] = []
    if results:
        for result in results:
            if (not result.is_correct) and result.score <= low_score_threshold:
                promotion_candidates.append(result.test_case_id)
        promotion_candidates = sorted(set(promotion_candidates))[:10]

    return {
        "weakest_category": weakest_category,
        "most_common_error_type": most_common_error,
        "failure_heavy_source": failure_heavy_source,
        "promotion_candidates": promotion_candidates,
    }
