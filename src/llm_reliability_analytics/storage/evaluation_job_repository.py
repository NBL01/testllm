"""Repository for product-level evaluation jobs."""

from __future__ import annotations

from datetime import datetime, timezone
from typing import Literal
from uuid import uuid4

from pydantic import BaseModel, Field

from llm_reliability_analytics.storage.db import get_connection, initialize_schema

EvaluationJobStatus = Literal["draft", "queued", "running", "completed", "failed", "canceled"]


class EvaluationJob(BaseModel):
    job_id: str
    status: EvaluationJobStatus = "draft"
    input_path: str = "sample_test_cases.jsonl"
    provider: str = "mock"
    model_name: str = "mock-baseline"
    dataset_version: str | None = None
    evaluation_mode: str = "regression"
    oracle_profile: str = "default"
    temperature: float = 0.0
    max_output_tokens: int = Field(default=128, ge=1, le=1024)
    timeout_seconds: float = Field(default=30.0, ge=1.0, le=300.0)
    repeat_count: int = Field(default=1, ge=1)
    limit: int | None = Field(default=None, ge=1)
    notes: str = ""
    submitted_by: str = ""
    team_name: str = ""
    client_name: str = ""
    project_name: str = ""
    linked_run_id: str | None = None
    failure_reason: str | None = None
    created_at: datetime
    started_at: datetime | None = None
    completed_at: datetime | None = None
    updated_at: datetime


class EvaluationJobCreate(BaseModel):
    input_path: str = "sample_test_cases.jsonl"
    provider: Literal["mock", "ollama", "local"] = "mock"
    model_name: str = "mock-baseline"
    dataset_version: str | None = None
    evaluation_mode: Literal["regression", "exploratory", "adversarial", "trace_replay"] = "regression"
    oracle_profile: str = "default"
    temperature: float = 0.0
    max_output_tokens: int = Field(default=128, ge=1, le=1024)
    timeout_seconds: float = Field(default=30.0, ge=1.0, le=300.0)
    repeat_count: int = Field(default=1, ge=1)
    limit: int | None = Field(default=None, ge=1)
    notes: str = ""
    submitted_by: str = ""
    team_name: str = ""
    client_name: str = ""
    project_name: str = ""


def create_evaluation_job(payload: EvaluationJobCreate) -> EvaluationJob:
    initialize_schema()
    conn = get_connection()
    now = datetime.now(timezone.utc)
    job = EvaluationJob(
        job_id=str(uuid4()),
        status="draft",
        input_path=payload.input_path,
        provider=payload.provider,
        model_name=payload.model_name,
        dataset_version=payload.dataset_version,
        evaluation_mode=payload.evaluation_mode,
        oracle_profile=payload.oracle_profile.strip() or "default",
        temperature=float(payload.temperature),
        max_output_tokens=int(payload.max_output_tokens),
        timeout_seconds=float(payload.timeout_seconds),
        repeat_count=int(payload.repeat_count),
        limit=payload.limit,
        notes=payload.notes.strip(),
        submitted_by=payload.submitted_by.strip(),
        team_name=payload.team_name.strip(),
        client_name=payload.client_name.strip(),
        project_name=payload.project_name.strip(),
        created_at=now,
        updated_at=now,
    )
    conn.execute(
        """
        INSERT INTO evaluation_jobs (
            job_id,
            status,
            input_path,
            provider,
            model_name,
            dataset_version,
            evaluation_mode,
            oracle_profile,
            temperature,
            max_output_tokens,
            timeout_seconds,
            repeat_count,
            test_case_limit,
            notes,
            submitted_by,
            team_name,
            client_name,
            project_name,
            linked_run_id,
            failure_reason,
            created_at,
            started_at,
            completed_at,
            updated_at
        )
        VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?);
        """,
        [
            job.job_id,
            job.status,
            job.input_path,
            job.provider,
            job.model_name,
            job.dataset_version,
            job.evaluation_mode,
            job.oracle_profile,
            job.temperature,
            job.max_output_tokens,
            job.timeout_seconds,
            job.repeat_count,
            job.limit,
            job.notes,
            job.submitted_by,
            job.team_name,
            job.client_name,
            job.project_name,
            job.linked_run_id,
            job.failure_reason,
            job.created_at,
            job.started_at,
            job.completed_at,
            job.updated_at,
        ],
    )
    conn.close()
    return job


