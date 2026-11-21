from llm_reliability_analytics.reporting.markdown import render_markdown_report
from llm_reliability_analytics.workflow.service import run_report_workflow
from llm_reliability_analytics.workflow.service import run_batch_workflow


def test_markdown_report_includes_required_sections(monkeypatch, tmp_path) -> None:
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

    markdown_report = render_markdown_report(run_report_workflow(run_result.run_id))

    for heading in ("# LLM Reliability Report", "## Summary", "## Metrics", "## Measurement Notes",
                    "## Pass Rate by Category", "## Failure Types", "## Latency", "## Findings"):
        assert heading in markdown_report, heading
    assert "| pass^k: cases passing all attempts | " in markdown_report and "(k=2)" in markdown_report
    assert "| Pass rate |" in markdown_report
    for legacy in ("Legacy", "Overall Reliability Score", "Consistency Summary", "heuristic"):
        assert legacy not in markdown_report, legacy
