import duckdb

from llm_reliability_analytics.models.domain import TestCase as DomainTestCase
from llm_reliability_analytics.models.domain import TestResult as DomainTestResult
from llm_reliability_analytics.storage.db import get_connection
from llm_reliability_analytics.storage.duckdb_store import (
    create_test_run,
    fetch_aggregated_summaries,
    initialize_storage_schema,
    insert_batch_results,
    insert_test_cases,
)


def test_initialize_storage_schema_creates_required_tables(monkeypatch, tmp_path) -> None:
    db_path = tmp_path / "storage_test.duckdb"
    monkeypatch.setenv("LLM_RELIABILITY_DB_PATH", str(db_path))

    initialize_storage_schema()
    conn = get_connection()
    rows = conn.execute(
        """
        SELECT table_name
        FROM information_schema.tables
        WHERE table_schema = 'main'
          AND table_name IN ('test_cases', 'test_runs', 'test_results')
        ORDER BY table_name;
        """
    ).fetchall()
    conn.close()

    assert [row[0] for row in rows] == ["test_cases", "test_results", "test_runs"]


def test_insert_test_cases_create_run_insert_results_and_fetch_summary(monkeypatch, tmp_path) -> None:
    db_path = tmp_path / "workflow_test.duckdb"
    monkeypatch.setenv("LLM_RELIABILITY_DB_PATH", str(db_path))

    initialize_storage_schema()
    test_cases = [
        DomainTestCase(
            id="case-1",
            category="math",
            difficulty="easy",
            prompt="What is 2 + 2?",
            expected_answer="4",
            oracle_type="exact_match",
            metadata={"source": "unit-test"},
        ),
        DomainTestCase(
            id="case-2",
            category="factual",
            difficulty="medium",
            prompt="Capital of France?",
            expected_answer="Paris",
            oracle_type="exact_match",
            metadata={"source": "unit-test"},
        ),
    ]
    inserted_cases = insert_test_cases(test_cases)
    assert inserted_cases == 2

    run = create_test_run(name="demo-run", model_name="mock-llm-v1")
    assert run.name == "demo-run"
    assert run.model_name == "mock-llm-v1"

    results = [
        DomainTestResult(
            run_id=run.id,
            test_case_id="case-1",
            category="math",
            actual_answer="4",
            is_correct=True,
            score=1.0,
            latency_ms=100.0,
            error_type=None,
        ),
        DomainTestResult(
            run_id=run.id,
            test_case_id="case-2",
            category="factual",
            actual_answer="Lyon",
            is_correct=False,
            score=0.0,
            latency_ms=300.0,
            error_type="wrong_answer",
        ),
    ]
    inserted_results = insert_batch_results(results)
    assert inserted_results == 2

    summaries = fetch_aggregated_summaries(run.id)
    assert len(summaries) == 1
    summary = summaries[0]

    assert summary.run_id == run.id
    assert summary.total_test_cases == 2
    assert summary.passed == 1
    assert summary.failed == 1
    assert summary.accuracy == 0.5
    assert summary.average_latency_ms == 200.0
    assert summary.error_distribution == {"wrong_answer": 1}


def test_initialize_storage_schema_migrates_legacy_test_cases_table(monkeypatch, tmp_path) -> None:
    db_path = tmp_path / "legacy_schema.duckdb"
    monkeypatch.setenv("LLM_RELIABILITY_DB_PATH", str(db_path))

    conn = duckdb.connect(str(db_path))
    conn.execute(
        """
        CREATE TABLE test_cases (
            batch_id TEXT,
            case_id TEXT,
            prompt TEXT
        );
        """
    )
    conn.close()

    initialize_storage_schema()

    conn = get_connection()
    columns = conn.execute(
        """
        SELECT column_name
        FROM information_schema.columns
        WHERE table_schema = 'main'
          AND table_name = 'test_cases'
        ORDER BY ordinal_position;
        """
    ).fetchall()
    backups = conn.execute(
        """
        SELECT table_name
        FROM information_schema.tables
        WHERE table_schema = 'main'
          AND table_name LIKE 'test_cases__backup_%';
        """
    ).fetchall()
    conn.close()

    assert [column[0] for column in columns] == [
        "test_case_id",
        "category",
        "difficulty",
        "prompt",
        "expected_answer",
        "oracle_type",
        "metadata",
    ]
    assert len(backups) == 1
