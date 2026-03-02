"""KPI cards for top-level run metrics."""

from __future__ import annotations

import streamlit as st

from frontend.utils.formatters import as_int, ms, pct, score
from llm_reliability_analytics.analytics.reliability import ReliabilityReport


def render_kpi_cards(report: ReliabilityReport) -> None:
    cols = st.columns(6)
    cols[0].metric("Total Cases", as_int(report.total_test_cases))
    cols[1].metric("Passed", as_int(report.passed))
    cols[2].metric("Failed", as_int(report.failed))
    cols[3].metric("Accuracy", pct(report.accuracy))
    cols[4].metric("Avg Latency", ms(report.average_latency_ms))
    cols[5].metric("Reliability", score(report.overall_reliability_score))
