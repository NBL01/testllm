"""Tabular views for analysis sections."""

from __future__ import annotations

import pandas as pd
import streamlit as st

from frontend.utils.formatters import pct


def render_category_table(category_df: pd.DataFrame) -> None:
    if category_df.empty:
        st.info("No category rows to display.")
        return

    display_df = category_df.copy()
    display_df["accuracy"] = display_df["accuracy"].apply(pct)
    display_df["average_latency_ms"] = display_df["average_latency_ms"].round(2)
    st.dataframe(display_df, use_container_width=True, hide_index=True)


def render_error_table(error_df: pd.DataFrame) -> None:
    if error_df.empty:
        st.info("No error table available.")
        return

    st.dataframe(error_df, use_container_width=True, hide_index=True)


def render_problematic_cases(problem_df: pd.DataFrame) -> None:
    if problem_df.empty:
        st.info("No problematic cases detected for this run.")
        return

    display_df = problem_df.copy()
    if "failure_rate" in display_df.columns:
        display_df["failure_rate"] = display_df["failure_rate"].apply(pct)
    if "avg_score" in display_df.columns:
        display_df["avg_score"] = display_df["avg_score"].round(3)
    if "avg_latency_ms" in display_df.columns:
        display_df["avg_latency_ms"] = display_df["avg_latency_ms"].round(2)

    st.dataframe(display_df, use_container_width=True, hide_index=True)


def render_raw_results_table(raw_df: pd.DataFrame) -> None:
    if raw_df.empty:
        st.info("No rows match the current filters.")
        return

    st.dataframe(raw_df, use_container_width=True, hide_index=True)
