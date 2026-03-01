"""Domain-oriented DuckDB storage helpers.

DuckDB is a good fit here because reliability evaluation is analytical:
- We run local, read-heavy aggregate queries over many results.
- We want SQL without operating a separate database server.
- A single local DB file keeps experiments reproducible and portable.
"""

import json
from datetime import datetime, timezone
from typing import Any
from uuid import uuid4

from pydantic import BaseModel, Field

from llm_reliability_analytics.models.domain import (
    ErrorTaxonomy,
    RunStatus,
    TestCase,
    TestResult,
    TestRun,
)
from llm_reliability_analytics.storage.db import get_connection, initialize_schema


class RunAggregatedSummary(BaseModel):
    run_id: str
    dataset_version: str = "v1"
    run_group_id: str = ""
    repetition_index: int = Field(default=1, ge=1)
    total_test_cases: int = Field(ge=0)
    passed: int = Field(ge=0)
    failed: int = Field(ge=0)
    accuracy: float = Field(ge=0.0, le=1.0)
    average_latency_ms: float = Field(ge=0.0)
    error_distribution: dict[str, int] = Field(default_factory=dict)
    error_taxonomy_distribution: dict[str, int] = Field(default_factory=dict)


def initialize_storage_schema() -> None:
    initialize_schema()


def upsert_test_cases(test_cases: list[TestCase]) -> int:
    if not test_cases:
        return 0

    initialize_schema()
    conn = get_connection()
    case_ids = [test_case.id for test_case in test_cases]
    placeholders = ", ".join(["?"] * len(case_ids))
    conn.execute(f"DELETE FROM test_cases WHERE test_case_id IN ({placeholders});", case_ids)

    rows = [
        (
            test_case.id,
            test_case.dataset_version,
            test_case.category,
            test_case.difficulty.value,
            test_case.prompt,
            test_case.expected_answer,
            test_case.oracle_type.value,
            json.dumps(test_case.metadata),
        )
        for test_case in test_cases
    ]
    conn.executemany(
        """
        INSERT INTO test_cases (
            test_case_id,
            dataset_version,
            category,
            difficulty,
            prompt,
            expected_answer,
            oracle_type,
            metadata
        )
        VALUES (?, ?, ?, ?, ?, ?, ?, ?);
        """,
        rows,
    )
    conn.close()
    return len(rows)


# Backward-compatible alias used by older code/tests.
insert_test_cases = upsert_test_cases


def create_test_run(
    name: str,
    model_name: str,
    dataset_version: str = "v1",
    run_group_id: str | None = None,
    repetition_index: int | None = None,
    metadata: dict[str, Any] | None = None,
    run_id: str | None = None,
) -> TestRun:
    initialize_schema()
    normalized_group_id = run_group_id or f"{name}:{model_name}:{dataset_version}"
    resolved_repetition_index = repetition_index or _next_repetition_index(normalized_group_id)
    run = TestRun(
        id=run_id or str(uuid4()),
        name=name,
        model_name=model_name,
        dataset_version=dataset_version,
        run_group_id=normalized_group_id,
        repetition_index=resolved_repetition_index,
        status=RunStatus.RUNNING,
        started_at=datetime.now(timezone.utc),
        finished_at=None,
        metadata=metadata or {},
    )

    conn = get_connection()
    conn.execute(
        """
        INSERT INTO test_runs (
            id,
            name,
            model_name,
            dataset_version,
            run_group_id,
            repetition_index,
            status,
            started_at,
            finished_at,
            metadata
        )
        VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?);
        """,
        [
            run.id,
            run.name,
            run.model_name,
            run.dataset_version,
            run.run_group_id,
            run.repetition_index,
            run.status.value,
            run.started_at,
            run.finished_at,
            json.dumps(run.metadata),
        ],
    )
    conn.close()
    return run


def insert_batch_results(results: list[TestResult]) -> int:
    if not results:
        return 0

    initialize_schema()
    run_id = results[0].run_id
    conn = get_connection()

    # Idempotent for repeated demo runs with the same run_id.
    conn.execute("DELETE FROM test_results WHERE run_id = ?;", [run_id])

    rows = [
        (
            result.run_id,
            result.test_case_id,
            result.attempt_index,
            result.dataset_version,
            result.category,
            result.actual_answer,
            result.expected_answer_normalized,
            result.actual_answer_normalized,
            result.is_correct,
            result.score,
            result.latency_ms,
            result.error_type,
            result.error_taxonomy.value,
        )
        for result in results
    ]
    conn.executemany(
        """
        INSERT INTO test_results (
            run_id,
            test_case_id,
            attempt_index,
            dataset_version,
            category,
            actual_answer,
            expected_answer_normalized,
            actual_answer_normalized,
            is_correct,
            score,
            latency_ms,
            error_type,
            error_taxonomy
        )
        VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?);
        """,
        rows,
    )

    conn.execute(
        """
        UPDATE test_runs
        SET status = ?, finished_at = ?
        WHERE id = ?;
        """,
        [RunStatus.COMPLETED.value, datetime.now(timezone.utc), run_id],
    )
    conn.close()
    return len(rows)


