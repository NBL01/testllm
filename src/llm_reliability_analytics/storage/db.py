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
from time import time

import duckdb

PROJECT_ROOT = Path(__file__).resolve().parents[3]
DATA_DIR = PROJECT_ROOT / "data"
DB_PATH = DATA_DIR / "reliability.duckdb"
logger = logging.getLogger(__name__)

EXPECTED_TABLE_COLUMNS: dict[str, list[str]] = {
    "test_cases": [
        "test_case_id",
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
        "created_at",
        "temperature",
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
        "actual_answer",
        "expected_answer_normalized",
        "actual_answer_normalized",
        "is_correct",
        "score",
        "latency_ms",
        "latency_source",
        "error_type",
        "error_taxonomy",
        "critical_error_flag",
        "normalized_answer",
    ],
}

CREATE_TABLE_SQL: dict[str, str] = {
    "test_cases": """
        CREATE TABLE IF NOT EXISTS test_cases (
            test_case_id TEXT PRIMARY KEY,
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
            created_at TIMESTAMP,
            temperature DOUBLE,
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
            actual_answer TEXT,
            expected_answer_normalized TEXT,
            actual_answer_normalized TEXT,
            is_correct BOOLEAN NOT NULL,
            score DOUBLE NOT NULL,
            latency_ms DOUBLE NOT NULL,
            latency_source TEXT,
            error_type TEXT,
            error_taxonomy TEXT,
            critical_error_flag BOOLEAN,
            normalized_answer TEXT,
            PRIMARY KEY (run_id, test_case_id, attempt_index)
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
    for table_name in ("test_cases", "test_runs", "test_results"):
        _ensure_table_schema(conn, table_name)
    conn.close()


def initialize_schema() -> None:
    """Alias used by the domain-oriented DuckDB storage module."""
    initialize_database()


def _ensure_table_schema(conn: duckdb.DuckDBPyConnection, table_name: str) -> None:
    expected_columns = EXPECTED_TABLE_COLUMNS[table_name]

    if not _table_exists(conn, table_name):
        conn.execute(CREATE_TABLE_SQL[table_name])
        return

    current_columns = _table_columns(conn, table_name)
    if current_columns == expected_columns:
        return

    # For demo safety, keep old data by renaming the table, then recreate schema.
    backup_name = f"{table_name}__backup_{int(time())}"
    logger.warning(
        "Schema mismatch for table '%s'. Backing up to '%s' and recreating table.",
        table_name,
        backup_name,
    )
    conn.execute(f"ALTER TABLE {table_name} RENAME TO {backup_name};")
    conn.execute(CREATE_TABLE_SQL[table_name])


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
