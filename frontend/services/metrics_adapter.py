"""HTTP metrics adapter with local display-table formatting."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

import pandas as pd

from frontend.services.api_client import APIClient, BackendAPIError
from llm_reliability_analytics.analytics.reliability import ReliabilityReport, RunComparisonReport


@dataclass
class RunComparisonBundle:
    baseline_report: ReliabilityReport
    candidate_report: ReliabilityReport
    comparison_report: RunComparisonReport
    category_delta: pd.DataFrame


@dataclass
class RunInsights:
    weakest_category: str
    strongest_category: str
    most_frequent_error_type: str
    improvement_status: str
    failure_heavy_source: str
    promotion_hint: str


@dataclass
class ModelAggregateReport:
    model_name: str
    run_ids: list[str]
    report: ReliabilityReport


class IncompatibleRunsError(ValueError):
    """Raised before aggregating or ranking unlike execution configurations."""


class MetricsAdapter:
    def __init__(self, api: APIClient | None = None) -> None:
        self.api = api or APIClient()

    def _request_compatible(self, method: str, path: str, **kwargs: Any) -> Any:
        try:
            return self.api.request(method, path, **kwargs)
        except BackendAPIError as exc:
            if exc.status_code == 409:
                raise IncompatibleRunsError(str(exc)) from exc
            raise

    def comparison_issues(self, runs_df: pd.DataFrame, results_df: pd.DataFrame,
                          run_ids: list[str]) -> list[str]:
        payload = self.api.request("POST", "/internal/metrics/eligibility", json={"run_ids": run_ids})
        return list(payload.get("issues", []))

    def run_selector_options(self, runs_df: pd.DataFrame, results_df: pd.DataFrame) -> pd.DataFrame:
        if runs_df.empty:
            run_ids = sorted(results_df["run_id"].dropna().astype(str).unique().tolist()) if not results_df.empty else []
            if not run_ids:
                return pd.DataFrame(columns=["run_id", "run_label", "created_at"])
            return pd.DataFrame(
                {
                    "run_id": run_ids,
                    "run_label": run_ids,
                    "created_at": pd.NaT,
                }
            )

        options = runs_df[["run_id", "run_label", "created_at"]].drop_duplicates("run_id").copy()
        options["created_at"] = pd.to_datetime(options["created_at"], errors="coerce")
        options = options.sort_values(["created_at", "run_id"], ascending=[False, False])
        return options

    def build_report_for_run(
        self,
        results_df: pd.DataFrame,
        run_id: str,
        runs_df: pd.DataFrame | None = None,
    ) -> ReliabilityReport:
        payload = self.api.request("GET", f"/internal/metrics/runs/{run_id}")
        return ReliabilityReport.model_validate(payload)

    def category_table(self, report: ReliabilityReport) -> pd.DataFrame:
        rows = [
            {
                "category": item.category,
                "total_cases": item.total_test_cases,
                "passed": item.passed,
                "failed": item.failed,
                "accuracy": item.accuracy,
                "average_latency_ms": item.average_latency_ms,
            }
            for item in report.category_reports
        ]
        return pd.DataFrame(rows)

    def error_distribution_table(self, report: ReliabilityReport) -> pd.DataFrame:
        rows = [
            {"error_type": error_type, "count": count}
            for error_type, count in sorted(
                report.error_distribution.items(),
                key=lambda item: (-item[1], item[0]),
            )
        ]
        return pd.DataFrame(rows)

    def oracle_pass_rate_table(self, report: ReliabilityReport, run_rows: pd.DataFrame) -> pd.DataFrame:
        usage = (
            run_rows.groupby("oracle_type", dropna=False)["result_id"]
            .count()
            .rename("usage_count")
            .reset_index()
        )
        rate_rows = pd.DataFrame(
            [
                {"oracle_type": oracle_type, "pass_rate": pass_rate}
                for oracle_type, pass_rate in report.oracle_type_pass_rate.items()
            ]
        )

        if rate_rows.empty:
            return usage.assign(pass_rate=0.0)

        merged = usage.merge(rate_rows, on="oracle_type", how="outer")
        merged["usage_count"] = merged["usage_count"].fillna(0).astype(int)
        merged["pass_rate"] = merged["pass_rate"].fillna(0.0)
        return merged.sort_values(["usage_count", "oracle_type"], ascending=[False, True])

    def pass_fail_distribution(self, report: ReliabilityReport) -> pd.DataFrame:
        return pd.DataFrame(
            [
                {"status": "passed", "count": report.passed},
                {"status": "failed", "count": report.failed},
            ]
        )

    def problematic_cases(self, run_rows: pd.DataFrame, top_n: int = 15) -> pd.DataFrame:
        if run_rows.empty:
            return pd.DataFrame(
                columns=[
                    "test_case_id",
                    "category",
                    "oracle_type",
                    "attempts",
                    "failures",
                    "failure_rate",
                    "avg_score",
                    "avg_latency_ms",
                    "top_error_type",
                ]
            )

        grouped = (
            run_rows.assign(failed=~run_rows["is_correct"].astype(bool))
            .groupby(["test_case_id", "category", "oracle_type"], dropna=False)
            .agg(
                attempts=("result_id", "count"),
                failures=("failed", "sum"),
                avg_score=("score", "mean"),
                avg_latency_ms=("latency_ms", "mean"),
            )
            .reset_index()
        )
        grouped["failure_rate"] = grouped["failures"] / grouped["attempts"]

        error_mode = (
            run_rows[run_rows["error_type"].astype(str).str.len() > 0]
            .groupby("test_case_id")["error_type"]
            .agg(lambda values: values.value_counts().index[0])
            .rename("top_error_type")
            .reset_index()
        )

        merged = grouped.merge(error_mode, on="test_case_id", how="left")
        merged["top_error_type"] = merged["top_error_type"].fillna("")
        ordered = merged.sort_values(
            ["failures", "failure_rate", "avg_score", "avg_latency_ms"],
            ascending=[False, False, True, False],
        )
        return ordered.head(top_n)

    def compare_runs(
        self,
        results_df: pd.DataFrame,
        runs_df: pd.DataFrame,
        baseline_run_id: str,
        candidate_run_id: str,
    ) -> RunComparisonBundle:
        payload = self._request_compatible(
            "POST",
            "/internal/metrics/compare",
            json={"run_ids": [baseline_run_id, candidate_run_id]},
        )
        baseline_report = ReliabilityReport.model_validate(payload["baseline_report"])
        candidate_report = ReliabilityReport.model_validate(payload["candidate_report"])
        return RunComparisonBundle(
            baseline_report=baseline_report,
            candidate_report=candidate_report,
            comparison_report=RunComparisonReport.model_validate(payload["comparison_report"]),
            category_delta=self._category_delta_table(baseline_report, candidate_report),
        )

    def build_multi_run_model_reports(
        self,
        results_df: pd.DataFrame,
        runs_df: pd.DataFrame,
        runs_per_model: int = 3,
        selected_models: list[str] | None = None,
        evaluation_mode: str | None = None,
        dataset_version: str | None = None,
    ) -> list[ModelAggregateReport]:
        if runs_df.empty:
            return []
        runs = runs_df.copy()
        if selected_models:
            runs = runs[runs["model_name"].astype(str).isin({str(model) for model in selected_models})]
        if evaluation_mode:
            runs = runs[runs["evaluation_mode"].astype(str) == str(evaluation_mode)]
        if dataset_version:
            runs = runs[runs["dataset_version"].astype(str) == str(dataset_version)]
        if runs.empty:
            return []

        runs = runs.copy()
        runs["created_at"] = pd.to_datetime(runs["created_at"], errors="coerce")
        runs["_model_name"] = runs["model_name"].fillna("unknown-model").astype(str)
        runs = runs.drop_duplicates("run_id").sort_values(
            ["created_at", "run_id"], ascending=[False, False], na_position="last"
        )
        selected = runs.groupby("_model_name", sort=False, group_keys=False).head(max(1, int(runs_per_model)))
        run_ids = selected["run_id"].astype(str).tolist()
        if not run_ids:
            return []
        payload = self._request_compatible("POST", "/internal/metrics/models", json={"run_ids": run_ids})
        return [
            ModelAggregateReport(
                model_name=str(item["model_name"]),
                run_ids=[str(run_id) for run_id in item["run_ids"]],
                report=ReliabilityReport.model_validate(item["report"]),
            )
            for item in payload.get("models", [])
        ]

    def multi_run_model_summary_table(self, model_reports: list[ModelAggregateReport]) -> pd.DataFrame:
        rows = [
            {
                "model_name": item.model_name,
                "runs_used": len(item.run_ids),
                "accuracy": item.report.accuracy,
                "reliability_score": item.report.overall_reliability_score,
                "avg_latency_ms": item.report.average_latency_ms,
                "p95_latency_ms": item.report.p95_latency_ms,
                "total_cases": item.report.total_test_cases,
                "passed": item.report.passed,
                "failed": item.report.failed,
            }
            for item in model_reports
        ]
        return pd.DataFrame(rows)

    def multi_run_category_delta(
        self,
        model_reports: list[ModelAggregateReport],
        baseline_model: str,
        candidate_model: str,
    ) -> pd.DataFrame:
        baseline = next((item.report for item in model_reports if item.model_name == baseline_model), None)
        candidate = next((item.report for item in model_reports if item.model_name == candidate_model), None)
        if baseline is None or candidate is None:
            return pd.DataFrame(columns=["category", "baseline_accuracy", "candidate_accuracy", "delta"])
        return self._category_delta_table(baseline=baseline, candidate=candidate)

    def latest_previous_run_id(self, runs_df: pd.DataFrame, run_id: str) -> str | None:
        if runs_df.empty or "run_id" not in runs_df.columns:
            return None

        ordered = runs_df.copy()
        ordered["created_at"] = pd.to_datetime(ordered["created_at"], errors="coerce")
        ordered = ordered.sort_values(["created_at", "run_id"], ascending=[False, False])

        run_ids = ordered["run_id"].astype(str).tolist()
        try:
            idx = run_ids.index(str(run_id))
        except ValueError:
            return run_ids[0] if run_ids else None

        if idx + 1 < len(run_ids):
            return run_ids[idx + 1]
        return None

    def build_insights(
        self,
        report: ReliabilityReport,
        improvement_status: str,
        run_rows: pd.DataFrame | None = None,
    ) -> RunInsights:
        payload = self.api.request("GET", f"/internal/metrics/runs/{report.run_id}/insights")
        return RunInsights(
            weakest_category=str(payload.get("weakest_category", "n/a")),
            strongest_category=str(payload.get("strongest_category", "n/a")),
            most_frequent_error_type=str(payload.get("most_frequent_error_type", "none")),
            improvement_status=improvement_status,
            failure_heavy_source=str(payload.get("failure_heavy_source", "none")),
            promotion_hint=str(payload.get("promotion_hint", "")),
        )

    def improvement_status_vs_previous(
        self,
        current_report: ReliabilityReport,
        previous_report: ReliabilityReport | None,
    ) -> str:
        if previous_report is None:
            return "no_previous_run"
        payload = self.api.request(
            "POST",
            "/internal/metrics/improvement",
            json={"run_id": current_report.run_id, "previous_run_id": previous_report.run_id},
        )
        return str(payload.get("status", "research_only"))

    def _category_delta_table(
        self,
        baseline: ReliabilityReport,
        candidate: ReliabilityReport,
    ) -> pd.DataFrame:
        baseline_df = pd.DataFrame(
            [
                {"category": item.category, "baseline_accuracy": item.accuracy}
                for item in baseline.category_reports
            ]
        )
        candidate_df = pd.DataFrame(
            [
                {"category": item.category, "candidate_accuracy": item.accuracy}
                for item in candidate.category_reports
            ]
        )

        if baseline_df.empty and candidate_df.empty:
            return pd.DataFrame(columns=["category", "baseline_accuracy", "candidate_accuracy", "delta"])

        merged = baseline_df.merge(candidate_df, on="category", how="outer")
        merged["baseline_accuracy"] = merged["baseline_accuracy"].fillna(0.0)
        merged["candidate_accuracy"] = merged["candidate_accuracy"].fillna(0.0)
        merged["delta"] = merged["candidate_accuracy"] - merged["baseline_accuracy"]
        return merged.sort_values("delta", ascending=False)
