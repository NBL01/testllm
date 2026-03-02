"""KPI cards for top-level run metrics."""

from __future__ import annotations

import streamlit as st

from frontend.utils.formatters import as_int, ms, pct, score
from llm_reliability_analytics.analytics.reliability import ReliabilityReport


def render_kpi_cards(report: ReliabilityReport) -> None:
    cols = st.columns(4)
    cols[0].metric("Unique Test Cases", as_int(report.unique_test_cases))
    cols[1].metric("Total Attempts", as_int(report.total_test_cases))
    cols[2].metric("Passed Attempts", as_int(report.passed))
    cols[3].metric("Failed Attempts", as_int(report.failed))

    cols2 = st.columns(4)
    cols2[0].metric("Accuracy", pct(report.accuracy))
    cols2[1].metric("Avg Latency", ms(report.average_latency_ms))
    cols2[2].metric("P95 Latency", ms(report.p95_latency_ms))
    cols2[3].metric("Reliability Score", score(report.overall_reliability_score))

    cols3 = st.columns(5)
    cols3[0].metric("Category Coverage", pct(report.category_coverage))
    cols3[1].metric("Source Coverage", as_int(report.source_coverage))
    cols3[2].metric("Failure Concentration", pct(report.failure_concentration))
    cols3[3].metric("Zero-Score Categories", as_int(report.zero_score_categories))
    cols3[4].metric("Low-Score Cases", as_int(report.low_score_cases))
