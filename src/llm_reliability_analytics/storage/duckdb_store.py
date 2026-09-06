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
    EvaluationMode,
    ErrorTaxonomy,
    RunStatus,
    TestCase,
    TestResult,
    TestRun,
)
from llm_reliability_analytics.storage.db import get_connection, initialize_schema, transaction_connection


class RunAggregatedSummary(BaseModel):
    run_id: str
    run_label: str = ""
    model_name: str = ""
    provider: str = ""
    model_version: str = ""
    dataset_version: str = "v1"
    evaluation_mode: str = "regression"
    created_at: datetime | None = None
    temperature: float = 0.0
    max_output_tokens: int = Field(default=128, ge=1)
    repeat_count: int = Field(default=1, ge=1)
    mode: str = "mock"
    notes: str = ""
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
    with transaction_connection() as conn:
        case_ids = [test_case.id for test_case in test_cases]
        placeholders = ", ".join(["?"] * len(case_ids))
        conn.execute(f"DELETE FROM test_cases WHERE test_case_id IN ({placeholders});", case_ids)

        rows = [
            (
                test_case.id,
                test_case.test_source.value,
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
                test_source,
                dataset_version,
                category,
                difficulty,
                prompt,
                expected_answer,
                oracle_type,
                metadata
            )
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?);
            """,
            rows,
        )
    return len(rows)


# Backward-compatible alias used by older code/tests.
insert_test_cases = upsert_test_cases


def create_test_run(
    name: str,
    model_name: str,
    run_label: str | None = None,
    provider: str = "local",
    model_version: str = "n/a",
    dataset_version: str = "v1",
    evaluation_mode: str = EvaluationMode.REGRESSION.value,
    created_at: datetime | None = None,
    temperature: float = 0.0,
    max_output_tokens: int = 128,
    repeat_count: int = 1,
    mode: str = "mock",
    notes: str = "",
    run_group_id: str | None = None,
    repetition_index: int | None = None,
    metadata: dict[str, Any] | None = None,
    run_id: str | None = None,
    connection=None,
) -> TestRun:
    if connection is None:
        initialize_schema()
    normalized_group_id = run_group_id or f"{name}:{model_name}:{dataset_version}"
    resolved_repetition_index = repetition_index or _next_repetition_index(normalized_group_id)
    resolved_created_at = created_at or datetime.now(timezone.utc)
    resolved_run_label = run_label or f"{model_name} | {dataset_version} | {resolved_created_at:%Y-%m-%d %H:%M}"
    run = TestRun(
        id=run_id or str(uuid4()),
        name=name,
        run_label=resolved_run_label,
        model_name=model_name,
        provider=provider,
        model_version=model_version,
        dataset_version=dataset_version,
        evaluation_mode=evaluation_mode,
        created_at=resolved_created_at,
        temperature=temperature,
        max_output_tokens=max(1, int(max_output_tokens)),
        repeat_count=max(1, int(repeat_count)),
        mode=mode,
        notes=notes,
        run_group_id=normalized_group_id,
        repetition_index=resolved_repetition_index,
        status=RunStatus.RUNNING,
        started_at=resolved_created_at,
        finished_at=None,
        metadata=metadata or {},
    )

    conn = connection if connection is not None else get_connection()
    conn.execute(
        """
        INSERT INTO test_runs (
            id,
            name,
            run_label,
            model_name,
            provider,
            model_version,
            dataset_version,
            evaluation_mode,
            created_at,
            temperature,
            max_output_tokens,
            repeat_count,
            mode,
            notes,
            run_group_id,
            repetition_index,
            status,
            started_at,
            finished_at,
            metadata
        )
        VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?);
        """,
        [
            run.id,
            run.name,
            run.run_label,
            run.model_name,
            run.provider,
            run.model_version,
            run.dataset_version,
            run.evaluation_mode.value,
            run.created_at,
            run.temperature,
            run.max_output_tokens,
            run.repeat_count,
            run.mode,
            run.notes,
            run.run_group_id,
            run.repetition_index,
            run.status.value,
            run.started_at,
            run.finished_at,
            json.dumps(run.metadata),
        ],
    )
    if connection is None:
        conn.close()
    return run


def insert_batch_results(results: list[TestResult], *, finalize: bool = True) -> int:
    if not results:
        return 0

    initialize_schema()
    run_id = results[0].run_id
    with transaction_connection() as conn:

        rows = [
            (
                result.run_id,
                result.test_case_id,
                result.attempt_index,
                result.dataset_version,
                result.category,
                result.test_source,
                result.prompt,
                result.expected_answer,
                result.oracle_type,
                result.raw_output,
                result.normalized_output,
                result.actual_answer,
                result.expected_answer_normalized,
                result.actual_answer_normalized,
                result.is_correct,
                result.score,
                result.latency_ms,
                result.latency_source,
                result.error_type,
                result.explanation,
                result.oracle_details_json,
                result.error_taxonomy.value,
                result.critical_error_flag,
                result.normalized_answer,
            )
            for result in results
        ]
        conn.executemany(
            """
            INSERT OR REPLACE INTO test_results (
                run_id,
                test_case_id,
                attempt_index,
                dataset_version,
                category,
                test_source,
                prompt,
                expected_answer,
                oracle_type,
                raw_output,
                normalized_output,
                actual_answer,
                expected_answer_normalized,
                actual_answer_normalized,
                is_correct,
                score,
                latency_ms,
                latency_source,
                error_type,
                explanation,
                oracle_details_json,
                error_taxonomy,
                critical_error_flag,
                normalized_answer
            )
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?);
            """,
            rows,
        )

        if finalize:
            conn.execute(
                """
                UPDATE test_runs
                SET status = ?, finished_at = ?
                WHERE id = ?;
                """,
                [RunStatus.COMPLETED.value, datetime.now(timezone.utc), run_id],
            )
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
            tr.run_label,
            tr.model_name,
            tr.provider,
            tr.model_version,
            tr.dataset_version,
            tr.evaluation_mode,
            tr.created_at,
            tr.temperature,
            tr.max_output_tokens,
            tr.repeat_count,
            tr.mode,
            tr.notes,
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
        GROUP BY
            r.run_id,
            tr.run_label,
            tr.model_name,
            tr.provider,
            tr.model_version,
            tr.dataset_version,
            tr.evaluation_mode,
            tr.created_at,
            tr.temperature,
            tr.max_output_tokens,
            tr.repeat_count,
            tr.mode,
            tr.notes,
            tr.run_group_id,
            tr.repetition_index
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
                run_label=row[1] or "",
                model_name=row[2] or "",
                provider=row[3] or "",
                model_version=row[4] or "",
                dataset_version=row[5],
                evaluation_mode=row[6] or EvaluationMode.REGRESSION.value,
                created_at=row[7],
                temperature=float(row[8] or 0.0),
                max_output_tokens=int(row[9] or 128),
                repeat_count=int(row[10] or 1),
                mode=row[11] or "mock",
                notes=row[12] or "",
                run_group_id=row[13],
                repetition_index=int(row[14]),
                total_test_cases=int(row[15]),
                passed=int(row[16]),
                failed=int(row[17]),
                accuracy=float(row[18]) if row[18] is not None else 0.0,
                average_latency_ms=float(row[19]) if row[19] is not None else 0.0,
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
            r.test_source,
            r.prompt,
            COALESCE(r.expected_answer, tc.expected_answer),
            COALESCE(r.oracle_type, tc.oracle_type),
            r.raw_output,
            r.normalized_output,
            r.actual_answer,
            r.expected_answer_normalized,
            r.actual_answer_normalized,
            r.is_correct,
            r.score,
            r.latency_ms,
            r.latency_source,
            r.error_type,
            r.explanation,
            r.oracle_details_json,
            r.error_taxonomy,
            r.critical_error_flag,
            r.normalized_answer
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
            test_source=row[5],
            prompt=row[6],
            expected_answer=row[7],
            oracle_type=row[8],
            raw_output=row[9],
            normalized_output=row[10],
            actual_answer=row[11],
            expected_answer_normalized=row[12],
            actual_answer_normalized=row[13],
            is_correct=bool(row[14]),
            score=float(row[15]),
            latency_ms=float(row[16]),
            latency_source=row[17] or "measured",
            error_type=row[18],
            explanation=row[19],
            oracle_details_json=row[20],
            error_taxonomy=ErrorTaxonomy(row[21]) if row[21] else ErrorTaxonomy.NONE,
            critical_error_flag=bool(row[22]),
            normalized_answer=row[23],
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