def get_evaluation_job(job_id: str) -> EvaluationJob | None:
    initialize_schema()
    conn = get_connection()
    row = conn.execute(
        """
        SELECT
            job_id,
            status,
            input_path,
            provider,
            model_name,
            dataset_version,
            evaluation_mode,
            oracle_profile,
            temperature,
            max_output_tokens,
            timeout_seconds,
            repeat_count,
            test_case_limit,
            notes,
            submitted_by,
            team_name,
            client_name,
            project_name,
            linked_run_id,
            failure_reason,
            created_at,
            started_at,
            completed_at,
            updated_at
        FROM evaluation_jobs
        WHERE job_id = ?;
        """,
        [job_id],
    ).fetchone()
    conn.close()
    if row is None:
        return None
    return _row_to_job(row)


def list_evaluation_jobs(
    limit: int = 100,
    status: EvaluationJobStatus | None = None,
    offset: int = 0,
    sort_by: str = "created_at",
    sort_order: str = "desc",
    search_query: str | None = None,
) -> list[EvaluationJob]:
    initialize_schema()
    conn = get_connection()
    effective_offset = max(0, int(offset))
    resolved_sort_by = "updated_at" if sort_by.strip().lower() == "updated_at" else "created_at"
    resolved_sort_order = "ASC" if sort_order.strip().lower() == "asc" else "DESC"
    normalized_search_query = (search_query or "").strip().lower()
    search_term = f"%{normalized_search_query}%"
    where_clauses: list[str] = []
    params: list[object] = []
    if status is not None:
        where_clauses.append("status = ?")
        params.append(status)
    if normalized_search_query:
        where_clauses.append(
            """
            (
                LOWER(job_id) LIKE ?
                OR LOWER(provider) LIKE ?
                OR LOWER(model_name) LIKE ?
                OR LOWER(COALESCE(dataset_version, '')) LIKE ?
                OR LOWER(COALESCE(project_name, '')) LIKE ?
                OR LOWER(COALESCE(client_name, '')) LIKE ?
                OR LOWER(COALESCE(team_name, '')) LIKE ?
                OR LOWER(COALESCE(submitted_by, '')) LIKE ?
            )
            """
        )
        params.extend([search_term] * 8)
    where_sql = f"WHERE {' AND '.join(where_clauses)}" if where_clauses else ""
    rows = conn.execute(
        f"""
        SELECT
            job_id,
            status,
            input_path,
            provider,
            model_name,
            dataset_version,
            evaluation_mode,
            oracle_profile,
            temperature,
            max_output_tokens,
            timeout_seconds,
            repeat_count,
            test_case_limit,
            notes,
            submitted_by,
            team_name,
            client_name,
            project_name,
            linked_run_id,
            failure_reason,
            created_at,
            started_at,
            completed_at,
            updated_at
        FROM evaluation_jobs
        {where_sql}
        ORDER BY {resolved_sort_by} {resolved_sort_order}
        LIMIT ? OFFSET ?;
        """,
        [*params, limit, effective_offset],
    ).fetchall()
    conn.close()
    return [_row_to_job(row) for row in rows]


