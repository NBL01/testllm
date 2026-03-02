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
from frontend.components.failure_insights import (  # noqa: E402
    render_failed_cases_table,
    render_low_score_category_breakdown,
    render_top_failure_causes_per_category,
)
from frontend.components.insights import (  # noqa: E402
    render_category_insight,
    render_error_insight,
    render_overview_summary,
    render_run_comparison_summary,
    render_top_insights,
)
from frontend.components.kpi_cards import render_kpi_cards  # noqa: E402
from frontend.components.result_inspector import render_result_inspector  # noqa: E402
from frontend.components.tables import (  # noqa: E402
    render_category_table,
    render_error_table,
    render_problematic_cases,
    render_raw_results_table,
)
from frontend.services.data_provider import DataProvider  # noqa: E402
from frontend.services.metrics_adapter import MetricsAdapter  # noqa: E402
from frontend.services.result_inspector import fetch_result_trace, fetch_results_by_category  # noqa: E402
from frontend.services.run_launcher import LaunchRequest, RunLauncher  # noqa: E402
from frontend.services.trace_service import mark_trace_candidate  # noqa: E402
from frontend.utils.formatters import as_int, dt, mode_badge, pct  # noqa: E402


st.set_page_config(page_title="LLM Reliability Dashboard", layout="wide")


@st.cache_data(show_spinner=False)
def load_dashboard_data(_db_signature: str) -> tuple[pd.DataFrame, pd.DataFrame, pd.DataFrame, str, str, str]:
    provider = DataProvider(project_root=PROJECT_ROOT)
    data = provider.load()
    return data.runs, data.cases, data.results, data.source, data.note, str(provider.db_path)


@st.cache_resource(show_spinner=False)
def get_run_launcher() -> RunLauncher:
    return RunLauncher(project_root=PROJECT_ROOT)


