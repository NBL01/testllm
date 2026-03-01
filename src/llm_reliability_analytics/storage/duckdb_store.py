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

from llm_reliability_analytics.models.domain import RunStatus, TestCase, TestResult, TestRun
from llm_reliability_analytics.storage.db import get_connection, initialize_schema


class RunAggregatedSummary(BaseModel):
    run_id: str
    total_test_cases: int = Field(ge=0)
    passed: int = Field(ge=0)
    failed: int = Field(ge=0)
    accuracy: float = Field(ge=0.0, le=1.0)
    average_latency_ms: float = Field(ge=0.0)
    error_distribution: dict[str, int] = Field(default_factory=dict)


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
            category,
            difficulty,
            prompt,
            expected_answer,
            oracle_type,
            metadata
        )
        VALUES (?, ?, ?, ?, ?, ?, ?);
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
    metadata: dict[str, Any] | None = None,
    run_id: str | None = None,
) -> TestRun:
    initialize_schema()
    run = TestRun(
        id=run_id or str(uuid4()),
        name=name,
        model_name=model_name,
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
            status,
            started_at,
            finished_at,
            metadata
        )
        VALUES (?, ?, ?, ?, ?, ?, ?);
        """,
        [
            run.id,
            run.name,
            run.model_name,
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
            result.category,
            result.actual_answer,
            result.is_correct,
            result.score,
            result.latency_ms,
            result.error_type,
        )
        for result in results
    ]
    conn.executemany(
        """
        INSERT INTO test_results (
            run_id,
            test_case_id,
            category,
            actual_answer,
            is_correct,
            score,
            latency_ms,
            error_type
        )
        VALUES (?, ?, ?, ?, ?, ?, ?, ?);
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
            run_id,
            COUNT(*) AS total_test_cases,
            SUM(CASE WHEN is_correct THEN 1 ELSE 0 END) AS passed,
            SUM(CASE WHEN is_correct THEN 0 ELSE 1 END) AS failed,
            AVG(CASE WHEN is_correct THEN 1.0 ELSE 0.0 END) AS accuracy,
            AVG(latency_ms) AS average_latency_ms
        FROM test_results
        {where_clause}
        GROUP BY run_id
        ORDER BY run_id;
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

        summaries.append(
            RunAggregatedSummary(
                run_id=current_run_id,
                total_test_cases=int(row[1]),
                passed=int(row[2]),
                failed=int(row[3]),
                accuracy=float(row[4]) if row[4] is not None else 0.0,
                average_latency_ms=float(row[5]) if row[5] is not None else 0.0,
                error_distribution=error_distribution,
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
            run_id,
            test_case_id,
            category,
            actual_answer,
            is_correct,
            score,
            latency_ms,
            error_type
        FROM test_results
        WHERE run_id = ?
        ORDER BY test_case_id;
        """,
        [run_id],
    ).fetchall()
    conn.close()

    return [
        TestResult(
            run_id=row[0],
            test_case_id=row[1],
            category=row[2],
            actual_answer=row[3],
            is_correct=bool(row[4]),
            score=float(row[5]),
            latency_ms=float(row[6]),
            error_type=row[7],
        )
        for row in rows
    ]
