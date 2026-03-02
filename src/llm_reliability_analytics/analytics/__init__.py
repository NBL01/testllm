"""Analytics module."""

from llm_reliability_analytics.analytics.coverage_metrics import CoverageMetrics, compute_coverage_metrics
from llm_reliability_analytics.analytics.insights import generate_run_insights
from llm_reliability_analytics.analytics.reliability import (
    FrequentErrorTypeSummary,
    ReliabilityReport,
    RunComparisonItem,
    RunComparisonReport,
    WeakCategorySummary,
    compute_run_comparison_report,
    compute_reliability_report,
)

__all__ = [
    "ReliabilityReport",
    "WeakCategorySummary",
    "FrequentErrorTypeSummary",
    "RunComparisonItem",
    "RunComparisonReport",
    "compute_reliability_report",
    "compute_run_comparison_report",
    "CoverageMetrics",
    "compute_coverage_metrics",
    "generate_run_insights",
]
