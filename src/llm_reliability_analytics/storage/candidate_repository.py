"""Persistence helpers for candidate test authoring workflow."""

from __future__ import annotations

import json
from datetime import datetime, timezone
from typing import Any
from uuid import uuid4

from pydantic import BaseModel, Field

from llm_reliability_analytics.models.domain import DifficultyLevel
from llm_reliability_analytics.storage.db import get_connection, initialize_schema
from llm_reliability_analytics.test_authoring.models import CandidateStatus, CandidateTestCase


class CandidateReviewEvent(BaseModel):
    event_id: str
    candidate_id: str
    old_status: CandidateStatus | None = None
    new_status: CandidateStatus
    reviewer: str = ""
    note: str = ""
    created_at: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))


def upsert_candidate_test_cases(candidates: list[CandidateTestCase]) -> int:
    if not candidates:
        return 0

    initialize_schema()
    conn = get_connection()
    now = datetime.now(timezone.utc)

    rows = [
        (
            candidate.candidate_id,
            candidate.category,
            candidate.difficulty.value,
            candidate.prompt,
            candidate.expected_answer,
            candidate.oracle_type,
            candidate.source_context,
            candidate.rationale,
            candidate.quality_score,
            json.dumps(candidate.validation_errors),
            candidate.status.value,
            json.dumps(candidate.metadata),
            candidate.created_at,
            now,
        )
        for candidate in candidates
    ]

    conn.executemany(
        """
        INSERT OR REPLACE INTO candidate_test_cases (
            candidate_id,
            category,
            difficulty,
            prompt,
            expected_answer,
            oracle_type,
            source_context,
            rationale,
            quality_score,
            validation_errors,
            status,
            metadata,
            created_at,
            updated_at
        )
        VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?);
        """,
        rows,
    )
    conn.close()
    return len(rows)


def list_candidate_test_cases(
    status: CandidateStatus | None = None,
    category: str | None = None,
    max_rows: int = 500,
) -> list[CandidateTestCase]:
    initialize_schema()
    conn = get_connection()
    conditions: list[str] = []
    params: list[Any] = []

    if status is not None:
        conditions.append("status = ?")
        params.append(status.value)
    if category:
        conditions.append("category = ?")
        params.append(category)

    where_clause = f"WHERE {' AND '.join(conditions)}" if conditions else ""
    rows = conn.execute(
        f"""
        SELECT
            candidate_id,
            category,
            difficulty,
            prompt,
            expected_answer,
            oracle_type,
            source_context,
            rationale,
            quality_score,
            validation_errors,
            status,
            metadata,
            created_at
        FROM candidate_test_cases
        {where_clause}
        ORDER BY created_at DESC
        LIMIT ?;
        """,
        [*params, max_rows],
    ).fetchall()
    conn.close()

    return [_row_to_candidate(row) for row in rows]


def get_candidate_test_case(candidate_id: str) -> CandidateTestCase | None:
    initialize_schema()
    conn = get_connection()
    row = conn.execute(
        """
        SELECT
            candidate_id,
            category,
            difficulty,
            prompt,
            expected_answer,
            oracle_type,
            source_context,
            rationale,
            quality_score,
            validation_errors,
            status,
            metadata,
            created_at
        FROM candidate_test_cases
        WHERE candidate_id = ?;
        """,
        [candidate_id],
    ).fetchone()
    conn.close()
    if row is None:
        return None
    return _row_to_candidate(row)


def update_candidate_status(
    candidate_id: str,
    new_status: CandidateStatus,
    reviewer: str = "",
    note: str = "",
) -> CandidateTestCase | None:
    initialize_schema()
    conn = get_connection()
    row = conn.execute(
        "SELECT status FROM candidate_test_cases WHERE candidate_id = ?;",
        [candidate_id],
    ).fetchone()
    if row is None:
        conn.close()
        return None

    old_status_raw = row[0]
    old_status = CandidateStatus(old_status_raw) if old_status_raw else None
    now = datetime.now(timezone.utc)

    conn.execute(
        """
        UPDATE candidate_test_cases
        SET status = ?, updated_at = ?
        WHERE candidate_id = ?;
        """,
        [new_status.value, now, candidate_id],
    )
    conn.execute(
        """
        INSERT INTO candidate_review_events (
            event_id,
            candidate_id,
            old_status,
            new_status,
            reviewer,
            note,
            created_at
        )
        VALUES (?, ?, ?, ?, ?, ?, ?);
        """,
        [
            str(uuid4()),
            candidate_id,
            old_status.value if old_status else None,
            new_status.value,
            reviewer,
            note,
            now,
        ],
    )
    conn.close()
    return get_candidate_test_case(candidate_id)


def list_candidate_review_events(candidate_id: str, max_rows: int = 100) -> list[CandidateReviewEvent]:
    initialize_schema()
    conn = get_connection()
    rows = conn.execute(
        """
        SELECT event_id, candidate_id, old_status, new_status, reviewer, note, created_at
        FROM candidate_review_events
        WHERE candidate_id = ?
        ORDER BY created_at DESC
        LIMIT ?;
        """,
        [candidate_id, max_rows],
    ).fetchall()
    conn.close()

    events: list[CandidateReviewEvent] = []
    for row in rows:
        events.append(
            CandidateReviewEvent(
                event_id=row[0],
                candidate_id=row[1],
                old_status=CandidateStatus(row[2]) if row[2] else None,
                new_status=CandidateStatus(row[3]),
                reviewer=row[4] or "",
                note=row[5] or "",
                created_at=row[6],
            )
        )
    return events


def _row_to_candidate(row: tuple[Any, ...]) -> CandidateTestCase:
    validation_errors = row[9]
    if isinstance(validation_errors, str):
        parsed_validation_errors = json.loads(validation_errors)
    else:
        parsed_validation_errors = list(validation_errors or [])

    metadata_raw = row[11]
    if isinstance(metadata_raw, str):
        parsed_metadata = json.loads(metadata_raw)
    else:
        parsed_metadata = dict(metadata_raw or {})

    return CandidateTestCase(
        candidate_id=row[0],
        category=row[1],
        difficulty=DifficultyLevel(row[2]),
        prompt=row[3],
        expected_answer=row[4],
        oracle_type=row[5],
        source_context=row[6] or "",
        rationale=row[7] or "",
        quality_score=float(row[8] or 0.0),
        validation_errors=list(parsed_validation_errors or []),
        status=CandidateStatus(row[10]),
        metadata=parsed_metadata,
        created_at=row[12],
    )
