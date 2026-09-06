"""Repository for product-level evaluation jobs."""

from __future__ import annotations

import json
from datetime import datetime, timezone
from typing import Literal
from uuid import uuid4

from pydantic import BaseModel, ConfigDict, Field

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
    dataset_sha256: str = ""
    dataset_snapshot: list[dict] = Field(default_factory=list)
    source_job_id: str | None = None
    queued_at: datetime | None = None
    created_at: datetime
    started_at: datetime | None = None
    completed_at: datetime | None = None
    updated_at: datetime


class EvaluationJobCreate(BaseModel):
    model_config = ConfigDict(str_strip_whitespace=True, allow_inf_nan=False)
    input_path: str = Field(default="sample_test_cases.jsonl", min_length=1)
    provider: Literal["mock", "ollama", "local"] = "mock"
    model_name: str = Field(default="mock-baseline", min_length=1)
    dataset_version: str | None = None
    evaluation_mode: Literal["regression", "exploratory", "adversarial", "trace_replay"] = "regression"
    oracle_profile: Literal["default"] = "default"
    temperature: float = Field(default=0.0, ge=0)
    max_output_tokens: int = Field(default=128, ge=1, le=1024)
    timeout_seconds: float = Field(default=30.0, ge=5.0, le=300.0)
    repeat_count: int = Field(default=1, ge=1)
    limit: int | None = Field(default=None, ge=1)
    notes: str = ""
    submitted_by: str = ""
    team_name: str = ""
    client_name: str = ""
    project_name: str = ""


def create_evaluation_job(payload: EvaluationJobCreate, *, dataset_sha256="", dataset_snapshot=None, source_job_id=None) -> EvaluationJob:
    initialize_schema()
    conn = get_connection()
    now = datetime.now(timezone.utc)
    job = EvaluationJob(
        dataset_sha256=dataset_sha256,
        dataset_snapshot=dataset_snapshot or [],
        source_job_id=source_job_id,
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
            updated_at, dataset_sha256, dataset_snapshot, source_job_id, queued_at
        )
        VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?);
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
            job.dataset_sha256, json.dumps(job.dataset_snapshot), job.source_job_id, job.queued_at,
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
            updated_at, dataset_sha256, dataset_snapshot, source_job_id, queued_at
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
    resolved_sort_by = sort_by if sort_by in {"created_at", "updated_at", "queued_at"} else "created_at"
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
            updated_at, dataset_sha256, dataset_snapshot, source_job_id, queued_at
        FROM evaluation_jobs
        {where_sql}
        ORDER BY {resolved_sort_by} {resolved_sort_order}, job_id {resolved_sort_order}
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


_UNSET = object()


def update_evaluation_job(job_id: str, *, status=None, linked_run_id=_UNSET, failure_reason=_UNSET,
                          started_at=_UNSET, completed_at=_UNSET, queued_at=_UNSET,
                          expected_statuses: tuple[str, ...] | None = None) -> EvaluationJob | None:
    initialize_schema()
    updates = {"updated_at": datetime.now(timezone.utc)}
    if status is not None:
        updates["status"] = status
    for field, value in {"linked_run_id": linked_run_id, "failure_reason": failure_reason,
                         "started_at": started_at, "completed_at": completed_at, "queued_at": queued_at}.items():
        if value is not _UNSET:
            updates[field] = value
    where = "job_id=?"
    params = [*updates.values(), job_id]
    if expected_statuses:
        where += f" AND status IN ({', '.join('?' for _ in expected_statuses)})"
        params.extend(expected_statuses)
    conn = get_connection()
    try:
        row = conn.execute(f"UPDATE evaluation_jobs SET {', '.join(field + '=?' for field in updates)} "
                           f"WHERE {where} RETURNING job_id", params).fetchone()
        if row is None and expected_statuses:
            raise ValueError("Job state changed; reload before retrying this action.")
    finally:
        conn.close()
    return get_evaluation_job(job_id) if row else None


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
        dataset_sha256=row[24] or "",
        dataset_snapshot=json.loads(row[25] or "[]"),
        source_job_id=row[26],
        queued_at=row[27],
    )
