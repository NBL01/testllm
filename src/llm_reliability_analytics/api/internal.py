"""Backend-owned run comparison for the client: eligibility and side-by-side evidence."""

from __future__ import annotations

import json
from collections import defaultdict
from typing import Any

import duckdb
import pandas as pd
from fastapi import APIRouter, HTTPException
from pydantic import BaseModel, Field, field_validator

from llm_reliability_analytics.analytics.reliability import ReliabilityReport, compute_reliability_report
from llm_reliability_analytics.models.domain import TestResult
from llm_reliability_analytics.storage.db import get_connection, get_db_path
from llm_reliability_analytics.storage.duckdb_store import fetch_results_for_run

router = APIRouter(prefix="/internal", tags=["internal"])


class MetricsRequest(BaseModel):
    run_ids: list[str] = Field(min_length=2, max_length=2, description="Baseline, then candidate.")

    @field_validator("run_ids")
    @classmethod
    def valid_run_ids(cls, values: list[str]) -> list[str]:
        values = [value.strip() for value in values]
        if any(not value for value in values) or len(set(values)) != len(values):
            raise ValueError("Run IDs must be nonempty and distinct.")
        return values


def _json_object(value: Any) -> dict[str, Any]:
    if isinstance(value, dict):
        return value
    if value is None or (isinstance(value, float) and pd.isna(value)):
        return {}
    try:
        parsed = json.loads(str(value))
    except (TypeError, ValueError):
        return {}
    return parsed if isinstance(parsed, dict) else {}


def _metric_context(run_ids: list[str]) -> tuple[dict[str, dict], dict[str, list[TestResult]]]:
    if not get_db_path().is_file():
        raise HTTPException(status_code=503, detail="Backend database is unavailable.")
    try:
        conn = get_connection()
        try:
            placeholders = ", ".join("?" for _ in run_ids)
            cursor = conn.execute(f"SELECT * FROM test_runs WHERE id IN ({placeholders})", run_ids)
            columns = [column[0] for column in cursor.description]
            runs = {row["id"]: row for row in (dict(zip(columns, values)) for values in cursor.fetchall())}
        finally:
            conn.close()
        missing = [run_id for run_id in run_ids if run_id not in runs]
        if missing:
            raise HTTPException(status_code=404, detail=f"Run not found: {', '.join(missing)}")
        # Ponytail: selected runs are materialized in memory; use paged aggregation for large histories.
        results = {run_id: fetch_results_for_run(run_id) for run_id in run_ids}
    except duckdb.Error as exc:
        raise HTTPException(status_code=503, detail="Backend database could not be read.") from exc
    return runs, results


def _report_for(run_id: str, runs: dict[str, dict], results: dict[str, list[TestResult]]) -> ReliabilityReport:
    return compute_reliability_report(
        results[run_id], run_id=run_id, dataset_version=runs[run_id]["dataset_version"],
    )


def _eligibility(runs: dict[str, dict], results: dict[str, list[TestResult]]) -> dict[str, Any]:
    issues: list[str] = []
    if any(run["status"] != "completed" for run in runs.values()):
        issues.append("only completed runs can be compared")
    metadata = [_json_object(run["metadata"]) for run in runs.values()]
    configurations = [_json_object(item.get("configuration")) for item in metadata]
    fields = {key: [run.get(key) for run in runs.values()] for key in (
        "provider", "dataset_version", "evaluation_mode", "mode", "temperature", "max_output_tokens", "repeat_count",
    )}
    fields["dataset_sha256"] = [item.get("dataset_sha256") for item in metadata]
    if all(run.get("mode") in REAL_MODES for run in runs.values()):
        # Between real executions the serving stack (Ollama vs an OpenAI-compatible
        # server) is part of the system under test, like model_name; mock vs real is not.
        del fields["provider"], fields["mode"]
    fields.update({key: [config.get(key) for config in configurations]
                   for key in ("oracle_profile", "timeout_seconds", "seed")})
    for key, values in fields.items():
        if any(value is None or value == "" for value in values):
            issues.append(f"unknown {key}")
        elif any(value != values[0] for value in values[1:]):
            issues.append(key)
    versions: dict[str, set[str]] = defaultdict(set)
    for run in runs.values():
        versions[run["model_name"]].add(run["model_version"])
    if any(len(values) > 1 for values in versions.values()):
        issues.append("model_version")

    evidence = []
    oracle_configs = []
    for run_id, rows in results.items():
        if not rows:
            issues.append(f"no stored evidence for {run_id}")
        cases: dict[str, set[int]] = defaultdict(set)
        configs = {}
        for row in rows:
            cases[row.test_case_id].add(row.attempt_index)
            config = _json_object(row.oracle_details_json).get("input_config")
            if not isinstance(config, dict):
                issues.append("unknown input_config")
            configs[(row.test_case_id, row.attempt_index)] = config
        expected_attempts = set(range(1, runs[run_id]["repeat_count"] + 1))
        if any(indices != expected_attempts for indices in cases.values()):
            issues.append("incomplete attempt coverage/evidence")
        evidence.append({(row.test_case_id, row.attempt_index, row.prompt, row.expected_answer,
                         row.oracle_type, row.test_source, row.category) for row in rows})
        oracle_configs.append(configs)
    if any(item != evidence[0] for item in evidence[1:]):
        issues.append("test case coverage/evidence")
    if any(item != oracle_configs[0] for item in oracle_configs[1:]):
        issues.append("input_config")
    issues = list(dict.fromkeys(issues))
    return {"eligible": not issues, "research_only": bool(issues), "issues": issues}


REAL_MODES = {"real_local", "real_api"}


def _case_changes(baseline: list[TestResult], candidate: list[TestResult]) -> dict[str, list[dict[str, Any]]]:
    """Cases whose passed-attempt count moved between two eligible runs (same cases and attempts)."""
    def tally(rows: list[TestResult]) -> dict[str, tuple[int, int, str]]:
        counts: dict[str, list] = {}
        for row in rows:
            entry = counts.setdefault(row.test_case_id, [0, 0, row.category or "uncategorized"])
            entry[0] += int(row.is_correct)
            entry[1] += 1
        return {case: (passed, attempts, category) for case, (passed, attempts, category) in counts.items()}

    before, after = tally(baseline), tally(candidate)
    changes = [{"test_case_id": case, "category": before[case][2], "attempts": before[case][1],
                "baseline_passed": before[case][0], "candidate_passed": after[case][0]}
               for case in sorted(before) if case in after and before[case][0] != after[case][0]]
    return {"regressions": [item for item in changes if item["candidate_passed"] < item["baseline_passed"]],
            "improvements": [item for item in changes if item["candidate_passed"] > item["baseline_passed"]]}


@router.post("/metrics/compare")
def metrics_compare(request: MetricsRequest) -> dict[str, Any]:
    runs, results = _metric_context(request.run_ids)
    eligibility = _eligibility(runs, results)
    if not eligibility["eligible"]:
        raise HTTPException(status_code=409, detail=eligibility)
    reports = [_report_for(run_id, runs, results) for run_id in request.run_ids]
    return {
        "eligibility": eligibility,
        "baseline_report": reports[0],
        "candidate_report": reports[1],
        "case_changes": _case_changes(results[request.run_ids[0]], results[request.run_ids[1]]),
    }
