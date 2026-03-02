from __future__ import annotations

import sys
from pathlib import Path

import pandas as pd
import streamlit as st

# Ensure both `frontend` and backend `src` modules are importable when running via Streamlit.
PROJECT_ROOT = Path(__file__).resolve().parents[1]
SRC_PATH = PROJECT_ROOT / "src"
for path in (PROJECT_ROOT, SRC_PATH):
    if str(path) not in sys.path:
        sys.path.insert(0, str(path))

from frontend.components.charts import (  # noqa: E402
    plot_category_accuracy,
    plot_category_accuracy_delta,
    plot_error_type_frequency,
    plot_oracle_pass_rate,
    plot_oracle_usage,
    plot_pass_fail_distribution,
    show_rate_table,
)
from frontend.components.insights import (  # noqa: E402
    render_category_insight,
    render_error_insight,
    render_overview_summary,
    render_run_comparison_summary,
)
from frontend.components.kpi_cards import render_kpi_cards  # noqa: E402
from frontend.components.tables import (  # noqa: E402
    render_category_table,
    render_error_table,
    render_problematic_cases,
    render_raw_results_table,
)
from frontend.services.data_provider import DataProvider  # noqa: E402
from frontend.services.metrics_adapter import MetricsAdapter  # noqa: E402
from frontend.utils.formatters import as_int, pct  # noqa: E402


st.set_page_config(page_title="LLM Reliability Dashboard", layout="wide")


@st.cache_data(show_spinner=False)
def load_dashboard_data() -> tuple[pd.DataFrame, pd.DataFrame, pd.DataFrame, str, str]:
    provider = DataProvider(project_root=PROJECT_ROOT)
    data = provider.load()
    return data.runs, data.cases, data.results, data.source, data.note


