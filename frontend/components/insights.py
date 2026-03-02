"""Concise textual insights for presentation narration."""

from __future__ import annotations

import streamlit as st

from frontend.services.metrics_adapter import RunComparisonBundle, RunInsights
from frontend.utils.formatters import delta_label, ms, pct, score
from llm_reliability_analytics.analytics.reliability import ReliabilityReport


def render_overview_summary(report: ReliabilityReport) -> None:
    st.markdown(
        (
            f"This run evaluated **{report.unique_test_cases}** unique test cases over "
            f"**{report.total_test_cases}** processed attempts. "
            f"Accuracy is **{pct(report.accuracy)}**, average latency is **{ms(report.average_latency_ms)}**, "
            f"and reliability score is **{score(report.overall_reliability_score)}**."
        )
    )


def render_category_insight(report: ReliabilityReport) -> None:
    if not report.weakest_categories:
        st.info("No weakest category identified.")
        return

    weakest = report.weakest_categories[0]
    st.warning(
        f"Weakest category: **{weakest.category}** "
        f"(accuracy={pct(weakest.accuracy)}, failed={weakest.failed}/{weakest.total_test_cases})."
    )


def render_error_insight(report: ReliabilityReport) -> None:
    if not report.most_frequent_error_types:
        st.success("No recurring error type was observed in this run.")
        return

    top_error = report.most_frequent_error_types[0]
    st.warning(
        f"Most frequent error: **{top_error.error_type}** "
        f"(count={top_error.count}, rate={pct(top_error.rate)})."
    )


def render_top_insights(insights: RunInsights) -> None:
    st.subheader("Insights")
    c1, c2, c3, c4, c5 = st.columns(5)
    c1.metric("Weakest Category", insights.weakest_category)
    c2.metric("Strongest Category", insights.strongest_category)
    c3.metric("Top Error Type", insights.most_frequent_error_type)
    c4.metric("Vs Previous Run", insights.improvement_status.replace("_", " ").title())
    c5.metric("Failures Concentrated In", insights.failure_heavy_source)
    st.caption(insights.promotion_hint)


def render_run_comparison_summary(bundle: RunComparisonBundle) -> None:
    baseline = bundle.baseline_report
    candidate = bundle.candidate_report

    accuracy_delta = candidate.accuracy - baseline.accuracy
    reliability_delta = candidate.overall_reliability_score - baseline.overall_reliability_score
    latency_delta = candidate.average_latency_ms - baseline.average_latency_ms

    st.markdown(
        (
            f"Accuracy: **{delta_label(accuracy_delta, positive_is_good=True)}** "
            f"({pct(baseline.accuracy)} -> {pct(candidate.accuracy)})."
        )
    )
    st.markdown(
        (
            f"Reliability score: **{delta_label(reliability_delta, positive_is_good=True)}** "
            f"({score(baseline.overall_reliability_score)} -> {score(candidate.overall_reliability_score)})."
        )
    )
    st.markdown(
        (
            f"Average latency: **{delta_label(latency_delta, positive_is_good=False)}** "
            f"({ms(baseline.average_latency_ms)} -> {ms(candidate.average_latency_ms)})."
        )
    )
