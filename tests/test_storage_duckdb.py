import duckdb

from llm_reliability_analytics.models.domain import TestCase as DomainTestCase
from llm_reliability_analytics.models.domain import TestResult as DomainTestResult
from llm_reliability_analytics.storage.db import get_connection
from llm_reliability_analytics.storage.duckdb_store import (
    create_test_run,
    fetch_aggregated_summaries,
    fetch_results_for_run,
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
          AND table_name IN ('test_cases', 'test_runs', 'test_results', 'evaluation_traces')
        ORDER BY table_name;
        """
    ).fetchall()
    conn.close()

    assert [row[0] for row in rows] == ["evaluation_traces", "test_cases", "test_results", "test_runs"]


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
    assert run.dataset_version == "v1"
    assert run.repetition_index == 1

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
    assert summary.dataset_version == "v1"
    assert summary.repetition_index == 1
    assert summary.total_test_cases == 2
    assert summary.passed == 1
    assert summary.failed == 1
    assert summary.accuracy == 0.5
    assert summary.average_latency_ms == 200.0
    assert summary.error_distribution == {"wrong_answer": 1}
    assert summary.error_taxonomy_distribution == {}


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
    backup_count = conn.execute(
        """
        SELECT COUNT(*)
        FROM information_schema.tables
        WHERE table_schema = 'main'
          AND table_name LIKE 'test_cases__backup_%';
        """
    ).fetchone()[0]
    conn.close()

    expected_columns = {
        "test_case_id",
        "test_source",
        "dataset_version",
        "category",
        "difficulty",
        "prompt",
        "expected_answer",
        "oracle_type",
        "metadata",
    }
    present_columns = {column[0] for column in columns}
    assert expected_columns.issubset(present_columns)
    assert {"batch_id", "case_id", "prompt"}.issubset(present_columns)
    assert backup_count == 0


def test_create_test_run_auto_increments_repetition_index(monkeypatch, tmp_path) -> None:
    db_path = tmp_path / "repetition_schema.duckdb"
    monkeypatch.setenv("LLM_RELIABILITY_DB_PATH", str(db_path))
    initialize_storage_schema()

    run_a = create_test_run(
        name="exp-run",
        model_name="mock-v2",
        dataset_version="v2",
        run_group_id="group-a",
    )
    run_b = create_test_run(
        name="exp-run",
        model_name="mock-v2",
        dataset_version="v2",
        run_group_id="group-a",
    )

    assert run_a.repetition_index == 1
    assert run_b.repetition_index == 2


def test_insert_batch_results_stores_each_attempt_separately(monkeypatch, tmp_path) -> None:
    db_path = tmp_path / "attempts_schema.duckdb"
    monkeypatch.setenv("LLM_RELIABILITY_DB_PATH", str(db_path))
    initialize_storage_schema()

    run = create_test_run(name="repeat-run", model_name="mock-v3")
    inserted_results = insert_batch_results(
        [
            DomainTestResult(
                run_id=run.id,
                test_case_id="case-repeat-1",
                attempt_index=1,
                category="math",
                actual_answer="4",
                is_correct=True,
                score=1.0,
                latency_ms=100.0,
                error_type=None,
            ),
            DomainTestResult(
                run_id=run.id,
                test_case_id="case-repeat-1",
                attempt_index=2,
                category="math",
                actual_answer="5",
                is_correct=False,
                score=0.0,
                latency_ms=120.0,
                error_type="wrong_answer",
            ),
        ]
    )
    assert inserted_results == 2

    stored_results = fetch_results_for_run(run.id)
    assert len(stored_results) == 2
    assert [result.attempt_index for result in stored_results] == [1, 2]
