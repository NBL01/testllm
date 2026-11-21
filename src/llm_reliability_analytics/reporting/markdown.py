from __future__ import annotations

from collections.abc import Mapping
from datetime import datetime, timezone
from html import escape
import re
from typing import Any, TYPE_CHECKING

from pydantic import BaseModel

from llm_reliability_analytics.analytics.reliability import ReliabilityReport
if TYPE_CHECKING:
    from llm_reliability_analytics.workflow.service import RunReportResult


def render_markdown_report(run_report: RunReportResult) -> str:
    """Render the run report shared by the client export and the batch CLI."""
    report = run_report.report
    summary = run_report.storage_summary
    lines = [
        "# LLM Reliability Report", "",
        f"- Run ID: `{run_report.run_id}`",
        f"- Dataset Version: `{summary.dataset_version}`",
        f"- Provider: {_markdown_text(summary.provider or 'unknown')}",
        f"- Model: {_markdown_text(summary.model_name or 'unknown')}",
        f"- Execution Mode: {_markdown_text(summary.mode)}",
        f"- Evaluation Mode: {_markdown_text(summary.evaluation_mode)}",
        f"- Repeat Count: {summary.repeat_count}",
        f"- Generated At (UTC): `{_utc_now_iso()}`",
        "", "## Summary", "", _build_executive_summary(report),
        "", "## Metrics", "", *_build_core_metrics_table(report),
        "", "## Measurement Notes", "", *(f"- {note}" for note in report.measurement_notes),
        "", "## Pass Rate by Category", "", *_build_category_breakdown(report),
        "", "## Failure Types", "", *_build_error_breakdown(report),
        "", "## Latency", "", *_build_latency_summary(report),
        "", "## Findings", "", *_build_findings(report),
    ]
    return "\n".join(lines).strip() + "\n"


def append_job_context(markdown: str, job: BaseModel | Mapping[str, Any]) -> str:
    """Append job metadata without importing the job workflow or mutating input."""
    values = job.model_dump() if isinstance(job, BaseModel) else job
    fields = (
        ("job_id", "Job ID"), ("status", "Status"), ("linked_run_id", "Linked Run ID"),
        ("provider", "Provider"), ("model_name", "Model"), ("input_path", "Dataset Path"),
        ("dataset_version", "Dataset Version"), ("evaluation_mode", "Evaluation Mode"),
        ("dataset_sha256", "Frozen Dataset SHA-256"), ("source_job_id", "Source Job ID"),
        ("oracle_profile", "Oracle Profile"), ("temperature", "Temperature"),
        ("max_output_tokens", "Max Output Tokens"), ("repeat_count", "Configured Repeat Count"),
        ("timeout_seconds", "Timeout Seconds"), ("limit", "Case Limit"),
        ("submitted_by", "Submitted By"), ("team_name", "Team"), ("client_name", "Client"),
        ("project_name", "Project"), ("notes", "Notes"),
    )
    lines = [markdown.rstrip(), "", "## Job Context", ""]
    for key, label in fields:
        value = values.get(key)
        lines.append(f"- {label}: {_markdown_text(value) if value is not None and value != '' else 'not recorded'}")
    lines.append("- Oracle Profile Semantics: scoring is dataset-defined by each case's oracle type and input_config; "
                 "the job profile is a label, not a scoring override.")
    return "\n".join(lines) + "\n"


def _markdown_text(value: Any) -> str:
    text = escape(str(value), quote=True)
    text = re.sub(r"([\\`*_{}\[\]()#|~])", r"\\\1", text)
    return text.replace("\r\n", "\n").replace("\r", "\n").replace("\n", "<br>")


