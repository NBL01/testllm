import csv
import importlib
from io import StringIO

import pytest

from llm_reliability_analytics.analytics.reliability import compute_reliability_report
from llm_reliability_analytics.models.domain import TestResult as Result
from llm_reliability_analytics.reporting import markdown
from llm_reliability_analytics.storage.db import get_connection, initialize_schema
from llm_reliability_analytics.storage.duckdb_store import RunAggregatedSummary, fetch_results_for_run
from llm_reliability_analytics.workflow.service import RunReportResult


def test_csv_exports_every_failed_attempt_over_5000_with_snapshot_evidence(monkeypatch, tmp_path):
    monkeypatch.setenv("LLM_RELIABILITY_DB_PATH", str(tmp_path / "export.duckdb"))
    initialize_schema()
    conn = get_connection()
    conn.execute("""
        INSERT INTO test_results (run_id, test_case_id, attempt_index, expected_answer,
                                  actual_answer, is_correct, score, latency_ms)
        SELECT 'run', 'case-' || i::VARCHAR, 1, 'truth', '=1+1', FALSE, 0, 1
        FROM range(5007) t(i)
    """)
    conn.execute("""
        INSERT INTO test_results (run_id, test_case_id, attempt_index, is_correct, score, latency_ms)
        VALUES ('run', 'passing', 1, TRUE, 1, 1), ('other-run', 'other', 1, FALSE, 0, 1)
    """)
    conn.close()
    exporter = importlib.import_module("llm_reliability_analytics.reporting.csv_export")
    exported = exporter.export_failed_cases_csv("run")
    rows = list(csv.DictReader(StringIO(exported, newline="")))
    assert len(rows) == 5007
    assert len({row["test_case_id"] for row in rows}) == 5007
    assert all(row["expected_answer"] == "truth" for row in rows)
    assert all(row["actual_answer"] == "'=1+1" for row in rows)
    report = compute_reliability_report(fetch_results_for_run("run"))
    assert len(rows) == report.failed
    assert report.total_test_cases == 5008
    assert report.unique_test_cases == 5008
    assert exported == exporter.export_failed_cases_csv("run")
    assert list(csv.DictReader(StringIO(exporter.export_failed_cases_csv("empty")))) == []


@pytest.mark.parametrize("value,expected", [
    ('comma,quote"CR\rLF\nUnicode \u043f\u0440\u0438\u0432\u0435\u0442', 'comma,quote"CR\rLF\nUnicode \u043f\u0440\u0438\u0432\u0435\u0442'),
    ("=1+1", "'=1+1"), ("+SUM(A1)", "'+SUM(A1)"), ("-2", "'-2"), ("@SUM(A1)", "'@SUM(A1)"),
    ("\ttext", "'\ttext"), ("\rtext", "'\rtext"), ("\ntext", "'\ntext"),
    ("  =1", "'  =1"), ("\ufeff=1", "'\ufeff=1"), ("\x00=1", "'\x00=1"),
    ("\uff1d1+1", "'\uff1d1+1"), (" " * 10000 + "=1", "'" + " " * 10000 + "=1"),
    (None, ""), ("", ""), (0, "0"), ("plain", "plain"),
])
def test_csv_rfc_round_trip_and_formula_neutralization(value, expected):
    exporter = importlib.import_module("llm_reliability_analytics.reporting.csv_export")
    output = exporter.render_failed_cases_csv([{"actual_answer": value}])
    rows = list(csv.DictReader(StringIO(output, newline="")))
    assert rows[0]["actual_answer"] == expected
    assert output.endswith("\r\n")


def run_report():
    report = compute_reliability_report([Result(
        run_id="run", test_case_id="case", actual_answer="bad", is_correct=False,
        score=0, latency_ms=0, latency_source="mock_simulated")])
    summary = RunAggregatedSummary(run_id="run", model_name="mock-baseline", provider="mock",
                                   total_test_cases=1, passed=0, failed=1, accuracy=0, average_latency_ms=0)
    return RunReportResult(run_id="run", report=report, storage_summary=summary)


def test_markdown_discloses_metric_scope_provenance_and_target():
    output = markdown.render_markdown_report(run_report())
    for text in ["legacy-v1", "mock-baseline", "Provider", "mock_simulated", "not measured",
                 "Total Attempts", "Repeated Cases", "Schema Cases", "Schema Attempts", "0.40", "lenient"]:
        assert text in output
    assert "failures / 1000 attempts" in output


def test_job_context_helper_accepts_mapping_and_escapes_untrusted_markdown():
    job = dict(job_id="job", provider="mock", model_name="mock-baseline", oracle_profile="default",
               submitted_by="Alice", team_name="Team", client_name="Client", project_name="Project",
               notes="note\n## forged\n<script>alert(1)</script>", evaluation_mode="regression",
               input_path="sample_test_cases.jsonl", repeat_count=2, status="completed")
    output = markdown.append_job_context("# Original\n", job)
    for value in ["# Original", "## Job Context", "Alice", "Team", "Client", "Project", "default", "mock-baseline"]:
        assert value in output
    assert "\n## forged" not in output
    assert "<script>" not in output
    assert "dataset-defined" in output
    from llm_reliability_analytics.storage.evaluation_job_repository import EvaluationJobCreate
    model_output = markdown.append_job_context("# Original\n", EvaluationJobCreate())
    assert "mock-baseline" in model_output