def main() -> None:
    st.title("LLM Reliability Analytics Dashboard")
    st.caption("Structured evaluation of LLM systems across test cases, oracles, and aggregated reliability metrics.")

    launcher = get_run_launcher()
    db_signature = _db_signature(DataProvider(project_root=PROJECT_ROOT).db_path)
    runs_df, _cases_df, results_df, source, note, db_path = load_dashboard_data(db_signature)
    adapter = MetricsAdapter()

    st.sidebar.header("Workspace")
    page = st.sidebar.radio(
        "Page",
        ["Analytics Dashboard", "Run New Evaluation", "Model Comparison"],
        index=0,
    )
    if st.sidebar.button("Refresh data"):
        load_dashboard_data.clear()
        st.rerun()

    with st.sidebar.expander("Data source details"):
        st.write(f"Source: **{source}**")
        st.write(f"DuckDB path: `{db_path}`")
        if note:
            st.write(note)

    if page == "Run New Evaluation":
        _render_run_new_page(launcher=launcher, runs_df=runs_df)
        return

    if page == "Model Comparison":
        _render_model_comparison_page(adapter=adapter, runs_df=runs_df, results_df=results_df)
        return

    st.sidebar.header("Run Selection")
    filtered_runs_df = runs_df.copy()
    if not runs_df.empty and "evaluation_mode" in runs_df.columns:
        available_modes = sorted(runs_df["evaluation_mode"].dropna().astype(str).unique().tolist())
        selected_modes = st.sidebar.multiselect(
            "Evaluation modes",
            available_modes,
            default=available_modes,
        )
        if selected_modes:
            filtered_runs_df = runs_df[runs_df["evaluation_mode"].astype(str).isin(selected_modes)]

    run_options_df = adapter.run_selector_options(runs_df=filtered_runs_df, results_df=results_df)
    if run_options_df.empty:
        st.warning("No runs available yet. Open the 'Run New Evaluation' page and start a batch.")
        if note:
            st.info(note)
        st.stop()

    label_by_run_id = {
        str(row["run_id"]): str(row["run_label"])
        for _, row in run_options_df.iterrows()
    }
    ordered_run_ids = run_options_df["run_id"].astype(str).tolist()

    selected_run_id = st.sidebar.selectbox(
        "Choose run",
        ordered_run_ids,
        format_func=lambda run_id: label_by_run_id.get(str(run_id), str(run_id)),
    )

    run_meta = _run_meta_for_id(runs_df=filtered_runs_df if not filtered_runs_df.empty else runs_df, run_id=selected_run_id)
    report = adapter.build_report_for_run(results_df=results_df, run_id=selected_run_id, runs_df=runs_df)
    run_rows = results_df[results_df["run_id"].astype(str) == str(selected_run_id)].copy()
    if run_rows.empty:
        st.warning(
            "This run currently has no stored test results. "
            "It may still be running, or execution ended before result persistence."
        )

    previous_run_id = adapter.latest_previous_run_id(runs_df=runs_df, run_id=selected_run_id)
    previous_report = (
        adapter.build_report_for_run(results_df=results_df, run_id=previous_run_id, runs_df=runs_df)
        if previous_run_id is not None
        else None
    )
    improvement_status = adapter.improvement_status_vs_previous(current_report=report, previous_report=previous_report)
    insights = adapter.build_insights(report=report, improvement_status=improvement_status, run_rows=run_rows)

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
        category_source_rows = run_rows.copy()
        category_sources = sorted(category_source_rows["test_source"].dropna().astype(str).unique().tolist())
        selected_category_sources = st.multiselect(
            "Filter test_source",
            category_sources,
            default=category_sources,
            key="category_source_filter",
        )
        if selected_category_sources:
            category_source_rows = category_source_rows[
                category_source_rows["test_source"].astype(str).isin(selected_category_sources)
            ]

        category_df = adapter.category_table(report)
        plot_category_accuracy(category_df)
        render_category_table(category_df)
        render_category_insight(report)
        st.subheader("Low-Performing Category Breakdown")
        render_low_score_category_breakdown(category_source_rows)
        available_categories = sorted(category_source_rows["category"].dropna().astype(str).unique().tolist())
        if available_categories:
            selected_failure_category = st.selectbox(
                "Failure analysis category",
                available_categories,
                key="failure_category_select",
            )
            st.markdown("**Top Failure Causes**")
            render_top_failure_causes_per_category(category_source_rows, selected_failure_category)
            st.markdown("**Failed Cases (drill-down list)**")
            render_failed_cases_table(category_source_rows, selected_failure_category)
        st.divider()
        _render_result_inspector_panel(
            run_rows=category_source_rows,
            runs_df=runs_df,
            selected_run_id=selected_run_id,
            panel_key="category_analysis_inspector",
            title="Category Result Inspector",
        )

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

        eval_modes = sorted(filtered_df["evaluation_mode"].dropna().astype(str).unique().tolist())
        selected_eval_modes = st.multiselect("evaluation_mode", eval_modes, default=eval_modes)
        if selected_eval_modes:
            filtered_df = filtered_df[filtered_df["evaluation_mode"].astype(str).isin(selected_eval_modes)]

        categories = sorted(filtered_df["category"].dropna().astype(str).unique().tolist())
        selected_categories = st.multiselect("category", categories, default=categories)
        if selected_categories:
            filtered_df = filtered_df[filtered_df["category"].astype(str).isin(selected_categories)]

        sources = sorted(filtered_df["test_source"].dropna().astype(str).unique().tolist())
        selected_sources = st.multiselect("test_source", sources, default=sources)
        if selected_sources:
            filtered_df = filtered_df[filtered_df["test_source"].astype(str).isin(selected_sources)]

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
            "test_source",
            "evaluation_mode",
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
        st.divider()
        _render_result_inspector_panel(
            run_rows=filtered_df,
            runs_df=runs_df,
            selected_run_id=selected_run_id,
            panel_key="raw_results_inspector",
            title="Raw Results Inspector",
        )


