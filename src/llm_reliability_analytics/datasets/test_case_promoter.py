"""Promote failed traces into curated reusable test cases."""

from __future__ import annotations

from llm_reliability_analytics.models.domain import OracleType, TestCase, TestSource
from llm_reliability_analytics.storage.duckdb_store import upsert_test_cases
from llm_reliability_analytics.storage.trace_repository import fetch_traces


def promote_traces_to_test_cases(
    trace_ids: list[str],
    target_source: TestSource,
    dataset_version: str,
) -> int:
    if not trace_ids:
        return 0

    traces = fetch_traces(max_rows=5000)
    trace_lookup = {str(trace["trace_id"]): trace for trace in traces}
    to_promote: list[TestCase] = []

    for trace_id in trace_ids:
        trace = trace_lookup.get(str(trace_id))
        if trace is None:
            continue

        oracle_value = str(trace.get("oracle_type") or "exact_match").strip().lower()
        try:
            oracle_type = OracleType(oracle_value)
        except ValueError:
            oracle_type = OracleType.EXACT_MATCH

        prompt = str(trace.get("prompt") or "").strip()
        if not prompt:
            continue

        expected_answer = str(trace.get("raw_output") or "").strip() or str(trace.get("normalized_output") or "")

        to_promote.append(
            TestCase(
                id=f"promoted-{trace_id}",
                test_source=target_source,
                dataset_version=dataset_version,
                category=str(trace.get("category") or "promoted"),
                difficulty="medium",
                prompt=prompt,
                expected_answer=expected_answer,
                oracle_type=oracle_type,
                metadata={
                    "promoted_from_trace_id": trace_id,
                    "promoted_from_run_id": trace.get("run_id"),
                    "original_error_type": trace.get("error_type"),
                    "original_score": trace.get("score"),
                },
            )
        )

    return upsert_test_cases(to_promote)
