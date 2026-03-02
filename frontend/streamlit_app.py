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
    render_top_insights,
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
from frontend.utils.formatters import as_int, dt, mode_badge, pct  # noqa: E402


st.set_page_config(page_title="LLM Reliability Dashboard", layout="wide")


@st.cache_data(show_spinner=False)
def load_dashboard_data() -> tuple[pd.DataFrame, pd.DataFrame, pd.DataFrame, str, str]:
    provider = DataProvider(project_root=PROJECT_ROOT)
    data = provider.load()
    return data.runs, data.cases, data.results, data.source, data.note


def main() -> None:
    st.title("LLM Reliability Analytics Dashboard")
    st.caption("Structured evaluation of LLM systems across test cases, oracles, and aggregated reliability metrics.")

    runs_df, _cases_df, results_df, source, note = load_dashboard_data()
    adapter = MetricsAdapter()

    run_options_df = adapter.run_selector_options(runs_df=runs_df, results_df=results_df)
    if run_options_df.empty:
        st.warning("No runs available. Load data into DuckDB or provide test_results CSV/Parquet exports.")
        st.stop()

    label_by_run_id = {
        str(row["run_id"]): str(row["run_label"])
        for _, row in run_options_df.iterrows()
    }
    ordered_run_ids = run_options_df["run_id"].astype(str).tolist()

    st.sidebar.header("Run Selection")
    selected_run_id = st.sidebar.selectbox(
        "Choose run",
        ordered_run_ids,
        format_func=lambda run_id: label_by_run_id.get(str(run_id), str(run_id)),
    )

    with st.sidebar.expander("Data source details"):
        st.write(f"Source: **{source}**")
        if note:
            st.write(note)

    run_meta = _run_meta_for_id(runs_df=runs_df, run_id=selected_run_id)
    report = adapter.build_report_for_run(results_df=results_df, run_id=selected_run_id, runs_df=runs_df)
    run_rows = results_df[results_df["run_id"].astype(str) == str(selected_run_id)].copy()

    previous_run_id = adapter.latest_previous_run_id(runs_df=runs_df, run_id=selected_run_id)
    previous_report = (
        adapter.build_report_for_run(results_df=results_df, run_id=previous_run_id, runs_df=runs_df)
        if previous_run_id is not None
        else None
    )
    improvement_status = adapter.improvement_status_vs_previous(current_report=report, previous_report=previous_report)
    insights = adapter.build_insights(report=report, improvement_status=improvement_status)

    # Presentation-critical section: clear top-level run context before metrics/charts.
    st.subheader("Run Summary")
    _render_run_summary(meta=run_meta)
    _render_mode_badge(run_mode=str(run_meta.get("mode", "mock")))

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

    # 1) Overview: first screen for a 5-minute walkthrough.
    with tabs[0]:
        render_kpi_cards(report)
        render_overview_summary(report)
        render_top_insights(insights)

        with st.expander("How reliability score is calculated"):
            st.markdown(
                """
                Reliability score is a weighted composite:
                - `0.35 * accuracy`
                - `0.15 * consistency_score`
                - `0.15 * repeatability_score`
                - `0.10 * schema_compliance_rate`
                - `0.10 * (1 - critical_error_rate)`
                - `0.10 * latency_score`
                - `0.05 * failure_density_score`

                This weighting keeps correctness as the primary signal while still accounting for stability and operational quality.
                """
            )

        if str(run_meta.get("mode", "")).lower() == "mock" and report.average_latency_ms < 50:
            st.info("Latency values are simulated/mock latency in this run mode and are not real network/API timings.")

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

        critical_count = int(run_rows["critical_error_flag"].fillna(False).astype(bool).sum())
        st.info(f"Critical errors: **{critical_count}** / **{report.total_test_cases}** attempts")

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
        if len(ordered_run_ids) < 2:
            st.info("At least two runs are required for run comparison.")
        else:
            comp_col1, comp_col2 = st.columns(2)
            with comp_col1:
                baseline_run_id = st.selectbox(
                    "Baseline run",
                    ordered_run_ids,
                    index=0,
                    key="baseline_run",
                    format_func=lambda run_id: label_by_run_id.get(str(run_id), str(run_id)),
                )
            with comp_col2:
                default_candidate_index = 1 if len(ordered_run_ids) > 1 else 0
                candidate_run_id = st.selectbox(
                    "Candidate run",
                    ordered_run_ids,
                    index=default_candidate_index,
                    key="candidate_run",
                    format_func=lambda run_id: label_by_run_id.get(str(run_id), str(run_id)),
                )

            if baseline_run_id == candidate_run_id:
                st.warning("Select two different runs for comparison.")
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

    # 6) Raw Results: transparent attempt-level drill-down.
    with tabs[5]:
        filtered_df = results_df.copy()

        selected_runs = st.multiselect(
            "run",
            ordered_run_ids,
            default=[selected_run_id],
            format_func=lambda run_id: label_by_run_id.get(str(run_id), str(run_id)),
        )
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
            "attempt_index",
            "category",
            "oracle_type",
            "actual_answer",
            "expected_answer",
            "normalized_answer",
            "is_correct",
            "score",
            "latency_ms",
            "latency_source",
            "error_type",
            "critical_error_flag",
            "timestamp",
        ]
        table_columns = [column for column in table_columns if column in filtered_df.columns]
        render_raw_results_table(filtered_df[table_columns])


