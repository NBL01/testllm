"""Adapter from raw tabular results to reusable analytics objects."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

import pandas as pd

from llm_reliability_analytics.analytics.reliability import (
    ReliabilityReport,
    RunComparisonReport,
    compute_reliability_report,
    compute_run_comparison_report,
)
from llm_reliability_analytics.models.domain import ErrorTaxonomy, TestResult


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


class MetricsAdapter:
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
        run_rows = results_df[results_df["run_id"].astype(str) == str(run_id)].copy()
        if run_rows.empty:
            return compute_reliability_report([], run_id=run_id)

        dataset_version = "v1"
        repetition_index = 1

        if runs_df is not None and not runs_df.empty and "run_id" in runs_df.columns:
            run_meta = runs_df[runs_df["run_id"].astype(str) == str(run_id)]
            if not run_meta.empty:
                if "dataset_version" in run_meta.columns and pd.notna(run_meta.iloc[0]["dataset_version"]):
                    dataset_version = str(run_meta.iloc[0]["dataset_version"])
                if "repetition_index" in run_meta.columns and pd.notna(run_meta.iloc[0]["repetition_index"]):
                    repetition_index = int(run_meta.iloc[0]["repetition_index"])

        domain_results = [self._row_to_test_result(row) for row in run_rows.to_dict(orient="records")]

        return compute_reliability_report(
            domain_results,
            run_id=run_id,
            dataset_version=dataset_version,
            repetition_index=repetition_index,
        )

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
        baseline_report = self.build_report_for_run(results_df, baseline_run_id, runs_df)
        candidate_report = self.build_report_for_run(results_df, candidate_run_id, runs_df)

        comparison_report = compute_run_comparison_report(
            [baseline_report, candidate_report],
            baseline_run_id=baseline_run_id,
        )

        category_delta = self._category_delta_table(baseline_report, candidate_report)

        return RunComparisonBundle(
            baseline_report=baseline_report,
            candidate_report=candidate_report,
            comparison_report=comparison_report,
            category_delta=category_delta,
        )

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
    ) -> RunInsights:
        weakest = report.weakest_categories[0].category if report.weakest_categories else "n/a"

        strongest = "n/a"
        if report.category_reports:
            strongest_item = max(report.category_reports, key=lambda item: (item.accuracy, item.total_test_cases))
            strongest = strongest_item.category

        top_error = report.most_frequent_error_types[0].error_type if report.most_frequent_error_types else "none"

        return RunInsights(
            weakest_category=weakest,
            strongest_category=strongest,
            most_frequent_error_type=top_error,
            improvement_status=improvement_status,
        )

    def improvement_status_vs_previous(
        self,
        current_report: ReliabilityReport,
        previous_report: ReliabilityReport | None,
    ) -> str:
        if previous_report is None:
            return "no_previous_run"

        delta = current_report.overall_reliability_score - previous_report.overall_reliability_score
        if abs(delta) < 1e-9:
            return "unchanged"
        return "improved" if delta > 0 else "worsened"

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

    def _row_to_test_result(self, row: dict[str, Any]) -> TestResult:
        taxonomy = self._parse_taxonomy(row.get("error_taxonomy"))
        return TestResult(
            run_id=str(row.get("run_id")),
            test_case_id=str(row.get("test_case_id")),
            attempt_index=int(row.get("attempt_index", 1) or 1),
            category=self._as_optional_str(row.get("category")),
            oracle_type=self._as_optional_str(row.get("oracle_type")),
            actual_answer=self._as_optional_str(row.get("actual_answer")),
            expected_answer_normalized=self._as_optional_str(row.get("expected_answer")),
            actual_answer_normalized=self._as_optional_str(row.get("normalized_answer")),
            normalized_answer=self._as_optional_str(row.get("normalized_answer")),
            is_correct=bool(row.get("is_correct", False)),
            score=float(row.get("score", 0.0) or 0.0),
            latency_ms=float(row.get("latency_ms", 0.0) or 0.0),
            latency_source=self._as_optional_str(row.get("latency_source")) or "measured",
            error_type=self._as_optional_str(row.get("error_type")),
            error_taxonomy=taxonomy,
            critical_error_flag=bool(row.get("critical_error_flag", False)),
        )

    def _parse_taxonomy(self, raw_value: Any) -> ErrorTaxonomy:
        if raw_value is None:
            return ErrorTaxonomy.NONE
        try:
            return ErrorTaxonomy(str(raw_value))
        except ValueError:
            return ErrorTaxonomy.UNKNOWN

    def _as_optional_str(self, value: Any) -> str | None:
        if value is None:
            return None
        text = str(value)
        return text if text else None