def _build_executive_summary(report: ReliabilityReport) -> str:
    return (
        f"This run evaluated **{report.total_test_cases}** attempts across "
        f"**{report.unique_test_cases}** unique test cases and reached a **{_pct(report.accuracy)}** pass rate. "
        + (f"**{_pct(report.pass_hat_k)}** of cases passed all {report.repeat_k} attempts (pass^{report.repeat_k}) and "
           f"**{_pct(report.pass_at_k)}** passed at least once (pass@{report.repeat_k})."
           if report.pass_hat_k is not None and report.pass_at_k is not None
           else "Consistency across repeats was not measured (cases need the same 2+ attempts).")
    )


def _build_core_metrics_table(report: ReliabilityReport) -> list[str]:
    return [
        "| Metric | Value |",
        "| --- | ---: |",
        f"| Attempts | {report.total_test_cases} |",
        f"| Unique test cases | {report.unique_test_cases} |",
        f"| Passed / failed attempts | {report.passed} / {report.failed} |",
        f"| Pass rate | {_pct(report.accuracy)} |",
        f"| pass^k: cases passing all attempts | {_optional_pct(report.pass_hat_k, report.repeat_k)} |",
        f"| pass@k: cases passing at least once | {_optional_pct(report.pass_at_k, report.repeat_k)} |",
        f"| Schema-only pass rate | {'not measured (no json_schema attempts)' if report.schema_pass_rate is None else _pct(report.schema_pass_rate)} |",
        f"| Latency p50 / p95 | {report.p50_latency_ms:.2f} / {report.p95_latency_ms:.2f} ms |",
    ]


def _optional_pct(value: float | None, k: int | None) -> str:
    return "not measured (needs the same 2+ attempts per case)" if value is None else f"{_pct(value)} (k={k})"


def _build_category_breakdown(report: ReliabilityReport) -> list[str]:
    if not report.category_reports:
        return ["No category-level data available."]
    lines = ["| Category | Attempts | Passed | Failed | Pass rate | Avg latency (ms) |", "| --- | ---: | ---: | ---: | ---: | ---: |"]
    for item in sorted(report.category_reports, key=lambda item: (item.accuracy, -item.failed, item.category)):
        lines.append(f"| {_markdown_text(item.category)} | {item.total_test_cases} | {item.passed} | "
                     f"{item.failed} | {_pct(item.accuracy)} | {item.average_latency_ms:.2f} |")
    return lines


def _build_error_breakdown(report: ReliabilityReport) -> list[str]:
    if not report.error_distribution:
        return ["No failure types were recorded in this run."]
    lines = ["| Failure type | Attempts | Share of attempts |", "| --- | ---: | ---: |"]
    for error_type, count in sorted(report.error_distribution.items(), key=lambda item: (-item[1], item[0])):
        lines.append(f"| {_markdown_text(error_type)} | {count} | {_pct(count / report.total_test_cases if report.total_test_cases else 0.0)} |")
    return lines


def _build_latency_summary(report: ReliabilityReport) -> list[str]:
    return [
        f"- Mean / p50 / p95: **{report.average_latency_ms:.2f} / {report.p50_latency_ms:.2f} / {report.p95_latency_ms:.2f} ms**",
        "- Sources (attempt counts): " + (
            ", ".join(f"{source}: {count}" for source, count in sorted(report.latency_sources.items())) or "not measured"),
    ]


def _build_findings(report: ReliabilityReport) -> list[str]:
    if not report.total_test_cases:
        return ["- No attempts were recorded."]
    weakest = min(report.category_reports, key=lambda item: (item.accuracy, -item.failed), default=None)
    top_error = max(report.error_distribution.items(), key=lambda item: item[1], default=None)
    return [
        f"- Weakest category: **{_markdown_text(weakest.category)}** ({_pct(weakest.accuracy)} pass rate)." if weakest else "- No categories recorded.",
        f"- Most frequent failure type: **{_markdown_text(top_error[0])}** ({top_error[1]} attempts)." if top_error else "- No failures recorded.",
    ]


def _pct(value: float) -> str:
    return f"{value * 100:.2f}%"


def _utc_now_iso() -> str:
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat()
