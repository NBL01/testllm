"""DuckDB connection + schema bootstrap.

Why DuckDB for this project:
- It is an embedded analytical database (no server setup), which is ideal for
  local experiments and student demos.
- SQL is expressive for aggregations (accuracy, latency, error distributions).
- It reads/writes local files efficiently, so iterative analytics workflows are
  simple and reproducible on a laptop.
"""

import logging
import os
from pathlib import Path

import duckdb

PROJECT_ROOT = Path(__file__).resolve().parents[3]
DATA_DIR = PROJECT_ROOT / "data"
DB_PATH = DATA_DIR / "reliability.duckdb"
logger = logging.getLogger(__name__)

EXPECTED_TABLE_COLUMNS: dict[str, list[str]] = {
    "test_cases": [
        "test_case_id",
        "test_source",
        "dataset_version",
        "category",
        "difficulty",
        "prompt",
        "expected_answer",
        "oracle_type",
        "metadata",
    ],
    "test_runs": [
        "id",
        "name",
        "run_label",
        "model_name",
        "provider",
        "model_version",
        "dataset_version",
        "evaluation_mode",
        "created_at",
        "temperature",
        "max_output_tokens",
        "repeat_count",
        "mode",
        "notes",
        "run_group_id",
        "repetition_index",
        "status",
        "started_at",
        "finished_at",
        "metadata",
    ],
    "test_results": [
        "run_id",
        "test_case_id",
        "attempt_index",
        "dataset_version",
        "category",
        "test_source",
        "prompt",
        "expected_answer",
        "oracle_type",
        "raw_output",
        "normalized_output",
        "actual_answer",
        "expected_answer_normalized",
        "actual_answer_normalized",
        "is_correct",
        "score",
        "latency_ms",
        "latency_source",
        "error_type",
        "explanation",
        "oracle_details_json",
        "error_taxonomy",
        "critical_error_flag",
        "normalized_answer",
    ],
    "evaluation_traces": [
        "trace_id",
        "run_id",
        "test_case_id",
        "attempt_index",
        "prompt",
        "raw_output",
        "normalized_output",
        "category",
        "test_source",
        "oracle_type",
        "score",
        "is_correct",
        "error_type",
        "explanation",
        "created_at",
    ],
    "candidate_test_cases": [
        "candidate_id",
        "category",
        "difficulty",
        "prompt",
        "expected_answer",
        "oracle_type",
        "source_context",
        "rationale",
        "quality_score",
        "validation_errors",
        "status",
        "metadata",
        "created_at",
        "updated_at",
    ],
    "candidate_review_events": [
        "event_id",
        "candidate_id",
        "old_status",
        "new_status",
        "reviewer",
        "note",
        "created_at",
    ],
    "evaluation_jobs": [
        "job_id",
        "status",
        "input_path",
        "provider",
        "model_name",
        "dataset_version",
        "evaluation_mode",
        "oracle_profile",
        "temperature",
        "max_output_tokens",
        "timeout_seconds",
        "repeat_count",
        "limit",
        "notes",
        "submitted_by",
        "team_name",
        "client_name",
        "project_name",
        "linked_run_id",
        "failure_reason",
        "created_at",
        "started_at",
        "completed_at",
        "updated_at",
    ],
}