def _run_meta_for_id(runs_df: pd.DataFrame, run_id: str) -> dict[str, object]:
    if runs_df.empty:
        return {
            "run_id": run_id,
            "run_label": run_id,
            "model_name": "unknown-model",
            "provider": "local",
            "dataset_version": "v1",
            "evaluation_mode": "regression",
            "created_at": None,
            "mode": "mock",
            "repeat_count": 1,
            "model_version": "n/a",
            "temperature": 0.0,
            "max_output_tokens": 128,
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
            "evaluation_mode": "regression",
            "created_at": None,
            "mode": "mock",
            "repeat_count": 1,
            "model_version": "n/a",
            "temperature": 0.0,
            "max_output_tokens": 128,
            "notes": "",
        }

    data = row.iloc[0].to_dict()
    data.setdefault("run_id", run_id)
    data.setdefault("run_label", run_id)
    data.setdefault("model_name", "unknown-model")
    data.setdefault("provider", "local")
    data.setdefault("dataset_version", "v1")
    data.setdefault("evaluation_mode", "regression")
    data.setdefault("created_at", None)
    data.setdefault("mode", "mock")
    data.setdefault("repeat_count", 1)
    data.setdefault("model_version", "n/a")
    data.setdefault("temperature", 0.0)
    data.setdefault("max_output_tokens", 128)
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
    c6.write(f"**Evaluation Mode:** {meta.get('evaluation_mode', '-')}")
    c7.write(f"**Created At:** {dt(meta.get('created_at'))}")
    c8.write(f"**Repeat Count:** {meta.get('repeat_count', '-')}")

    c9, c10, c11 = st.columns(3)
    c9.write(f"**Temperature:** {meta.get('temperature', '-')}")
    c10.write(f"**Max Output Tokens:** {meta.get('max_output_tokens', '-')}")
    c11.write(f"**Mode:** {meta.get('mode', '-')}")

    notes = str(meta.get("notes", "") or "").strip()
    if notes:
        st.write(f"**Notes:** {notes}")


def _render_mode_badge(run_mode: str) -> None:
    badge = mode_badge(run_mode)
    normalized = run_mode.strip().lower()
    if normalized == "mock":
        st.info(f"Run Mode: **{badge}**")
    elif normalized in {"real", "real_local"}:
        st.success(f"Run Mode: **{badge}**")
    else:
        st.warning(f"Run Mode: **{badge}**")


def _render_result_inspector_panel(
    run_rows: pd.DataFrame,
    runs_df: pd.DataFrame,
    selected_run_id: str,
    panel_key: str,
    title: str,
) -> None:
    st.subheader(title)
    st.caption("Drill down: input -> model output -> oracle reasoning -> final score.")

    if run_rows.empty:
        st.info("No rows available for inspection under current filters.")
        return

    categories = sorted(run_rows["category"].dropna().astype(str).unique().tolist())
    if not categories:
        st.info("No category data available for inspection.")
        return

    selected_category = st.selectbox(
        "Category",
        categories,
        key=f"{panel_key}_category",
    )
    failed_only = st.checkbox("Show only failed", value=True, key=f"{panel_key}_failed_only")
    low_score_only = st.checkbox("Show only low-score results", value=False, key=f"{panel_key}_low_score_only")
    threshold = st.slider(
        "Low-score threshold",
        min_value=0.0,
        max_value=1.0,
        value=0.3,
        step=0.05,
        key=f"{panel_key}_score_threshold",
        disabled=not low_score_only,
    )

    inspector_rows = fetch_results_by_category(
        results_df=run_rows,
        run_id=selected_run_id,
        category=selected_category,
        failed_only=failed_only,
        low_score_threshold=(threshold if low_score_only else None),
    )

    if inspector_rows.empty:
        st.info("No rows matched inspector filters. Relax filters to inspect more results.")
        return

    preview_columns = [
        "result_id",
        "test_case_id",
        "attempt_index",
        "is_correct",
        "score",
        "error_type",
        "latency_ms",
    ]
    preview_columns = [col for col in preview_columns if col in inspector_rows.columns]
    st.dataframe(inspector_rows[preview_columns], use_container_width=True, hide_index=True)

    ordered_result_ids = inspector_rows["result_id"].astype(str).tolist()
    selected_result_id = st.selectbox(
        "Result row",
        ordered_result_ids,
        key=f"{panel_key}_result",
        format_func=lambda rid: _result_option_label(inspector_rows, rid),
    )

    trace = fetch_result_trace(results_df=run_rows, runs_df=runs_df, result_id=selected_result_id)
    render_result_inspector(trace)
    if trace is not None and not bool(trace.get("oracle_evaluation", {}).get("is_correct", False)):
        c1, c2 = st.columns(2)
        if c1.button("Mark as regression candidate", key=f"{panel_key}_mark_regression"):
            path = mark_trace_candidate(trace, target_source="regression", project_root=PROJECT_ROOT)
            st.success(f"Saved candidate trace to {path}")
        if c2.button("Mark as adversarial candidate", key=f"{panel_key}_mark_adversarial"):
            path = mark_trace_candidate(trace, target_source="adversarial", project_root=PROJECT_ROOT)
            st.success(f"Saved candidate trace to {path}")


