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


REQUIRED_RUN_COLUMNS = [
    "run_id",
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
]

REQUIRED_RESULT_COLUMNS = [
    "result_id",
    "run_id",
    "test_case_id",
    "attempt_index",
    "category",
    "oracle_type",
    "actual_answer",
    "expected_answer",
    "is_correct",
    "score",
    "latency_ms",
    "latency_source",
    "error_type",
    "error_taxonomy",
    "critical_error_flag",
    "normalized_answer",
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
                        run_label,
                        model_name,
                        provider,
                        model_version,
                        dataset_version,
                        created_at,
                        temperature,
                        repeat_count,
                        mode,
                        notes,
                        run_group_id,
                        repetition_index,
                        status,
                        started_at,
                        finished_at
                    FROM test_runs
                    ORDER BY COALESCE(created_at, started_at, finished_at) DESC, run_id DESC;
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
                    r.attempt_index,
                    COALESCE(r.category, tc.category, 'unknown') AS category,
                    COALESCE(tc.oracle_type, 'unknown') AS oracle_type,
                    r.actual_answer,
                    tc.expected_answer,
                    r.is_correct,
                    r.score,
                    r.latency_ms,
                    r.latency_source,
                    r.error_type,
                    r.error_taxonomy,
                    r.critical_error_flag,
                    COALESCE(r.normalized_answer, r.actual_answer_normalized, r.actual_answer) AS normalized_answer,
                    COALESCE(tr.finished_at, tr.created_at, tr.started_at) AS timestamp
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
        prepared.note = f"Loaded from DuckDB"
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
        runs = self._normalize_runs(runs_df)
        cases = cases_df.copy()
        if "test_case_id" not in cases.columns and "id" in cases.columns:
            cases = cases.rename(columns={"id": "test_case_id"})

        results = self._normalize_results(results_df)

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

        if not runs.empty:
            run_enrich = runs[["run_id", "mode", "created_at"]].drop_duplicates("run_id")
            results = results.merge(run_enrich, on="run_id", how="left", suffixes=("", "_run"))

            results["timestamp"] = results["timestamp"].fillna(results["created_at"])
            # If latency source is not provided, infer from mode for explainability.
            missing_latency_source = results["latency_source"].isna() | (results["latency_source"].astype(str).str.len() == 0)
            results.loc[missing_latency_source & (results["mode"] == "mock"), "latency_source"] = "mock_simulated"
            results.loc[missing_latency_source & (results["mode"] != "mock"), "latency_source"] = "observed"

            results = results.drop(columns=[col for col in ["mode", "created_at"] if col in results.columns])

        results["timestamp"] = pd.to_datetime(results["timestamp"], errors="coerce")
        return LoadedData(runs=runs, cases=cases, results=results[REQUIRED_RESULT_COLUMNS], source="", note="")

    def _normalize_runs(self, runs_df: pd.DataFrame) -> pd.DataFrame:
        runs = runs_df.copy()
        if runs.empty:
            return pd.DataFrame(columns=REQUIRED_RUN_COLUMNS)

        if "run_id" not in runs.columns and "id" in runs.columns:
            runs = runs.rename(columns={"id": "run_id"})

        # Graceful fallbacks for legacy schema fields.
        if "created_at" not in runs.columns:
            if "started_at" in runs.columns:
                runs["created_at"] = runs["started_at"]
            elif "finished_at" in runs.columns:
                runs["created_at"] = runs["finished_at"]
            else:
                runs["created_at"] = pd.Timestamp.utcnow()

        runs["created_at"] = pd.to_datetime(runs["created_at"], errors="coerce")
        runs["name"] = self._series_or_default(runs, "name", "").fillna("")
        runs["model_name"] = self._series_or_default(runs, "model_name", "unknown-model").fillna("unknown-model")
        runs["provider"] = self._series_or_default(runs, "provider", "local").fillna("local")
        runs["model_version"] = self._series_or_default(runs, "model_version", "n/a").fillna("n/a")
        runs["dataset_version"] = self._series_or_default(runs, "dataset_version", "v1").fillna("v1")
        runs["temperature"] = pd.to_numeric(self._series_or_default(runs, "temperature", 0.0), errors="coerce").fillna(0.0)
        if "repeat_count" in runs.columns:
            runs["repeat_count"] = pd.to_numeric(runs["repeat_count"], errors="coerce").fillna(1).astype(int)
        else:
            runs["repeat_count"] = pd.to_numeric(self._series_or_default(runs, "repetition_index", 1), errors="coerce").fillna(1).astype(int)

        inferred_mode = runs["mode"] if "mode" in runs.columns else None
        if inferred_mode is None:
            inferred_mode = runs["model_name"].astype(str).str.lower().apply(
                lambda value: "mock" if "mock" in value else "real"
            )
        runs["mode"] = inferred_mode.fillna("mock")

        runs["notes"] = self._series_or_default(runs, "notes", "").fillna("")
        runs["run_group_id"] = self._series_or_default(runs, "run_group_id", "").fillna("")
        runs["repetition_index"] = pd.to_numeric(self._series_or_default(runs, "repetition_index", 1), errors="coerce").fillna(1).astype(int)
        runs["status"] = self._series_or_default(runs, "status", "completed").fillna("completed")

        if "run_label" not in runs.columns:
            runs["run_label"] = ""
        runs["run_label"] = runs["run_label"].fillna("")

        missing_label = runs["run_label"].astype(str).str.strip().eq("")
        runs.loc[missing_label, "run_label"] = runs[missing_label].apply(
            lambda row: self._build_run_label(
                model_name=str(row["model_name"]),
                dataset_version=str(row["dataset_version"]),
                created_at=row["created_at"],
            ),
            axis=1,
        )

        return runs[[col for col in REQUIRED_RUN_COLUMNS if col in runs.columns]]

    def _normalize_results(self, results_df: pd.DataFrame) -> pd.DataFrame:
        results = results_df.copy()

        alias_map = {
            "id": "result_id",
            "expected_answer_normalized": "expected_answer",
            "actual_answer_normalized": "normalized_answer",
            "created_at": "timestamp",
            "finished_at": "timestamp",
        }
        for src, dst in alias_map.items():
            if src in results.columns and dst not in results.columns:
                results = results.rename(columns={src: dst})

        for column in REQUIRED_RESULT_COLUMNS:
            if column not in results.columns:
                results[column] = None

        if "attempt_index" not in results.columns or results["attempt_index"].isna().all():
            if "result_id" in results.columns:
                results["attempt_index"] = (
                    results["result_id"].astype(str).str.split(":").str[-1].str.extract(r"(\d+)")[0]
                )
            else:
                results["attempt_index"] = 1

        results["attempt_index"] = pd.to_numeric(results["attempt_index"], errors="coerce").fillna(1).astype(int)

        if results["result_id"].isna().any() or (results["result_id"].astype(str).str.len() == 0).any():
            results["result_id"] = (
                results["run_id"].astype(str)
                + ":"
                + results["test_case_id"].astype(str)
                + ":"
                + results["attempt_index"].astype(str)
            )

        results["is_correct"] = results["is_correct"].fillna(False).astype(bool)
        results["score"] = pd.to_numeric(results["score"], errors="coerce").fillna(0.0)
        results["latency_ms"] = pd.to_numeric(results["latency_ms"], errors="coerce").fillna(0.0)
        results["run_id"] = results["run_id"].astype(str)
        results["test_case_id"] = results["test_case_id"].astype(str)
        results["category"] = results["category"].fillna("unknown").astype(str)
        results["oracle_type"] = results["oracle_type"].fillna("unknown").astype(str)
        results["actual_answer"] = results["actual_answer"].fillna("")
        results["expected_answer"] = results["expected_answer"].fillna("")
        results["error_type"] = results["error_type"].fillna("")
        results["error_taxonomy"] = results["error_taxonomy"].fillna("none")
        results["normalized_answer"] = results["normalized_answer"].fillna(results["actual_answer"]).astype(str)

        results["critical_error_flag"] = results["critical_error_flag"].fillna(False)
        if results["critical_error_flag"].dtype != bool:
            tax = results["error_taxonomy"].astype(str).str.lower()
            results["critical_error_flag"] = tax.isin({"runtime", "oracle", "timeout", "unknown"})

        return results

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
        runs = pd.DataFrame(
            [
                {
                    "run_id": "mock-run-1",
                    "name": "mock-baseline",
                    "run_label": "mock-llm | v_mock | 2026-03-01 09:00",
                    "model_name": "mock-llm",
                    "provider": "local",
                    "model_version": "v1",
                    "dataset_version": "v_mock",
                    "created_at": "2026-03-01T09:00:00Z",
                    "temperature": 0.0,
                    "repeat_count": 2,
                    "mode": "mock",
                    "notes": "Baseline mock run",
                    "run_group_id": "mock-group",
                    "repetition_index": 1,
                    "status": "completed",
                },
                {
                    "run_id": "mock-run-2",
                    "name": "mock-improved",
                    "run_label": "mock-llm-v2 | v_mock | 2026-03-01 10:00",
                    "model_name": "mock-llm-v2",
                    "provider": "local",
                    "model_version": "v2",
                    "dataset_version": "v_mock",
                    "created_at": "2026-03-01T10:00:00Z",
                    "temperature": 0.0,
                    "repeat_count": 2,
                    "mode": "mock",
                    "notes": "Improved prompt setup",
                    "run_group_id": "mock-group",
                    "repetition_index": 2,
                    "status": "completed",
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
                {"result_id": "mock-run-1:tc-1:1", "run_id": "mock-run-1", "test_case_id": "tc-1", "attempt_index": 1, "category": "factual_qa", "oracle_type": "exact_match", "actual_answer": "Paris", "expected_answer": "Paris", "is_correct": True, "score": 1.0, "latency_ms": 2.2, "latency_source": "mock_simulated", "error_type": "", "error_taxonomy": "none", "critical_error_flag": False, "normalized_answer": "paris", "timestamp": "2026-03-01T09:00:00Z"},
                {"result_id": "mock-run-1:tc-1:2", "run_id": "mock-run-1", "test_case_id": "tc-1", "attempt_index": 2, "category": "factual_qa", "oracle_type": "exact_match", "actual_answer": "Paris", "expected_answer": "Paris", "is_correct": True, "score": 1.0, "latency_ms": 2.5, "latency_source": "mock_simulated", "error_type": "", "error_taxonomy": "none", "critical_error_flag": False, "normalized_answer": "paris", "timestamp": "2026-03-01T09:00:00Z"},
                {"result_id": "mock-run-1:tc-2:1", "run_id": "mock-run-1", "test_case_id": "tc-2", "attempt_index": 1, "category": "classification", "oracle_type": "keyword_match", "actual_answer": "neutral", "expected_answer": "positive", "is_correct": False, "score": 0.0, "latency_ms": 2.9, "latency_source": "mock_simulated", "error_type": "wrong_answer", "error_taxonomy": "none", "critical_error_flag": False, "normalized_answer": "neutral", "timestamp": "2026-03-01T09:00:00Z"},
                {"result_id": "mock-run-2:tc-1:1", "run_id": "mock-run-2", "test_case_id": "tc-1", "attempt_index": 1, "category": "factual_qa", "oracle_type": "exact_match", "actual_answer": "Paris", "expected_answer": "Paris", "is_correct": True, "score": 1.0, "latency_ms": 1.8, "latency_source": "mock_simulated", "error_type": "", "error_taxonomy": "none", "critical_error_flag": False, "normalized_answer": "paris", "timestamp": "2026-03-01T10:00:00Z"},
                {"result_id": "mock-run-2:tc-2:1", "run_id": "mock-run-2", "test_case_id": "tc-2", "attempt_index": 1, "category": "classification", "oracle_type": "keyword_match", "actual_answer": "positive", "expected_answer": "positive", "is_correct": True, "score": 1.0, "latency_ms": 2.1, "latency_source": "mock_simulated", "error_type": "", "error_taxonomy": "none", "critical_error_flag": False, "normalized_answer": "positive", "timestamp": "2026-03-01T10:00:00Z"},
                {"result_id": "mock-run-2:tc-3:1", "run_id": "mock-run-2", "test_case_id": "tc-3", "attempt_index": 1, "category": "numeric_reasoning", "oracle_type": "numeric_tolerance", "actual_answer": "41.9", "expected_answer": "42", "is_correct": True, "score": 0.95, "latency_ms": 2.3, "latency_source": "mock_simulated", "error_type": "", "error_taxonomy": "none", "critical_error_flag": False, "normalized_answer": "41.9", "timestamp": "2026-03-01T10:00:00Z"},
                {"result_id": "mock-run-2:tc-4:1", "run_id": "mock-run-2", "test_case_id": "tc-4", "attempt_index": 1, "category": "format_constrained_json", "oracle_type": "json_schema", "actual_answer": "{\"value\":1}", "expected_answer": "{\"type\":\"object\"}", "is_correct": True, "score": 1.0, "latency_ms": 2.0, "latency_source": "mock_simulated", "error_type": "", "error_taxonomy": "none", "critical_error_flag": False, "normalized_answer": "{\"value\":1}", "timestamp": "2026-03-01T10:00:00Z"},
            ]
        )

        prepared = self._prepare_loaded_data(runs_df=runs, cases_df=cases, results_df=results)
        prepared.source = "mock"
        prepared.note = "No stored data found. Showing built-in mock data for dashboard demo."
        return prepared

    def _build_run_label(self, model_name: str, dataset_version: str, created_at: pd.Timestamp | None) -> str:
        if created_at is None or pd.isna(created_at):
            created_fragment = "unknown-time"
        else:
            created_fragment = created_at.strftime("%Y-%m-%d %H:%M")
        return f"{model_name} | {dataset_version} | {created_fragment}"

    def _series_or_default(self, frame: pd.DataFrame, column: str, default_value: object) -> pd.Series:
        if column in frame.columns:
            return frame[column]
        return pd.Series([default_value] * len(frame), index=frame.index)