MIGRATION_COLUMN_SQL_TYPES: dict[str, dict[str, str]] = {
    "test_cases": {
        "test_case_id": "TEXT",
        "test_source": "TEXT",
        "dataset_version": "TEXT",
        "category": "TEXT",
        "difficulty": "TEXT",
        "prompt": "TEXT",
        "expected_answer": "TEXT",
        "oracle_type": "TEXT",
        "metadata": "JSON",
    },
    "test_runs": {
        "id": "TEXT",
        "name": "TEXT",
        "run_label": "TEXT",
        "model_name": "TEXT",
        "provider": "TEXT",
        "model_version": "TEXT",
        "dataset_version": "TEXT",
        "evaluation_mode": "TEXT",
        "created_at": "TIMESTAMP",
        "temperature": "DOUBLE",
        "max_output_tokens": "INTEGER",
        "repeat_count": "INTEGER",
        "mode": "TEXT",
        "notes": "TEXT",
        "run_group_id": "TEXT",
        "repetition_index": "INTEGER",
        "status": "TEXT",
        "started_at": "TIMESTAMP",
        "finished_at": "TIMESTAMP",
        "metadata": "JSON",
    },
    "test_results": {
        "run_id": "TEXT",
        "test_case_id": "TEXT",
        "attempt_index": "INTEGER",
        "dataset_version": "TEXT",
        "category": "TEXT",
        "test_source": "TEXT",
        "prompt": "TEXT",
        "expected_answer": "TEXT",
        "oracle_type": "TEXT",
        "raw_output": "TEXT",
        "normalized_output": "TEXT",
        "actual_answer": "TEXT",
        "expected_answer_normalized": "TEXT",
        "actual_answer_normalized": "TEXT",
        "is_correct": "BOOLEAN",
        "score": "DOUBLE",
        "latency_ms": "DOUBLE",
        "latency_source": "TEXT",
        "error_type": "TEXT",
        "explanation": "TEXT",
        "oracle_details_json": "TEXT",
        "error_taxonomy": "TEXT",
        "critical_error_flag": "BOOLEAN",
        "normalized_answer": "TEXT",
    },
    "evaluation_traces": {
        "trace_id": "TEXT",
        "run_id": "TEXT",
        "test_case_id": "TEXT",
        "attempt_index": "INTEGER",
        "prompt": "TEXT",
        "raw_output": "TEXT",
        "normalized_output": "TEXT",
        "category": "TEXT",
        "test_source": "TEXT",
        "oracle_type": "TEXT",
        "score": "DOUBLE",
        "is_correct": "BOOLEAN",
        "error_type": "TEXT",
        "explanation": "TEXT",
        "created_at": "TIMESTAMP",
    },
    "candidate_test_cases": {
        "candidate_id": "TEXT",
        "category": "TEXT",
        "difficulty": "TEXT",
        "prompt": "TEXT",
        "expected_answer": "TEXT",
        "oracle_type": "TEXT",
        "source_context": "TEXT",
        "rationale": "TEXT",
        "quality_score": "DOUBLE",
        "validation_errors": "JSON",
        "status": "TEXT",
        "metadata": "JSON",
        "created_at": "TIMESTAMP",
        "updated_at": "TIMESTAMP",
    },
    "candidate_review_events": {
        "event_id": "TEXT",
        "candidate_id": "TEXT",
        "old_status": "TEXT",
        "new_status": "TEXT",
        "reviewer": "TEXT",
        "note": "TEXT",
        "created_at": "TIMESTAMP",
    },
    "evaluation_jobs": {
        "job_id": "TEXT",
        "status": "TEXT",
        "input_path": "TEXT",
        "provider": "TEXT",
        "model_name": "TEXT",
        "dataset_version": "TEXT",
        "evaluation_mode": "TEXT",
        "oracle_profile": "TEXT",
        "temperature": "DOUBLE",
        "max_output_tokens": "INTEGER",
        "timeout_seconds": "DOUBLE",
        "repeat_count": "INTEGER",
        "limit": "INTEGER",
        "notes": "TEXT",
        "submitted_by": "TEXT",
        "team_name": "TEXT",
        "client_name": "TEXT",
        "project_name": "TEXT",
        "linked_run_id": "TEXT",
        "failure_reason": "TEXT",
        "created_at": "TIMESTAMP",
        "started_at": "TIMESTAMP",
        "completed_at": "TIMESTAMP",
        "updated_at": "TIMESTAMP",
    },
}

