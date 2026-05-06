"""Trace capture and replay helpers backed by DuckDB."""

from __future__ import annotations

from datetime import datetime, timezone
from typing import Any

from llm_reliability_analytics.models.domain import TestResult
from llm_reliability_analytics.storage.db import get_connection, initialize_schema


def capture_traces_for_run(results: list[TestResult]) -> int:
    """Persist prompt/output traces so failed cases can be promoted into future tests."""
    if not results:
        return 0

    initialize_schema()
    conn = get_connection()

    created_at = datetime.now(timezone.utc)
    rows = [
        (
            f"{result.run_id}:{result.test_case_id}:{result.attempt_index}",
            result.run_id,
            result.test_case_id,
            result.attempt_index,
            result.prompt,
            result.raw_output or result.actual_answer,
            result.normalized_output or result.normalized_answer,
            result.category,
            result.test_source,
            result.oracle_type,
            result.score,
            result.is_correct,
            result.error_type,
            result.explanation,
            created_at,
        )
        for result in results
    ]
    conn.executemany(
        """
        INSERT OR REPLACE INTO evaluation_traces (
            trace_id,
            run_id,
            test_case_id,
            attempt_index,
            prompt,
            raw_output,
            normalized_output,
            category,
            test_source,
            oracle_type,
            score,
            is_correct,
            error_type,
            explanation,
            created_at
        )
        VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?);
        """,
        rows,
    )
    conn.close()
    return len(rows)


def fetch_traces(
    run_id: str | None = None,
    category: str | None = None,
    test_case_id: str | None = None,
    only_failed: bool = False,
    max_rows: int = 500,
) -> list[dict[str, Any]]:
    initialize_schema()
    conn = get_connection()
    conditions: list[str] = []
    params: list[Any] = []

    if run_id:
        conditions.append("run_id = ?")
        params.append(run_id)
    if category:
        conditions.append("category = ?")
        params.append(category)
    if test_case_id:
        conditions.append("test_case_id = ?")
        params.append(test_case_id)
    if only_failed:
        conditions.append("is_correct = FALSE")

    where_clause = f"WHERE {' AND '.join(conditions)}" if conditions else ""
    rows = conn.execute(
        f"""
        SELECT
            trace_id,
            run_id,
            test_case_id,
            attempt_index,
            prompt,
            raw_output,
            normalized_output,
            category,
            test_source,
            oracle_type,
            score,
            is_correct,
            error_type,
            explanation,
            created_at
        FROM evaluation_traces
        {where_clause}
        ORDER BY created_at DESC
        LIMIT ?;
        """,
        [*params, max_rows],
    ).fetchall()
    conn.close()

    return [
        {
            "trace_id": row[0],
            "run_id": row[1],
            "test_case_id": row[2],
            "attempt_index": row[3],
            "prompt": row[4],
            "raw_output": row[5],
            "normalized_output": row[6],
            "category": row[7],
            "test_source": row[8],
            "oracle_type": row[9],
            "score": float(row[10] or 0.0),
            "is_correct": bool(row[11]),
            "error_type": row[12],
            "explanation": row[13],
            "created_at": row[14],
        }
        for row in rows
    ]