def count_evaluation_jobs(status: EvaluationJobStatus | None = None, search_query: str | None = None) -> int:
    initialize_schema()
    conn = get_connection()
    normalized_search_query = (search_query or "").strip().lower()
    search_term = f"%{normalized_search_query}%"
    where_clauses: list[str] = []
    params: list[object] = []
    if status is not None:
        where_clauses.append("status = ?")
        params.append(status)
    if normalized_search_query:
        where_clauses.append(
            """
            (
                LOWER(job_id) LIKE ?
                OR LOWER(provider) LIKE ?
                OR LOWER(model_name) LIKE ?
                OR LOWER(COALESCE(dataset_version, '')) LIKE ?
                OR LOWER(COALESCE(project_name, '')) LIKE ?
                OR LOWER(COALESCE(client_name, '')) LIKE ?
                OR LOWER(COALESCE(team_name, '')) LIKE ?
                OR LOWER(COALESCE(submitted_by, '')) LIKE ?
            )
            """
        )
        params.extend([search_term] * 8)
    where_sql = f"WHERE {' AND '.join(where_clauses)}" if where_clauses else ""
    row = conn.execute(
        f"SELECT COUNT(*) FROM evaluation_jobs {where_sql};",
        params,
    ).fetchone()
    conn.close()
    return int((row or [0])[0] or 0)


def update_evaluation_job(
    job_id: str,
    *,
    status: EvaluationJobStatus | None = None,
    linked_run_id: str | None = None,
    failure_reason: str | None = None,
    started_at: datetime | None = None,
    completed_at: datetime | None = None,
) -> EvaluationJob | None:
    existing = get_evaluation_job(job_id)
    if existing is None:
        return None

    initialize_schema()
    conn = get_connection()
    now = datetime.now(timezone.utc)
    resolved_status = status or existing.status
    resolved_linked_run_id = linked_run_id if linked_run_id is not None else existing.linked_run_id
    resolved_failure_reason = failure_reason if failure_reason is not None else existing.failure_reason
    resolved_started_at = started_at if started_at is not None else existing.started_at
    resolved_completed_at = completed_at if completed_at is not None else existing.completed_at

    conn.execute(
        """
        UPDATE evaluation_jobs
        SET
            status = ?,
            linked_run_id = ?,
            failure_reason = ?,
            started_at = ?,
            completed_at = ?,
            updated_at = ?
        WHERE job_id = ?;
        """,
        [
            resolved_status,
            resolved_linked_run_id,
            resolved_failure_reason,
            resolved_started_at,
            resolved_completed_at,
            now,
            job_id,
        ],
    )
    conn.close()
    return get_evaluation_job(job_id)


def evaluation_job_status_counts() -> dict[str, int]:
    initialize_schema()
    conn = get_connection()
    rows = conn.execute(
        """
        SELECT status, COUNT(*) AS status_count
        FROM evaluation_jobs
        GROUP BY status
        ORDER BY status;
        """
    ).fetchall()
    conn.close()
    counts = {
        "draft": 0,
        "queued": 0,
        "running": 0,
        "completed": 0,
        "failed": 0,
        "canceled": 0,
    }
    for status, status_count in rows:
        normalized = str(status or "").strip().lower()
        if normalized in counts:
            counts[normalized] = int(status_count or 0)
    return counts


def _row_to_job(row: tuple) -> EvaluationJob:
    return EvaluationJob(
        job_id=row[0],
        status=row[1],
        input_path=row[2],
        provider=row[3],
        model_name=row[4],
        dataset_version=row[5],
        evaluation_mode=row[6],
        oracle_profile=row[7],
        temperature=float(row[8] or 0.0),
        max_output_tokens=int(row[9] or 128),
        timeout_seconds=float(row[10] or 30.0),
        repeat_count=int(row[11] or 1),
        limit=int(row[12]) if row[12] is not None else None,
        notes=row[13] or "",
        submitted_by=row[14] or "",
        team_name=row[15] or "",
        client_name=row[16] or "",
        project_name=row[17] or "",
        linked_run_id=row[18],
        failure_reason=row[19],
        created_at=row[20],
        started_at=row[21],
        completed_at=row[22],
        updated_at=row[23],
    )
