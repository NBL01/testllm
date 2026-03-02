"""Data access layer for the Streamlit dashboard.

Load priority for presentation robustness:
1) DuckDB (primary project storage)
2) CSV/Parquet exports (portable fallback)
3) In-memory mock data (always available for demo)
"""

from __future__ import annotations

import os
from dataclasses import dataclass
from pathlib import Path

import duckdb
import pandas as pd


REQUIRED_RESULT_COLUMNS = [
    "result_id",
    "run_id",
    "test_case_id",
    "category",
    "oracle_type",
    "actual_answer",
    "expected_answer",
    "is_correct",
    "score",
    "latency_ms",
    "error_type",
    "error_taxonomy",
    "timestamp",
]


@dataclass
class LoadedData:
    runs: pd.DataFrame
    cases: pd.DataFrame
    results: pd.DataFrame
    source: str
    note: str = ""


class DataProvider:
    def __init__(self, project_root: Path | None = None) -> None:
        self.project_root = project_root or Path(__file__).resolve().parents[2]
        default_db_path = self.project_root / "data" / "reliability.duckdb"
        self.db_path = Path(os.getenv("LLM_RELIABILITY_DB_PATH", str(default_db_path)))

    def load(self) -> LoadedData:
        duckdb_data = self._load_from_duckdb()
        if duckdb_data is not None and not duckdb_data.results.empty:
            return duckdb_data

        file_data = self._load_from_files()
        if file_data is not None and not file_data.results.empty:
            return file_data

        return self._load_mock_data()

    def _load_from_duckdb(self) -> LoadedData | None:
        if not self.db_path.exists():
            return None

        try:
            conn = duckdb.connect(str(self.db_path))
        except duckdb.Error:
            return None

        try:
            tables = {
                row[0]
                for row in conn.execute(
                    """
                    SELECT table_name
                    FROM information_schema.tables
                    WHERE table_schema = 'main';
                    """
                ).fetchall()
            }

            if "test_results" not in tables:
                return None

            runs_df = (
                conn.execute(
                    """
                    SELECT
                        id AS run_id,
                        name,
                        model_name,
                        dataset_version,
                        run_group_id,
                        repetition_index,
                        status,
                        started_at,
                        finished_at
                    FROM test_runs
                    ORDER BY started_at DESC, run_id DESC;
                    """
                ).fetchdf()
                if "test_runs" in tables
                else pd.DataFrame(columns=["run_id"])
            )

            cases_df = (
                conn.execute(
                    """
                    SELECT
                        test_case_id,
                        dataset_version,
                        category,
                        difficulty,
                        prompt,
                        expected_answer,
                        oracle_type
                    FROM test_cases;
                    """
                ).fetchdf()
                if "test_cases" in tables
                else pd.DataFrame(columns=["test_case_id"])
            )

            results_df = conn.execute(
                """
                SELECT
                    CONCAT(r.run_id, ':', r.test_case_id, ':', r.attempt_index) AS result_id,
                    r.run_id,
                    r.test_case_id,
                    COALESCE(r.category, tc.category, 'unknown') AS category,
                    COALESCE(tc.oracle_type, 'unknown') AS oracle_type,
                    r.actual_answer,
                    tc.expected_answer,
                    r.is_correct,
                    r.score,
                    r.latency_ms,
                    r.error_type,
                    r.error_taxonomy,
                    COALESCE(tr.finished_at, tr.started_at) AS timestamp
                FROM test_results r
                LEFT JOIN test_cases tc
                    ON tc.test_case_id = r.test_case_id
                LEFT JOIN test_runs tr
                    ON tr.id = r.run_id
                ORDER BY r.run_id, r.test_case_id, r.attempt_index;
                """
            ).fetchdf()
        finally:
            conn.close()

        prepared = self._prepare_loaded_data(runs_df=runs_df, cases_df=cases_df, results_df=results_df)
        prepared.source = "duckdb"
        prepared.note = f"Loaded from {self.db_path}"
        return prepared

    def _load_from_files(self) -> LoadedData | None:
        runs_df = self._load_table_file("test_runs")
        cases_df = self._load_table_file("test_cases")
        results_df = self._load_table_file("test_results")

        if results_df is None or results_df.empty:
            return None

        prepared = self._prepare_loaded_data(
            runs_df=runs_df if runs_df is not None else pd.DataFrame(),
            cases_df=cases_df if cases_df is not None else pd.DataFrame(),
            results_df=results_df,
        )
        prepared.source = "file"
        prepared.note = "Loaded from CSV/Parquet exports"
        return prepared

    def _prepare_loaded_data(
        self,
        runs_df: pd.DataFrame,
        cases_df: pd.DataFrame,
        results_df: pd.DataFrame,
    ) -> LoadedData:
        runs = runs_df.copy()
        cases = cases_df.copy()
        results = results_df.copy()

        if "run_id" not in runs.columns and "id" in runs.columns:
            runs = runs.rename(columns={"id": "run_id"})

        if "test_case_id" not in cases.columns and "id" in cases.columns:
            cases = cases.rename(columns={"id": "test_case_id"})

        results = self._normalize_results(results)

        # Enrich missing category/oracle/expected_answer from test_cases when possible.
        if not cases.empty and "test_case_id" in cases.columns:
            enrich_columns = [
                col
                for col in ["test_case_id", "category", "oracle_type", "expected_answer"]
                if col in cases.columns
            ]
            if len(enrich_columns) > 1:
                case_lookup = cases[enrich_columns].drop_duplicates("test_case_id")
                results = results.merge(case_lookup, on="test_case_id", how="left", suffixes=("", "_case"))
                for col in ["category", "oracle_type", "expected_answer"]:
                    case_col = f"{col}_case"
                    if case_col in results.columns:
                        results[col] = results[col].fillna(results[case_col])
                        results = results.drop(columns=[case_col])

        if "timestamp" not in results.columns or results["timestamp"].isna().all():
            if not runs.empty and {"run_id", "finished_at", "started_at"}.intersection(runs.columns):
                run_time_col = "finished_at" if "finished_at" in runs.columns else "started_at"
                if run_time_col in runs.columns:
                    results = results.merge(
                        runs[["run_id", run_time_col]].drop_duplicates("run_id"),
                        on="run_id",
                        how="left",
                        suffixes=("", "_run"),
                    )
                    if "timestamp" not in results.columns:
                        results["timestamp"] = results[run_time_col]
                    else:
                        results["timestamp"] = results["timestamp"].fillna(results[run_time_col])
                    if run_time_col in results.columns:
                        results = results.drop(columns=[run_time_col])

        results["timestamp"] = pd.to_datetime(results["timestamp"], errors="coerce")
        return LoadedData(runs=runs, cases=cases, results=results, source="", note="")

    def _normalize_results(self, results_df: pd.DataFrame) -> pd.DataFrame:
        results = results_df.copy()

        # Harmonize common column aliases from external exports.
        alias_map = {
            "id": "result_id",
            "expected_answer_normalized": "expected_answer",
            "actual_answer_normalized": "actual_answer",
            "created_at": "timestamp",
            "finished_at": "timestamp",
        }
        for src, dst in alias_map.items():
            if src in results.columns and dst not in results.columns:
                results = results.rename(columns={src: dst})

        for column in REQUIRED_RESULT_COLUMNS:
            if column not in results.columns:
                results[column] = None

        if results["result_id"].isna().any() or (results["result_id"].astype(str).str.len() == 0).any():
            attempt = (
                results["attempt_index"].fillna(1).astype(int)
                if "attempt_index" in results.columns
                else 1
            )
            results["result_id"] = (
                results["run_id"].astype(str)
                + ":"
                + results["test_case_id"].astype(str)
                + ":"
                + pd.Series(attempt, index=results.index).astype(str)
            )

        results["is_correct"] = results["is_correct"].fillna(False).astype(bool)
        results["score"] = pd.to_numeric(results["score"], errors="coerce").fillna(0.0)
        results["latency_ms"] = pd.to_numeric(results["latency_ms"], errors="coerce").fillna(0.0)
        results["run_id"] = results["run_id"].astype(str)
        results["test_case_id"] = results["test_case_id"].astype(str)
        results["category"] = results["category"].fillna("unknown").astype(str)
        results["oracle_type"] = results["oracle_type"].fillna("unknown").astype(str)
        results["error_type"] = results["error_type"].fillna("")
        results["error_taxonomy"] = results["error_taxonomy"].fillna("none")

        return results[REQUIRED_RESULT_COLUMNS]

    def _load_table_file(self, table_name: str) -> pd.DataFrame | None:
        for path in self._table_file_candidates(table_name):
            if not path.exists():
                continue

            if path.suffix.lower() == ".csv":
                return pd.read_csv(path)

            if path.suffix.lower() == ".parquet":
                conn = duckdb.connect()
                try:
                    return conn.execute(
                        "SELECT * FROM read_parquet(?)",
                        [str(path)],
                    ).fetchdf()
                finally:
                    conn.close()

        return None

    def _table_file_candidates(self, table_name: str) -> list[Path]:
        directories = [
            self.project_root / "data",
            self.project_root / "data" / "raw",
            self.project_root / "data" / "export",
            self.project_root / "data" / "pbi_export",
        ]

        candidates: list[Path] = []
        for directory in directories:
            candidates.append(directory / f"{table_name}.parquet")
            candidates.append(directory / f"{table_name}.csv")

        return candidates

    def _load_mock_data(self) -> LoadedData:
        # Minimal mock dataset keeps dashboard runnable even when storage is empty.
        runs = pd.DataFrame(
            [
                {
                    "run_id": "mock-run-1",
                    "name": "mock-baseline",
                    "model_name": "mock-llm",
                    "dataset_version": "v_mock",
                    "repetition_index": 1,
                },
                {
                    "run_id": "mock-run-2",
                    "name": "mock-improved",
                    "model_name": "mock-llm-v2",
                    "dataset_version": "v_mock",
                    "repetition_index": 2,
                },
            ]
        )

        cases = pd.DataFrame(
            [
                {"test_case_id": "tc-1", "category": "factual_qa", "oracle_type": "exact_match", "expected_answer": "Paris"},
                {"test_case_id": "tc-2", "category": "classification", "oracle_type": "keyword_match", "expected_answer": "positive"},
                {"test_case_id": "tc-3", "category": "numeric_reasoning", "oracle_type": "numeric_tolerance", "expected_answer": "42"},
                {"test_case_id": "tc-4", "category": "format_constrained_json", "oracle_type": "json_schema", "expected_answer": "{\"type\":\"object\"}"},
            ]
        )

        results = pd.DataFrame(
            [
                {
                    "result_id": "mock-run-1:tc-1:1",
                    "run_id": "mock-run-1",
                    "test_case_id": "tc-1",
                    "category": "factual_qa",
                    "oracle_type": "exact_match",
                    "actual_answer": "Paris",
                    "expected_answer": "Paris",
                    "is_correct": True,
                    "score": 1.0,
                    "latency_ms": 110,
                    "error_type": "",
                    "timestamp": "2026-03-01T09:00:00Z",
                },
                {
                    "result_id": "mock-run-1:tc-2:1",
                    "run_id": "mock-run-1",
                    "test_case_id": "tc-2",
                    "category": "classification",
                    "oracle_type": "keyword_match",
                    "actual_answer": "neutral",
                    "expected_answer": "positive",
                    "is_correct": False,
                    "score": 0.0,
                    "latency_ms": 140,
                    "error_type": "wrong_answer",
                    "timestamp": "2026-03-01T09:00:00Z",
                },
                {
                    "result_id": "mock-run-1:tc-3:1",
                    "run_id": "mock-run-1",
                    "test_case_id": "tc-3",
                    "category": "numeric_reasoning",
                    "oracle_type": "numeric_tolerance",
                    "actual_answer": "42",
                    "expected_answer": "42",
                    "is_correct": True,
                    "score": 1.0,
                    "latency_ms": 160,
                    "error_type": "",
                    "timestamp": "2026-03-01T09:00:00Z",
                },
                {
                    "result_id": "mock-run-1:tc-4:1",
                    "run_id": "mock-run-1",
                    "test_case_id": "tc-4",
                    "category": "format_constrained_json",
                    "oracle_type": "json_schema",
                    "actual_answer": "{}",
                    "expected_answer": "{\"type\":\"object\"}",
                    "is_correct": True,
                    "score": 1.0,
                    "latency_ms": 130,
                    "error_type": "",
                    "timestamp": "2026-03-01T09:00:00Z",
                },
                {
                    "result_id": "mock-run-2:tc-1:1",
                    "run_id": "mock-run-2",
                    "test_case_id": "tc-1",
                    "category": "factual_qa",
                    "oracle_type": "exact_match",
                    "actual_answer": "Paris",
                    "expected_answer": "Paris",
                    "is_correct": True,
                    "score": 1.0,
                    "latency_ms": 90,
                    "error_type": "",
                    "timestamp": "2026-03-01T10:00:00Z",
                },
                {
                    "result_id": "mock-run-2:tc-2:1",
                    "run_id": "mock-run-2",
                    "test_case_id": "tc-2",
                    "category": "classification",
                    "oracle_type": "keyword_match",
                    "actual_answer": "positive",
                    "expected_answer": "positive",
                    "is_correct": True,
                    "score": 1.0,
                    "latency_ms": 120,
                    "error_type": "",
                    "timestamp": "2026-03-01T10:00:00Z",
                },
                {
                    "result_id": "mock-run-2:tc-3:1",
                    "run_id": "mock-run-2",
                    "test_case_id": "tc-3",
                    "category": "numeric_reasoning",
                    "oracle_type": "numeric_tolerance",
                    "actual_answer": "41.9",
                    "expected_answer": "42",
                    "is_correct": True,
                    "score": 0.95,
                    "latency_ms": 125,
                    "error_type": "",
                    "timestamp": "2026-03-01T10:00:00Z",
                },
                {
                    "result_id": "mock-run-2:tc-4:1",
                    "run_id": "mock-run-2",
                    "test_case_id": "tc-4",
                    "category": "format_constrained_json",
                    "oracle_type": "json_schema",
                    "actual_answer": "{\"value\":1}",
                    "expected_answer": "{\"type\":\"object\"}",
                    "is_correct": True,
                    "score": 1.0,
                    "latency_ms": 105,
                    "error_type": "",
                    "timestamp": "2026-03-01T10:00:00Z",
                },
            ]
        )

        results["timestamp"] = pd.to_datetime(results["timestamp"], errors="coerce")
        return LoadedData(
            runs=runs,
            cases=cases,
            results=results,
            source="mock",
            note="No stored data found. Showing built-in mock data for dashboard demo.",
        )
