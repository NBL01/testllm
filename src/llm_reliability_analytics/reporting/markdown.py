from datetime import datetime, timezone

from llm_reliability_analytics.analytics.reliability import ReliabilityReport
from llm_reliability_analytics.workflow.service import RunReportResult, run_report_workflow


def generate_run_markdown_report(run_id: str) -> str:
    """Load a run from storage and render a Markdown summary report."""
    run_report = run_report_workflow(run_id)
    return render_markdown_report(run_report)


def render_markdown_report(run_report: RunReportResult) -> str:
    """Render a clean Markdown report suitable for demo/defense presentation."""
    report = run_report.report
    summary = run_report.storage_summary

    lines: list[str] = []
    lines.append("# LLM Reliability Report")
    lines.append("")
    lines.append(f"- Run ID: `{run_report.run_id}`")
    lines.append(f"- Dataset Version: `{summary.dataset_version}`")
    lines.append(f"- Repetition Index: `{summary.repetition_index}`")
    lines.append(f"- Generated At (UTC): `{_utc_now_iso()}`")
    lines.append("")
    lines.append("## Executive Summary")
    lines.append("")
    lines.append(_build_executive_summary(report))
    lines.append("")
    lines.append("## Core Metrics")
    lines.append("")
    lines.extend(_build_core_metrics_table(report))
    lines.append("")
    lines.append("## Category Breakdown")
    lines.append("")
    lines.extend(_build_category_breakdown(report))
    lines.append("")
    lines.append("## Error Type Breakdown")
    lines.append("")
    lines.extend(_build_error_breakdown(report))
    lines.append("")
    lines.append("## Latency Summary")
    lines.append("")
    lines.extend(_build_latency_summary(report))
    lines.append("")
    lines.append("## Consistency Summary")
    lines.append("")
    lines.extend(_build_consistency_summary(report))
    lines.append("")
    lines.append("## Overall Reliability Score")
    lines.append("")
    lines.append(f"- Overall Reliability Score: **{report.overall_reliability_score:.3f}**")
    lines.append("")
    lines.append("## Conclusions")
    lines.append("")
    lines.extend(_build_conclusions(report))

    return "\n".join(lines).strip() + "\n"


def _build_executive_summary(report: ReliabilityReport) -> str:
    return (
        f"This run evaluated **{report.total_test_cases}** attempts across "
        f"**{report.unique_test_cases}** unique test cases, reached **{_pct(report.accuracy)}** accuracy, "
        f"and achieved an overall reliability score of **{report.overall_reliability_score:.3f}**."
    )


def _build_core_metrics_table(report: ReliabilityReport) -> list[str]:
    return [
        "| Metric | Value |",
        "| --- | ---: |",
        f"| Total Test Cases | {report.total_test_cases} |",
        f"| Unique Test Cases | {report.unique_test_cases} |",
        f"| Passed | {report.passed} |",
        f"| Failed | {report.failed} |",
        f"| Accuracy | {_pct(report.accuracy)} |",
    ]


def _build_category_breakdown(report: ReliabilityReport) -> list[str]:
    if not report.category_reports:
        return ["No category-level data available."]

    lines = [
        "| Category | Total | Passed | Failed | Accuracy | Avg Latency (ms) |",
        "| --- | ---: | ---: | ---: | ---: | ---: |",
    ]
    ordered = sorted(
        report.category_reports,
        key=lambda item: (item.accuracy, -item.failed, item.category),
    )
    for item in ordered:
        lines.append(
            f"| {item.category} | {item.total_test_cases} | {item.passed} | "
            f"{item.failed} | {_pct(item.accuracy)} | {item.average_latency_ms:.2f} |"
        )
    return lines


def _build_error_breakdown(report: ReliabilityReport) -> list[str]:
    if not report.error_distribution:
        return ["No explicit error types were recorded in this run."]

    lines = [
        "| Error Type | Count | Rate |",
        "| --- | ---: | ---: |",
    ]
    ordered_errors = sorted(report.error_distribution.items(), key=lambda item: (-item[1], item[0]))
    for error_type, count in ordered_errors:
        rate = count / report.total_test_cases if report.total_test_cases else 0.0
        lines.append(f"| {error_type} | {count} | {_pct(rate)} |")
    return lines


def _build_latency_summary(report: ReliabilityReport) -> list[str]:
    return [
        f"- Average Latency: **{report.average_latency_ms:.2f} ms**",
        f"- P95 Latency: **{report.p95_latency_ms:.2f} ms**",
        f"- Failure Density: **{report.failure_density_per_1000:.2f} failures / 1000 cases**",
    ]


def _build_consistency_summary(report: ReliabilityReport) -> list[str]:
    return [
        f"- Consistency Score: **{report.consistency_score:.3f}**",
        f"- Repeatability Score: **{report.repeatability_score:.3f}**",
        f"- Unstable Cases: **{report.unstable_case_count}**",
        f"- Schema Compliance Rate: **{_pct(report.schema_compliance_rate)}**",
        f"- Critical Error Rate: **{_pct(report.critical_error_rate)}**",
    ]


def _build_conclusions(report: ReliabilityReport) -> list[str]:
    top_weak = report.weakest_categories[0].category if report.weakest_categories else "n/a"
    top_error = (
        report.most_frequent_error_types[0].error_type
        if report.most_frequent_error_types
        else "none"
    )

    reliability_band = _reliability_band(report.overall_reliability_score)
    return [
        f"- The current run is in the **{reliability_band}** reliability band.",
        f"- The weakest category is **{top_weak}** and should be prioritized for prompt/oracle refinement.",
        f"- The most frequent error type is **{top_error}**; reducing this error will likely improve overall reliability fastest.",
        "- Next iteration should target high-failure categories while preserving low latency and repeatable behavior.",
    ]


def _reliability_band(score: float) -> str:
    if score >= 0.85:
        return "high"
    if score >= 0.65:
        return "moderate"
    return "low"


def _pct(value: float) -> str:
    return f"{value * 100:.2f}%"


def _utc_now_iso() -> str:
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat()
