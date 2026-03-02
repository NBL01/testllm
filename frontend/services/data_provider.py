"""Data access layer for the Streamlit dashboard.

The dashboard now reads from DuckDB only to avoid ambiguous fallback behavior.
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
]

REQUIRED_RESULT_COLUMNS = [
    "result_id",
    "run_id",
    "test_case_id",
    "attempt_index",
    "category",
    "test_source",
    "prompt",
    "oracle_type",
    "raw_output",
    "normalized_output",
    "actual_answer",
    "expected_answer",
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
    "provider",
    "model_name",
    "evaluation_mode",
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
        loaded = self._load_from_duckdb()
        if loaded is not None:
            return loaded
        return self._empty_loaded_data(note="DuckDB data is unavailable.")

    def _load_from_duckdb(self) -> LoadedData | None:
        if not self.db_path.exists():
            return self._empty_loaded_data(
                note=f"DuckDB file not found at {self.db_path}. Run at least one evaluation batch first.",
            )

        try:
            conn = duckdb.connect(str(self.db_path))
        except duckdb.Error as exc:
            return self._empty_loaded_data(note=f"Failed to connect DuckDB: {exc}")

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
                return self._empty_loaded_data(
                    note="DuckDB is reachable, but table 'test_results' is missing.",
                )

            runs_df = self._load_runs_from_duckdb(conn=conn, tables=tables)

            cases_df = self._load_cases_from_duckdb(conn=conn, tables=tables)

            results_df = self._load_results_from_duckdb(conn=conn, tables=tables)
        except Exception as exc:
            return self._empty_loaded_data(note=f"Failed to load dashboard data from DuckDB: {exc}")
        finally:
            conn.close()

        prepared = self._prepare_loaded_data(runs_df=runs_df, cases_df=cases_df, results_df=results_df)
        prepared.source = "duckdb"
        prepared.note = "Loaded from DuckDB"
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
                for col in ["test_case_id", "category", "test_source", "oracle_type", "expected_answer", "prompt"]
                if col in cases.columns
            ]
            if len(enrich_columns) > 1:
                case_lookup = cases[enrich_columns].drop_duplicates("test_case_id")
                results = results.merge(case_lookup, on="test_case_id", how="left", suffixes=("", "_case"))
                for col in ["category", "test_source", "oracle_type", "expected_answer", "prompt"]:
                    case_col = f"{col}_case"
                    if case_col in results.columns:
                        results[col] = results[col].fillna(results[case_col])
                        results = results.drop(columns=[case_col])

        if not runs.empty:
            run_enrich = runs[
                ["run_id", "mode", "created_at", "provider", "model_name", "evaluation_mode"]
            ].drop_duplicates("run_id")
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
        runs["evaluation_mode"] = self._series_or_default(runs, "evaluation_mode", "regression").fillna("regression")
        runs["temperature"] = pd.to_numeric(self._series_or_default(runs, "temperature", 0.0), errors="coerce").fillna(0.0)
        runs["max_output_tokens"] = pd.to_numeric(
            self._series_or_default(runs, "max_output_tokens", 128),
            errors="coerce",
        ).fillna(128).astype(int)
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

        results["is_correct"] = self._normalize_boolean_series(results["is_correct"], default=False)
        results["score"] = pd.to_numeric(results["score"], errors="coerce").fillna(0.0)
        results["latency_ms"] = pd.to_numeric(results["latency_ms"], errors="coerce").fillna(0.0)
        results["run_id"] = self._as_text_series(results["run_id"])
        results["test_case_id"] = self._as_text_series(results["test_case_id"])
        results["category"] = self._as_text_series(results["category"], default="unknown")
        results["test_source"] = self._as_text_series(results["test_source"], default="regression")
        results["prompt"] = self._as_text_series(results["prompt"])
        results["oracle_type"] = self._as_text_series(results["oracle_type"], default="unknown")
        if "raw_output" in results.columns:
            results["raw_output"] = results["raw_output"].fillna(results["actual_answer"])
        else:
            results["raw_output"] = results["actual_answer"]
        if "normalized_output" in results.columns:
            results["normalized_output"] = results["normalized_output"].fillna(results["normalized_answer"])
        else:
            results["normalized_output"] = results["normalized_answer"]

        results["raw_output"] = self._as_text_series(results["raw_output"])
        results["normalized_output"] = self._as_text_series(results["normalized_output"])
        results["actual_answer"] = self._as_text_series(results["actual_answer"])
        results["expected_answer"] = self._as_text_series(results["expected_answer"])
        results["error_type"] = self._as_text_series(results["error_type"])
        results["explanation"] = self._as_text_series(results["explanation"])
        results["oracle_details_json"] = self._as_text_series(results["oracle_details_json"])
        results["error_taxonomy"] = self._as_text_series(results["error_taxonomy"], default="none")
        results["normalized_answer"] = self._as_text_series(results["normalized_answer"])
        missing_normalized = results["normalized_answer"].str.len() == 0
        results.loc[missing_normalized, "normalized_answer"] = results.loc[missing_normalized, "actual_answer"]
        results["provider"] = self._as_text_series(results["provider"], default="unknown")
        results["model_name"] = self._as_text_series(results["model_name"], default="unknown-model")
        results["evaluation_mode"] = self._as_text_series(results["evaluation_mode"], default="regression")

        results["critical_error_flag"] = self._normalize_boolean_series(
            results["critical_error_flag"],
            default=False,
        )
        if str(results["critical_error_flag"].dtype) != "bool":
            tax = results["error_taxonomy"].astype(str).str.lower()
            results["critical_error_flag"] = tax.isin({"runtime", "oracle", "timeout", "unknown"})

        return results

    def _empty_loaded_data(self, note: str) -> LoadedData:
        return LoadedData(
            runs=pd.DataFrame(columns=REQUIRED_RUN_COLUMNS),
            cases=pd.DataFrame(columns=["test_case_id"]),
            results=pd.DataFrame(columns=REQUIRED_RESULT_COLUMNS),
            source="duckdb",
            note=note,
        )

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

    def _as_text_series(self, series: pd.Series, default: str = "") -> pd.Series:
        values = series.astype("object")
        values = values.where(~values.isna(), default)
        return values.map(lambda value: default if value is None else str(value))

    def _normalize_boolean_series(self, series: pd.Series, default: bool = False) -> pd.Series:
        def parse_bool(value: object) -> bool:
            if value is None:
                return default
            if isinstance(value, bool):
                return value
            if isinstance(value, (int, float)):
                return bool(value)
            text = str(value).strip().lower()
            if text in {"true", "1", "yes", "y", "t"}:
                return True
            if text in {"false", "0", "no", "n", "f", ""}:
                return False
            return default

        return series.map(parse_bool).astype(bool)

    def _load_runs_from_duckdb(self, conn: duckdb.DuckDBPyConnection, tables: set[str]) -> pd.DataFrame:
        if "test_runs" not in tables:
            return pd.DataFrame(columns=["run_id"])

        run_columns = self._table_columns(conn, "test_runs")

        def run_expr(column: str, alias: str, fallback_sql: str) -> str:
            if column in run_columns:
                return f"{column} AS {alias}"
            return f"{fallback_sql} AS {alias}"

        select_columns = [
            run_expr("id", "run_id", "''"),
            run_expr("name", "name", "''"),
            run_expr("run_label", "run_label", "''"),
            run_expr("model_name", "model_name", "'unknown-model'"),
            run_expr("provider", "provider", "'local'"),
            run_expr("model_version", "model_version", "'n/a'"),
            run_expr("dataset_version", "dataset_version", "'v1'"),
            run_expr("evaluation_mode", "evaluation_mode", "'regression'"),
            run_expr("created_at", "created_at", "NULL"),
            run_expr("temperature", "temperature", "0.0"),
            run_expr("max_output_tokens", "max_output_tokens", "128"),
            run_expr("repeat_count", "repeat_count", "1"),
            run_expr("mode", "mode", "'mock'"),
            run_expr("notes", "notes", "''"),
            run_expr("run_group_id", "run_group_id", "''"),
            run_expr("repetition_index", "repetition_index", "1"),
            run_expr("status", "status", "'completed'"),
            run_expr("started_at", "started_at", "NULL"),
            run_expr("finished_at", "finished_at", "NULL"),
        ]

        query = f"""
            SELECT
                {", ".join(select_columns)}
            FROM test_runs
            ORDER BY COALESCE(created_at, started_at, finished_at) DESC, run_id DESC;
        """
        return conn.execute(query).fetchdf()

    def _load_cases_from_duckdb(self, conn: duckdb.DuckDBPyConnection, tables: set[str]) -> pd.DataFrame:
        if "test_cases" not in tables:
            return pd.DataFrame(columns=["test_case_id"])

        case_columns = self._table_columns(conn, "test_cases")

        def case_expr(column: str, alias: str, fallback_sql: str) -> str:
            if column in case_columns:
                return f"{column} AS {alias}"
            return f"{fallback_sql} AS {alias}"

        select_columns = [
            case_expr("test_case_id", "test_case_id", "''"),
            case_expr("test_source", "test_source", "'regression'"),
            case_expr("dataset_version", "dataset_version", "'v1'"),
            case_expr("category", "category", "'unknown'"),
            case_expr("difficulty", "difficulty", "'medium'"),
            case_expr("prompt", "prompt", "''"),
            case_expr("expected_answer", "expected_answer", "''"),
            case_expr("oracle_type", "oracle_type", "'exact_match'"),
        ]
        return conn.execute(f"SELECT {', '.join(select_columns)} FROM test_cases;").fetchdf()

    def _load_results_from_duckdb(self, conn: duckdb.DuckDBPyConnection, tables: set[str]) -> pd.DataFrame:
        join_cases = "test_cases" in tables
        join_runs = "test_runs" in tables
        result_columns = self._table_columns(conn, "test_results")
        case_columns = self._table_columns(conn, "test_cases") if join_cases else set()

        def result_expr(column: str, fallback_sql: str) -> str:
            if column in result_columns:
                return f"r.{column}"
            return fallback_sql

        def case_expr(column: str, fallback_sql: str) -> str:
            if column in case_columns:
                return f"tc.{column}"
            return fallback_sql

        category_expr = (
            f"COALESCE({result_expr('category', 'NULL')}, {case_expr('category', 'NULL')}, 'unknown')"
            if join_cases
            else f"COALESCE({result_expr('category', 'NULL')}, 'unknown')"
        )
        test_source_expr = (
            f"COALESCE({result_expr('test_source', 'NULL')}, {case_expr('test_source', 'NULL')}, 'regression')"
            if join_cases
            else f"COALESCE({result_expr('test_source', 'NULL')}, 'regression')"
        )
        oracle_expr = (
            f"COALESCE({result_expr('oracle_type', 'NULL')}, {case_expr('oracle_type', 'NULL')}, 'unknown')"
            if join_cases
            else f"COALESCE({result_expr('oracle_type', 'NULL')}, 'unknown')"
        )
        expected_answer_expr = (
            f"COALESCE({result_expr('expected_answer', 'NULL')}, {case_expr('expected_answer', 'NULL')})"
            if join_cases
            else result_expr("expected_answer", "NULL")
        )
        prompt_expr = (
            f"COALESCE({result_expr('prompt', 'NULL')}, {case_expr('prompt', 'NULL')}, '')"
            if join_cases
            else f"COALESCE({result_expr('prompt', 'NULL')}, '')"
        )
        empty_text_sql = "''"
        raw_output_expr = f"COALESCE({result_expr('raw_output', 'NULL')}, {result_expr('actual_answer', empty_text_sql)}, '')"
        normalized_output_expr = (
            f"COALESCE({result_expr('normalized_output', 'NULL')}, "
            f"{result_expr('normalized_answer', 'NULL')}, "
            f"{result_expr('actual_answer_normalized', 'NULL')}, "
            f"{result_expr('actual_answer', empty_text_sql)})"
        )
        actual_answer_expr = f"COALESCE({result_expr('actual_answer', 'NULL')}, {result_expr('raw_output', empty_text_sql)}, '')"
        timestamp_expr = (
            "COALESCE(tr.finished_at, tr.created_at, tr.started_at)"
            if join_runs
            else "CURRENT_TIMESTAMP"
        )

        query = f"""
            SELECT
                CONCAT(r.run_id, ':', r.test_case_id, ':', r.attempt_index) AS result_id,
                r.run_id,
                r.test_case_id,
                r.attempt_index,
                {category_expr} AS category,
                {test_source_expr} AS test_source,
                {prompt_expr} AS prompt,
                {oracle_expr} AS oracle_type,
                {raw_output_expr} AS raw_output,
                {normalized_output_expr} AS normalized_output,
                {actual_answer_expr} AS actual_answer,
                {expected_answer_expr} AS expected_answer,
                r.is_correct,
                r.score,
                r.latency_ms,
                {result_expr("latency_source", "NULL")} AS latency_source,
                {result_expr("error_type", "NULL")} AS error_type,
                {result_expr("explanation", "NULL")} AS explanation,
                {result_expr("oracle_details_json", "NULL")} AS oracle_details_json,
                {result_expr("error_taxonomy", "NULL")} AS error_taxonomy,
                {result_expr("critical_error_flag", "NULL")} AS critical_error_flag,
                COALESCE(
                    {result_expr("normalized_answer", "NULL")},
                    {result_expr("normalized_output", "NULL")},
                    {result_expr("actual_answer_normalized", "NULL")},
                    {result_expr("actual_answer", "NULL")},
                    {result_expr("raw_output", "NULL")}
                ) AS normalized_answer,
                {timestamp_expr} AS timestamp
            FROM test_results r
            {"LEFT JOIN test_cases tc ON tc.test_case_id = r.test_case_id" if join_cases else ""}
            {"LEFT JOIN test_runs tr ON tr.id = r.run_id" if join_runs else ""}
            ORDER BY r.run_id, r.test_case_id, r.attempt_index;
        """
        return conn.execute(query).fetchdf()

    def _table_columns(self, conn: duckdb.DuckDBPyConnection, table_name: str) -> set[str]:
        rows = conn.execute(
            """
            SELECT column_name
            FROM information_schema.columns
            WHERE table_schema = 'main'
              AND table_name = ?;
            """,
            [table_name],
        ).fetchall()
        return {str(row[0]) for row in rows}
