"""Failure-focused views to explain zero/low category scores."""

from __future__ import annotations

import pandas as pd
import streamlit as st

from frontend.utils.formatters import pct


def render_low_score_category_breakdown(run_rows: pd.DataFrame, low_accuracy_threshold: float = 0.2) -> None:
    if run_rows.empty:
        st.info("No results available for failure breakdown.")
        return

    grouped = (
        run_rows.groupby("category", dropna=False)["is_correct"]
        .agg(total_cases="count", passed="sum")
        .reset_index()
    )
    grouped["failed"] = grouped["total_cases"] - grouped["passed"]
    grouped["accuracy"] = grouped["passed"] / grouped["total_cases"]

    low_df = grouped[grouped["accuracy"] <= low_accuracy_threshold].copy()
    if low_df.empty:
        st.success("No category is below the current low-score threshold.")
        return

    low_df = low_df.sort_values(["accuracy", "failed"], ascending=[True, False])
    display = low_df.copy()
    display["accuracy"] = display["accuracy"].apply(pct)
    st.dataframe(display, use_container_width=True, hide_index=True)


def render_top_failure_causes_per_category(run_rows: pd.DataFrame, category: str, top_n: int = 5) -> None:
    scoped = run_rows[
        (run_rows["category"].astype(str) == str(category))
        & (~run_rows["is_correct"].astype(bool))
    ].copy()
    if scoped.empty:
        st.info("No failures for selected category.")
        return

    causes = (
        scoped.assign(error_type=scoped["error_type"].astype(str).replace("", "wrong_answer"))
        .groupby("error_type", dropna=False)["result_id"]
        .count()
        .reset_index(name="count")
        .sort_values(["count", "error_type"], ascending=[False, True])
        .head(top_n)
    )
    st.dataframe(causes, use_container_width=True, hide_index=True)


def render_failed_cases_table(run_rows: pd.DataFrame, category: str, top_n: int = 30) -> pd.DataFrame:
    scoped = run_rows[
        (run_rows["category"].astype(str) == str(category))
        & (~run_rows["is_correct"].astype(bool))
    ].copy()
    if scoped.empty:
        st.info("No failed cases in selected category.")
        return scoped

    columns = [
        "result_id",
        "test_case_id",
        "prompt",
        "raw_output",
        "expected_answer",
        "oracle_type",
        "error_type",
        "explanation",
        "score",
    ]
    columns = [column for column in columns if column in scoped.columns]
    scoped = scoped.sort_values(["score", "latency_ms"], ascending=[True, False]).head(top_n)
    st.dataframe(scoped[columns], use_container_width=True, hide_index=True)
    return scoped