def fetch_aggregated_summaries(run_id: str | None = None) -> list[RunAggregatedSummary]:
    initialize_schema()
    conn = get_connection()

    filters: list[Any] = []
    where_clause = ""
    if run_id:
        where_clause = "WHERE run_id = ?"
        filters.append(run_id)

    # SQL kept explicit/readable for demo presentations.
    summary_rows = conn.execute(
        f"""
        SELECT
            r.run_id,
            tr.dataset_version,
            tr.run_group_id,
            tr.repetition_index,
            COUNT(*) AS total_test_cases,
            SUM(CASE WHEN r.is_correct THEN 1 ELSE 0 END) AS passed,
            SUM(CASE WHEN r.is_correct THEN 0 ELSE 1 END) AS failed,
            AVG(CASE WHEN r.is_correct THEN 1.0 ELSE 0.0 END) AS accuracy,
            AVG(r.latency_ms) AS average_latency_ms
        FROM test_results r
        JOIN test_runs tr
            ON tr.id = r.run_id
        {where_clause}
        GROUP BY r.run_id, tr.dataset_version, tr.run_group_id, tr.repetition_index
        ORDER BY r.run_id;
        """,
        filters,
    ).fetchall()

    summaries: list[RunAggregatedSummary] = []
    for row in summary_rows:
        current_run_id = row[0]
        error_rows = conn.execute(
            """
            SELECT error_type, COUNT(*) AS error_count
            FROM test_results
            WHERE run_id = ?
              AND error_type IS NOT NULL
            GROUP BY error_type
            ORDER BY error_type;
            """,
            [current_run_id],
        ).fetchall()
        error_distribution = {error_type: count for error_type, count in error_rows}
        taxonomy_rows = conn.execute(
            """
            SELECT error_taxonomy, COUNT(*) AS error_count
            FROM test_results
            WHERE run_id = ?
              AND error_taxonomy IS NOT NULL
              AND error_taxonomy <> ?
            GROUP BY error_taxonomy
            ORDER BY error_taxonomy;
            """,
            [current_run_id, ErrorTaxonomy.NONE.value],
        ).fetchall()
        error_taxonomy_distribution = {error_type: count for error_type, count in taxonomy_rows}

        summaries.append(
            RunAggregatedSummary(
                run_id=current_run_id,
                dataset_version=row[1],
                run_group_id=row[2],
                repetition_index=int(row[3]),
                total_test_cases=int(row[4]),
                passed=int(row[5]),
                failed=int(row[6]),
                accuracy=float(row[7]) if row[7] is not None else 0.0,
                average_latency_ms=float(row[8]) if row[8] is not None else 0.0,
                error_distribution=error_distribution,
                error_taxonomy_distribution=error_taxonomy_distribution,
            )
        )

    conn.close()
    return summaries


def fetch_results_for_run(run_id: str) -> list[TestResult]:
    initialize_schema()
    conn = get_connection()
    rows = conn.execute(
        """
        SELECT
            r.run_id,
            r.test_case_id,
            r.attempt_index,
            r.dataset_version,
            r.category,
            tc.oracle_type,
            r.actual_answer,
            r.expected_answer_normalized,
            r.actual_answer_normalized,
            r.is_correct,
            r.score,
            r.latency_ms,
            r.error_type,
            r.error_taxonomy
        FROM test_results r
        LEFT JOIN test_cases tc
            ON tc.test_case_id = r.test_case_id
        WHERE r.run_id = ?
        ORDER BY r.test_case_id, r.attempt_index;
        """,
        [run_id],
    ).fetchall()
    conn.close()

    return [
        TestResult(
            run_id=row[0],
            test_case_id=row[1],
            attempt_index=int(row[2]),
            dataset_version=row[3],
            category=row[4],
            oracle_type=row[5],
            actual_answer=row[6],
            expected_answer_normalized=row[7],
            actual_answer_normalized=row[8],
            is_correct=bool(row[9]),
            score=float(row[10]),
            latency_ms=float(row[11]),
            error_type=row[12],
            error_taxonomy=ErrorTaxonomy(row[13]) if row[13] else ErrorTaxonomy.NONE,
        )
        for row in rows
    ]


def _next_repetition_index(run_group_id: str) -> int:
    conn = get_connection()
    row = conn.execute(
        """
        SELECT COALESCE(MAX(repetition_index), 0)
        FROM test_runs
        WHERE run_group_id = ?;
        """,
        [run_group_id],
    ).fetchone()
    conn.close()
    return int(row[0]) + 1
