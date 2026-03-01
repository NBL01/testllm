from llm_reliability_analytics.reporting.markdown import generate_run_markdown_report
from llm_reliability_analytics.workflow.service import run_batch_workflow


def test_generate_run_markdown_report_includes_required_sections(monkeypatch, tmp_path) -> None:
    db_path = tmp_path / "reporting_flow.duckdb"
    monkeypatch.setenv("LLM_RELIABILITY_DB_PATH", str(db_path))

    run_result = run_batch_workflow(
        input_path="sample_test_cases.jsonl",
        run_name="reporting-test-run",
        model_name="mock-llm",
        dataset_version="v1",
        mode="deterministic",
        seed=42,
        limit=6,
        repeats_per_case=2,
    )

    markdown_report = generate_run_markdown_report(run_result.run_id)

    assert "# LLM Reliability Report" in markdown_report
    assert "## Executive Summary" in markdown_report
    assert "## Core Metrics" in markdown_report
    assert "## Category Breakdown" in markdown_report
    assert "## Error Type Breakdown" in markdown_report
    assert "## Latency Summary" in markdown_report
    assert "## Consistency Summary" in markdown_report
    assert "## Overall Reliability Score" in markdown_report
    assert "## Conclusions" in markdown_report
    assert "Total Test Cases" in markdown_report
    assert "Passed" in markdown_report
    assert "Failed" in markdown_report
    assert "Accuracy" in markdown_report
    assert "Overall Reliability Score" in markdown_report