CREATE_TABLE_SQL: dict[str, str] = {
    "test_cases": """
        CREATE TABLE IF NOT EXISTS test_cases (
            test_case_id TEXT PRIMARY KEY,
            test_source TEXT NOT NULL,
            dataset_version TEXT NOT NULL,
            category TEXT NOT NULL,
            difficulty TEXT NOT NULL,
            prompt TEXT NOT NULL,
            expected_answer TEXT NOT NULL,
            oracle_type TEXT NOT NULL,
            metadata JSON
        );
    """,
    "test_runs": """
        CREATE TABLE IF NOT EXISTS test_runs (
            id TEXT PRIMARY KEY,
            name TEXT NOT NULL,
            run_label TEXT,
            model_name TEXT NOT NULL,
            provider TEXT NOT NULL,
            model_version TEXT NOT NULL,
            dataset_version TEXT NOT NULL,
            evaluation_mode TEXT NOT NULL,
            created_at TIMESTAMP,
            temperature DOUBLE,
            max_output_tokens INTEGER NOT NULL,
            repeat_count INTEGER NOT NULL,
            mode TEXT NOT NULL,
            notes TEXT,
            run_group_id TEXT NOT NULL,
            repetition_index INTEGER NOT NULL,
            status TEXT NOT NULL,
            started_at TIMESTAMP,
            finished_at TIMESTAMP,
            metadata JSON
        );
    """,
    "test_results": """
        CREATE TABLE IF NOT EXISTS test_results (
            run_id TEXT NOT NULL,
            test_case_id TEXT NOT NULL,
            attempt_index INTEGER NOT NULL,
            dataset_version TEXT,
            category TEXT,
            test_source TEXT,
            prompt TEXT,
            expected_answer TEXT,
            oracle_type TEXT,
            raw_output TEXT,
            normalized_output TEXT,
            actual_answer TEXT,
            expected_answer_normalized TEXT,
            actual_answer_normalized TEXT,
            is_correct BOOLEAN NOT NULL,
            score DOUBLE NOT NULL,
            latency_ms DOUBLE NOT NULL,
            latency_source TEXT,
            error_type TEXT,
            explanation TEXT,
            oracle_details_json TEXT,
            error_taxonomy TEXT,
            critical_error_flag BOOLEAN,
            normalized_answer TEXT,
            PRIMARY KEY (run_id, test_case_id, attempt_index)
        );
    """,
    "evaluation_traces": """
        CREATE TABLE IF NOT EXISTS evaluation_traces (
            trace_id TEXT PRIMARY KEY,
            run_id TEXT NOT NULL,
            test_case_id TEXT,
            attempt_index INTEGER,
            prompt TEXT,
            raw_output TEXT,
            normalized_output TEXT,
            category TEXT,
            test_source TEXT,
            oracle_type TEXT,
            score DOUBLE,
            is_correct BOOLEAN,
            error_type TEXT,
            explanation TEXT,
            created_at TIMESTAMP
        );
    """,
    "candidate_test_cases": """
        CREATE TABLE IF NOT EXISTS candidate_test_cases (
            candidate_id TEXT PRIMARY KEY,
            category TEXT NOT NULL,
            difficulty TEXT NOT NULL,
            prompt TEXT NOT NULL,
            expected_answer TEXT NOT NULL,
            oracle_type TEXT NOT NULL,
            source_context TEXT,
            rationale TEXT,
            quality_score DOUBLE NOT NULL,
            validation_errors JSON,
            status TEXT NOT NULL,
            metadata JSON,
            created_at TIMESTAMP,
            updated_at TIMESTAMP
        );
    """,
    "candidate_review_events": """
        CREATE TABLE IF NOT EXISTS candidate_review_events (
            event_id TEXT PRIMARY KEY,
            candidate_id TEXT NOT NULL,
            old_status TEXT,
            new_status TEXT NOT NULL,
            reviewer TEXT,
            note TEXT,
            created_at TIMESTAMP
        );
    """,
    "evaluation_jobs": """
        CREATE TABLE IF NOT EXISTS evaluation_jobs (
            job_id TEXT PRIMARY KEY,
            status TEXT NOT NULL,
            input_path TEXT NOT NULL,
            provider TEXT NOT NULL,
            model_name TEXT NOT NULL,
            dataset_version TEXT,
            evaluation_mode TEXT NOT NULL,
            oracle_profile TEXT NOT NULL,
            temperature DOUBLE NOT NULL,
            max_output_tokens INTEGER NOT NULL,
            timeout_seconds DOUBLE NOT NULL,
            repeat_count INTEGER NOT NULL,
            limit INTEGER,
            notes TEXT,
            submitted_by TEXT,
            team_name TEXT,
            client_name TEXT,
            project_name TEXT,
            linked_run_id TEXT,
            failure_reason TEXT,
            created_at TIMESTAMP,
            started_at TIMESTAMP,
            completed_at TIMESTAMP,
            updated_at TIMESTAMP
        );
    """,
}


def get_db_path() -> Path:
    """Allow tests and local tooling to override the DB path safely."""
    env_override = os.getenv("LLM_RELIABILITY_DB_PATH")
    if env_override:
        return Path(env_override)
    return DB_PATH


def get_connection() -> duckdb.DuckDBPyConnection:
    db_path = get_db_path()
    db_path.parent.mkdir(parents=True, exist_ok=True)
    return duckdb.connect(str(db_path))


def initialize_database() -> None:
    conn = get_connection()
    for table_name in (
        "test_cases",
        "test_runs",
        "test_results",
        "evaluation_traces",
        "candidate_test_cases",
        "candidate_review_events",
        "evaluation_jobs",
    ):
        _ensure_table_schema(conn, table_name)
    conn.close()


def initialize_schema() -> None:
    """Alias used by the domain-oriented DuckDB storage module."""
    initialize_database()


def _ensure_table_schema(conn: duckdb.DuckDBPyConnection, table_name: str) -> None:
    expected_columns = EXPECTED_TABLE_COLUMNS[table_name]
    expected_types = MIGRATION_COLUMN_SQL_TYPES[table_name]

    if not _table_exists(conn, table_name):
        conn.execute(CREATE_TABLE_SQL[table_name])
        return

    current_columns = set(_table_columns(conn, table_name))
    missing_columns = [column for column in expected_columns if column not in current_columns]
    if not missing_columns:
        return

    logger.warning(
        "Schema mismatch for table '%s'. Missing columns=%s. Applying additive migration.",
        table_name,
        missing_columns,
    )
    for column_name in missing_columns:
        column_type = expected_types[column_name]
        conn.execute(f"ALTER TABLE {table_name} ADD COLUMN {column_name} {column_type};")


def _table_exists(conn: duckdb.DuckDBPyConnection, table_name: str) -> bool:
    row = conn.execute(
        """
        SELECT COUNT(*) AS table_count
        FROM information_schema.tables
        WHERE table_schema = 'main'
          AND table_name = ?;
        """,
        [table_name],
    ).fetchone()
    return bool(row and row[0] > 0)


def _table_columns(conn: duckdb.DuckDBPyConnection, table_name: str) -> list[str]:
    rows = conn.execute(
        """
        SELECT column_name
        FROM information_schema.columns
        WHERE table_schema = 'main'
          AND table_name = ?
        ORDER BY ordinal_position;
        """,
        [table_name],
    ).fetchall()
    return [row[0] for row in rows]