def main() -> None:
    st.title("LLM Reliability Analytics Dashboard")
    st.caption("Structured evaluation of LLM systems across test cases, oracles, and reliability metrics.")

    runs_df, cases_df, results_df, source, note = load_dashboard_data()
    adapter = MetricsAdapter()
    run_ids = adapter.available_run_ids(results_df)

    st.sidebar.header("Data")
    st.sidebar.write(f"Source: **{source}**")
    if note:
        st.sidebar.info(note)

    if not run_ids:
        st.warning("No runs available. Load data into DuckDB or provide test_results CSV/Parquet exports.")
        st.stop()

    selected_run_id = st.sidebar.selectbox("Select run_id", run_ids, index=0)

    report = adapter.build_report_for_run(results_df=results_df, run_id=selected_run_id, runs_df=runs_df)
    run_rows = results_df[results_df["run_id"].astype(str) == str(selected_run_id)].copy()

    tabs = st.tabs(
        [
            "Overview",
            "Category Analysis",
            "Error Analysis",
            "Oracle Analysis",
            "Run Comparison",
            "Raw Results",
        ]
    )

    # 1) Overview: first screen for quick project story in a short presentation.
    with tabs[0]:
        render_kpi_cards(report)
        render_overview_summary(report)

        col1, col2, col3 = st.columns(3)
        col1.metric("P95 Latency", f"{report.p95_latency_ms:.2f} ms")
        col2.metric("Consistency", f"{report.consistency_score:.3f}")
        col3.metric("Repeatability", f"{report.repeatability_score:.3f}")

    # 2) Category Analysis
    with tabs[1]:
        category_df = adapter.category_table(report)
        plot_category_accuracy(category_df)
        render_category_table(category_df)
        render_category_insight(report)

    # 3) Error Analysis
    with tabs[2]:
        error_df = adapter.error_distribution_table(report)
        pass_fail_df = adapter.pass_fail_distribution(report)

        c1, c2 = st.columns(2)
        with c1:
            plot_error_type_frequency(error_df)
        with c2:
            plot_pass_fail_distribution(pass_fail_df)

        problematic_df = adapter.problematic_cases(run_rows)
        st.subheader("Most Problematic Test Cases")
        render_problematic_cases(problematic_df)

        critical_count = int(round(report.critical_error_rate * report.total_test_cases))
        st.info(f"Critical errors (approx): **{critical_count}** / **{report.total_test_cases}**")

        st.subheader("Error Type Breakdown")
        render_error_table(error_df)
        render_error_insight(report)

    # 4) Oracle Analysis
    with tabs[3]:
        oracle_df = adapter.oracle_pass_rate_table(report=report, run_rows=run_rows)
        c1, c2 = st.columns(2)
        with c1:
            plot_oracle_pass_rate(oracle_df)
        with c2:
            plot_oracle_usage(oracle_df)

        st.subheader("Oracle Pass Rate and Usage")
        show_rate_table(oracle_df)

    # 5) Run Comparison
    with tabs[4]:
        if len(run_ids) < 2:
            st.info("At least two runs are required for run comparison.")
        else:
            comp_col1, comp_col2 = st.columns(2)
            with comp_col1:
                baseline_run_id = st.selectbox("Baseline run_id", run_ids, index=0, key="baseline_run")
            with comp_col2:
                default_candidate_index = 1 if len(run_ids) > 1 else 0
                candidate_run_id = st.selectbox(
                    "Candidate run_id",
                    run_ids,
                    index=default_candidate_index,
                    key="candidate_run",
                )

            if baseline_run_id == candidate_run_id:
                st.warning("Select two different run_ids for comparison.")
            else:
                bundle = adapter.compare_runs(
                    results_df=results_df,
                    runs_df=runs_df,
                    baseline_run_id=baseline_run_id,
                    candidate_run_id=candidate_run_id,
                )

                render_run_comparison_summary(bundle)

                metric_rows = [
                    {
                        "metric": "accuracy",
                        "baseline": bundle.baseline_report.accuracy,
                        "candidate": bundle.candidate_report.accuracy,
                        "delta": bundle.candidate_report.accuracy - bundle.baseline_report.accuracy,
                    },
                    {
                        "metric": "reliability_score",
                        "baseline": bundle.baseline_report.overall_reliability_score,
                        "candidate": bundle.candidate_report.overall_reliability_score,
                        "delta": (
                            bundle.candidate_report.overall_reliability_score
                            - bundle.baseline_report.overall_reliability_score
                        ),
                    },
                    {
                        "metric": "average_latency_ms",
                        "baseline": bundle.baseline_report.average_latency_ms,
                        "candidate": bundle.candidate_report.average_latency_ms,
                        "delta": (
                            bundle.candidate_report.average_latency_ms
                            - bundle.baseline_report.average_latency_ms
                        ),
                    },
                ]
                metric_df = pd.DataFrame(metric_rows)
                st.dataframe(metric_df, use_container_width=True, hide_index=True)

                st.subheader("Category-wise Accuracy Delta")
                plot_category_accuracy_delta(bundle.category_delta)

    # 6) Raw Results: filterable table for transparent drill-down.
    with tabs[5]:
        filtered_df = results_df.copy()

        selected_runs = st.multiselect("run_id", run_ids, default=[selected_run_id])
        if selected_runs:
            filtered_df = filtered_df[filtered_df["run_id"].astype(str).isin(selected_runs)]

        categories = sorted(filtered_df["category"].dropna().astype(str).unique().tolist())
        selected_categories = st.multiselect("category", categories, default=categories)
        if selected_categories:
            filtered_df = filtered_df[filtered_df["category"].astype(str).isin(selected_categories)]

        oracle_types = sorted(filtered_df["oracle_type"].dropna().astype(str).unique().tolist())
        selected_oracles = st.multiselect("oracle_type", oracle_types, default=oracle_types)
        if selected_oracles:
            filtered_df = filtered_df[filtered_df["oracle_type"].astype(str).isin(selected_oracles)]

        correctness_filter = st.multiselect("is_correct", [True, False], default=[True, False])
        filtered_df = filtered_df[filtered_df["is_correct"].isin(correctness_filter)]

        error_options = sorted(
            [value for value in filtered_df["error_type"].dropna().astype(str).unique().tolist() if value]
        )
        selected_errors = st.multiselect("error_type", error_options)
        if selected_errors:
            filtered_df = filtered_df[filtered_df["error_type"].astype(str).isin(selected_errors)]

        sort_column = st.selectbox("Sort by", ["latency_ms", "score", "timestamp"]) 
        descending = st.checkbox("Sort descending", value=(sort_column != "latency_ms"))

        if sort_column in filtered_df.columns:
            filtered_df = filtered_df.sort_values(sort_column, ascending=not descending)

        st.caption(
            f"Rows shown: **{as_int(len(filtered_df))}** | "
            f"Pass rate in filtered set: **{pct(filtered_df['is_correct'].mean() if not filtered_df.empty else 0.0)}**"
        )

        table_columns = [
            "result_id",
            "run_id",
            "test_case_id",
            "category",
            "oracle_type",
            "actual_answer",
            "expected_answer",
            "is_correct",
            "score",
            "latency_ms",
            "error_type",
            "timestamp",
        ]
        table_columns = [column for column in table_columns if column in filtered_df.columns]
        render_raw_results_table(filtered_df[table_columns])


if __name__ == "__main__":
    main()
