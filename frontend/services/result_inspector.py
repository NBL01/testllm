"""Helpers for trace-level inspection in the Streamlit dashboard."""

from __future__ import annotations

import json
from typing import Any

import pandas as pd


def fetch_results_by_category(
    results_df: pd.DataFrame,
    run_id: str,
    category: str,
    failed_only: bool = False,
    low_score_threshold: float | None = None,
) -> pd.DataFrame:
    frame = results_df.copy()
    run_filtered = frame[frame["run_id"].astype(str) == str(run_id)]
    frame = run_filtered if not run_filtered.empty else frame
    frame = frame[frame["category"].astype(str) == str(category)]

    if failed_only:
        frame = frame[~frame["is_correct"].astype(bool)]
    if low_score_threshold is not None:
        frame = frame[pd.to_numeric(frame["score"], errors="coerce").fillna(0.0) <= float(low_score_threshold)]

    return frame.sort_values(["is_correct", "score", "latency_ms"], ascending=[True, True, False])


def fetch_result_trace(
    results_df: pd.DataFrame,
    runs_df: pd.DataFrame,
    result_id: str,
) -> dict[str, Any] | None:
    matched_rows = results_df[results_df["result_id"].astype(str) == str(result_id)]
    if matched_rows.empty:
        return None

    row = matched_rows.iloc[0].to_dict()
    run_id = str(row.get("run_id", ""))
    run_meta_rows = runs_df[runs_df["run_id"].astype(str) == run_id] if not runs_df.empty else pd.DataFrame()
    run_meta = run_meta_rows.iloc[0].to_dict() if not run_meta_rows.empty else {}
    oracle_details = parse_oracle_details(row.get("oracle_details_json"))

    return {
        "result_id": result_id,
        "run_id": run_id,
        "test_case": {
            "test_case_id": row.get("test_case_id", ""),
            "category": row.get("category", ""),
            "test_source": row.get("test_source", ""),
            "prompt": row.get("prompt", ""),
            "expected_answer": row.get("expected_answer", ""),
            "oracle_type": row.get("oracle_type", ""),
        },
        "model_output": {
            "provider": run_meta.get("provider", row.get("provider", "unknown")),
            "model_name": run_meta.get("model_name", row.get("model_name", "unknown-model")),
            "evaluation_mode": run_meta.get("evaluation_mode", row.get("evaluation_mode", "regression")),
            "raw_output": row.get("raw_output", row.get("actual_answer", "")),
            "latency_ms": row.get("latency_ms", 0.0),
            "attempt_index": row.get("attempt_index", 1),
        },
        "normalization": {
            "normalized_expected": row.get("expected_answer_normalized", ""),
            "normalized_output": row.get("normalized_output", row.get("normalized_answer", "")),
        },
        "oracle_evaluation": {
            "is_correct": bool(row.get("is_correct", False)),
            "score": float(row.get("score", 0.0) or 0.0),
            "error_type": row.get("error_type", ""),
            "explanation": row.get("explanation", ""),
            "details": oracle_details,
            "oracle_type": row.get("oracle_type", ""),
        },
        "raw_result": row,
        "raw_oracle_details": row.get("oracle_details_json", ""),
    }


def parse_oracle_details(raw_json: Any) -> dict[str, Any]:
    if isinstance(raw_json, dict):
        return raw_json
    if raw_json is None:
        return {}

    text = str(raw_json).strip()
    if not text:
        return {}

    try:
        parsed = json.loads(text)
    except json.JSONDecodeError:
        return {"_parse_error": "Invalid JSON trace payload", "_raw": text}

    if isinstance(parsed, dict):
        return parsed
    return {"value": parsed}
