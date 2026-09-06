"""Trace capture and replay helpers backed by DuckDB."""

from __future__ import annotations

import json
from datetime import datetime, timezone
from typing import Any, TypedDict

from llm_reliability_analytics.models.domain import TestResult
from llm_reliability_analytics.storage.db import get_connection, initialize_schema


class TraceEvidence(TypedDict):
    trace_id: str
    run_id: str
    test_case_id: str
    attempt_index: int
    prompt: str | None
    raw_output: str | None
    normalized_output: str | None
    category: str | None
    test_source: str | None
    oracle_type: str | None
    score: float
    is_correct: bool
    error_type: str | None
    explanation: str | None
    created_at: datetime
    expected_answer: str | None
    oracle_details: dict[str, Any]
    oracle_config: dict[str, Any] | None


def _parse_oracle_details(value: str | None) -> dict[str, Any]:
    try:
        parsed = json.loads(value) if value else {}
    except (ValueError, TypeError):
        return {}
    return parsed if isinstance(parsed, dict) else {}


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
) -> list[TraceEvidence]:
    total, items = fetch_traces_page(
        run_id=run_id,
        category=category,
        test_case_id=test_case_id,
        only_failed=only_failed,
        max_rows=max_rows,
        offset=0,
    )
    _ = total
    return items


def fetch_traces_page(
    run_id: str | None = None,
    category: str | None = None,
    test_case_id: str | None = None,
    only_failed: bool = False,
    max_rows: int = 500,
    offset: int = 0,
) -> tuple[int, list[TraceEvidence]]:
    initialize_schema()
    conn = get_connection()
    conditions: list[str] = []
    params: list[Any] = []

    if run_id:
        conditions.append("t.run_id = ?")
        params.append(run_id)
    if category:
        conditions.append("t.category = ?")
        params.append(category)
    if test_case_id:
        conditions.append("t.test_case_id = ?")
        params.append(test_case_id)
    if only_failed:
        conditions.append("t.is_correct = FALSE")

    where_clause = f"WHERE {' AND '.join(conditions)}" if conditions else ""
    total_row = conn.execute(
        f"SELECT COUNT(*) FROM evaluation_traces t {where_clause};",
        params,
    ).fetchone()
    total = int((total_row or [0])[0] or 0)

    effective_offset = max(0, int(offset))
    rows = conn.execute(
        f"""
        SELECT
            t.trace_id,
            t.run_id,
            t.test_case_id,
            t.attempt_index,
            t.prompt,
            t.raw_output,
            t.normalized_output,
            t.category,
            t.test_source,
            r.oracle_type,
            t.score,
            t.is_correct,
            t.error_type,
            t.explanation,
            t.created_at,
            r.expected_answer,
            r.oracle_details_json
        FROM evaluation_traces t
        LEFT JOIN test_results r
            ON r.run_id = t.run_id AND r.test_case_id = t.test_case_id
            AND r.attempt_index = t.attempt_index
        {where_clause}
        ORDER BY t.created_at DESC, t.run_id, t.test_case_id, t.attempt_index, t.trace_id
        LIMIT ? OFFSET ?;
        """,
        [*params, max_rows, effective_offset],
    ).fetchall()
    conn.close()

    items: list[TraceEvidence] = []
    for row in rows:
        details = _parse_oracle_details(row[16])
        config = details.get("input_config")
        items.append({
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
            "expected_answer": row[15],
            "oracle_details": details,
            "oracle_config": config if isinstance(config, dict) else None,
        })
    return total, items