def _result_option_label(frame: pd.DataFrame, result_id: str) -> str:
    rows = frame[frame["result_id"].astype(str) == str(result_id)]
    if rows.empty:
        return str(result_id)
    row = rows.iloc[0]
    status = "FAIL" if not bool(row.get("is_correct", False)) else "PASS"
    return (
        f"{status} | case={row.get('test_case_id', '-')}"
        f" | score={float(row.get('score', 0.0) or 0.0):.3f}"
        f" | attempt={int(row.get('attempt_index', 1) or 1)}"
    )


def _render_run_new_page(launcher: RunLauncher, runs_df: pd.DataFrame) -> None:
    _render_run_launcher(launcher)

    st.divider()
    st.subheader("Recent Runs")
    if runs_df.empty:
        st.info("No runs available yet.")
        return

    preview_columns = [
        "run_label",
        "model_name",
        "provider",
        "evaluation_mode",
        "dataset_version",
        "created_at",
        "mode",
        "repeat_count",
    ]
    preview_columns = [column for column in preview_columns if column in runs_df.columns]
    preview = runs_df.copy()
    preview["created_at"] = pd.to_datetime(preview["created_at"], errors="coerce")
    preview = preview.sort_values(["created_at", "run_id"], ascending=[False, False]).head(12)
    st.dataframe(preview[preview_columns], use_container_width=True, hide_index=True)


def _render_model_comparison_page(
    adapter: MetricsAdapter,
    runs_df: pd.DataFrame,
    results_df: pd.DataFrame,
) -> None:
    st.subheader("Model Comparison")
    st.caption("Compare models using multi-run median aggregation (default: last 3 runs per model).")

    if runs_df.empty or results_df.empty:
        st.info("No run/result data available yet.")
        return

    model_options = sorted(runs_df["model_name"].dropna().astype(str).unique().tolist())
    if not model_options:
        st.info("No model names found in run metadata.")
        return

    runs_per_model = int(st.number_input("Runs per model (latest N)", min_value=1, max_value=10, value=3, step=1))
    selected_models = st.multiselect(
        "Models",
        model_options,
        default=model_options,
    )

    mode_options = sorted(runs_df["evaluation_mode"].dropna().astype(str).unique().tolist())
    selected_mode = st.selectbox("Evaluation mode filter", ["all"] + mode_options, index=0)

    dataset_options = sorted(runs_df["dataset_version"].dropna().astype(str).unique().tolist())
    selected_dataset = st.selectbox("Dataset version filter", ["all"] + dataset_options, index=0)

    model_reports = adapter.build_multi_run_model_reports(
        results_df=results_df,
        runs_df=runs_df,
        runs_per_model=runs_per_model,
        selected_models=selected_models,
        evaluation_mode=None if selected_mode == "all" else selected_mode,
        dataset_version=None if selected_dataset == "all" else selected_dataset,
    )

    if not model_reports:
        st.warning("No model reports available for selected filters.")
        return

    summary_df = adapter.multi_run_model_summary_table(model_reports)
    st.dataframe(summary_df, use_container_width=True, hide_index=True)

    with st.expander("Aggregation Method"):
        st.markdown(
            """
            For each model and each test case:
            - collect results from latest N runs of that model
            - compute median of binary correctness (`0/1`)
            - assign pass if median >= 0.5
            - aggregate score/latency using medians
            """
        )

    if len(model_reports) < 2:
        st.info("Need at least two models for category-delta comparison.")
        return

    model_names = [item.model_name for item in model_reports]
    col1, col2 = st.columns(2)
    with col1:
        baseline_model = st.selectbox("Baseline model", model_names, index=0, key="model_cmp_baseline")
    with col2:
        default_idx = 1 if len(model_names) > 1 else 0
        candidate_model = st.selectbox("Candidate model", model_names, index=default_idx, key="model_cmp_candidate")

    if baseline_model == candidate_model:
        st.warning("Select two different models.")
        return

    category_delta = adapter.multi_run_category_delta(
        model_reports=model_reports,
        baseline_model=baseline_model,
        candidate_model=candidate_model,
    )
    if category_delta.empty:
        st.info("No category delta available.")
        return

    st.subheader("Category-wise Delta (Median Aggregated)")
    plot_category_accuracy_delta(category_delta)
    st.dataframe(category_delta, use_container_width=True, hide_index=True)