def _run_meta_for_id(runs_df: pd.DataFrame, run_id: str) -> dict[str, object]:
    if runs_df.empty:
        return {
            "run_id": run_id,
            "run_label": run_id,
            "model_name": "unknown-model",
            "provider": "local",
            "dataset_version": "v1",
            "created_at": None,
            "mode": "mock",
            "repeat_count": 1,
            "model_version": "n/a",
            "temperature": 0.0,
            "notes": "",
        }

    row = runs_df[runs_df["run_id"].astype(str) == str(run_id)]
    if row.empty:
        return {
            "run_id": run_id,
            "run_label": run_id,
            "model_name": "unknown-model",
            "provider": "local",
            "dataset_version": "v1",
            "created_at": None,
            "mode": "mock",
            "repeat_count": 1,
            "model_version": "n/a",
            "temperature": 0.0,
            "notes": "",
        }

    data = row.iloc[0].to_dict()
    data.setdefault("run_id", run_id)
    data.setdefault("run_label", run_id)
    data.setdefault("model_name", "unknown-model")
    data.setdefault("provider", "local")
    data.setdefault("dataset_version", "v1")
    data.setdefault("created_at", None)
    data.setdefault("mode", "mock")
    data.setdefault("repeat_count", 1)
    data.setdefault("model_version", "n/a")
    data.setdefault("temperature", 0.0)
    data.setdefault("notes", "")
    return data


def _render_run_summary(meta: dict[str, object]) -> None:
    c1, c2, c3, c4 = st.columns(4)
    c1.write(f"**Run Label:** {meta.get('run_label', '-')}")
    c2.write(f"**Model:** {meta.get('model_name', '-')}")
    c3.write(f"**Provider:** {meta.get('provider', '-')}")
    c4.write(f"**Model Version:** {meta.get('model_version', '-')}")

    c5, c6, c7, c8 = st.columns(4)
    c5.write(f"**Dataset Version:** {meta.get('dataset_version', '-')}")
    c6.write(f"**Created At:** {dt(meta.get('created_at'))}")
    c7.write(f"**Repeat Count:** {meta.get('repeat_count', '-')}")
    c8.write(f"**Temperature:** {meta.get('temperature', '-')}")

    notes = str(meta.get("notes", "") or "").strip()
    if notes:
        st.write(f"**Notes:** {notes}")


def _render_mode_badge(run_mode: str) -> None:
    badge = mode_badge(run_mode)
    normalized = run_mode.strip().lower()
    if normalized == "mock":
        st.info(f"Run Mode: **{badge}**")
    elif normalized == "real":
        st.success(f"Run Mode: **{badge}**")
    else:
        st.warning(f"Run Mode: **{badge}**")


if __name__ == "__main__":
    main()