def _render_run_launcher(launcher: RunLauncher) -> None:
    st.subheader("Run New Evaluation")
    st.caption("Choose provider, model, and run settings. Start a batch and refresh analytics automatically.")

    provider_label = st.selectbox("Provider", ["Mock", "Ollama (local)"], index=0)
    provider = "ollama" if provider_label.startswith("Ollama") else "mock"

    datasets = launcher.list_datasets()
    dataset_path = st.selectbox("Dataset file", datasets, index=0 if datasets else None)

    run_name = st.text_input("Run name", value="streamlit-run")
    run_label = st.text_input("Run label (optional)", value="")
    dataset_version = st.text_input("Dataset version (optional)", value="")
    evaluation_mode = st.selectbox(
        "Evaluation mode",
        ["regression", "exploratory", "adversarial", "trace_replay"],
        index=0,
    )

    model_name = "mock-baseline"
    mock_mode = "deterministic"
    temperature_default = 0.0

    if provider == "mock":
        profiles = {
            "mock-baseline": "deterministic",
            "mock-semi-random": "semi_random",
        }
        model_name = st.selectbox("Mock profile", list(profiles.keys()), index=0)
        mock_mode = profiles[model_name]
    else:
        recommended_models = launcher.recommended_ollama_models()
        installed_models: list[str] = []
        ollama_status = "unknown"
        try:
            installed_models = launcher.list_installed_ollama_models(timeout_seconds=3.0)
            ollama_status = "reachable"
        except Exception as exc:  # noqa: BLE001 - UI should continue in mock mode
            ollama_status = launcher.friendly_error_message(exc)

        model_options = list(dict.fromkeys(installed_models + recommended_models))
        default_model = installed_models[0] if installed_models else recommended_models[0]
        model_name = st.selectbox("Ollama model", model_options, index=model_options.index(default_model))
        temperature_default = 0.1

        if ollama_status == "reachable":
            st.success("Ollama reachable")
        else:
            st.warning(ollama_status)

        if installed_models:
            st.caption(f"Installed local models: {', '.join(installed_models)}")
        else:
            st.info("No local models detected. Example: `ollama pull llama3.2:1b`")

    c1, c2, c3, c4 = st.columns(4)
    temperature = c1.slider("Temperature", min_value=0.0, max_value=1.0, value=temperature_default, step=0.05)
    repeat_count = c2.number_input("Repeat count", min_value=1, max_value=10, value=1, step=1)
    max_output_tokens = c3.number_input("Max output tokens", min_value=16, max_value=512, value=128, step=16)
    timeout_seconds = c4.number_input("Timeout (sec)", min_value=5.0, max_value=180.0, value=30.0, step=5.0)

    limit_value = st.number_input("Optional test case limit (0 = no limit)", min_value=0, max_value=10000, value=0, step=1)
    notes = st.text_area("Run notes (optional)", value="")

    if st.button("Start Evaluation Run", type="primary", use_container_width=False):
        request = LaunchRequest(
            dataset_path=dataset_path,
            run_name=run_name.strip() or "streamlit-run",
            run_label=run_label.strip() or None,
            provider=provider,
            model_name=model_name,
            dataset_version=dataset_version.strip() or None,
            evaluation_mode=evaluation_mode,
            temperature=float(temperature),
            repeat_count=int(repeat_count),
            max_output_tokens=int(max_output_tokens),
            timeout_seconds=float(timeout_seconds),
            mock_mode=mock_mode,
            notes=notes.strip(),
            limit=int(limit_value) if int(limit_value) > 0 else None,
        )

        with st.spinner("Starting evaluation run..."):
            try:
                result = launcher.start_run(request)
            except Exception as exc:  # noqa: BLE001 - friendly UI error handling
                st.error(launcher.friendly_error_message(exc))
            else:
                st.success(
                    f"Run completed: {result.run_id} "
                    f"(attempts={result.executed_test_cases}, accuracy={pct(result.report.accuracy)})"
                )
                load_dashboard_data.clear()
                st.rerun()


def _db_signature(db_path: Path) -> str:
    if not db_path.exists():
        return f"{db_path}:missing"
    stat = db_path.stat()
    return f"{db_path}:{stat.st_mtime_ns}:{stat.st_size}"


if __name__ == "__main__":
    main()
