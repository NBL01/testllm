"""Build replay datasets from captured evaluation traces."""

from __future__ import annotations

from llm_reliability_analytics.models.domain import OracleType, TestCase, TestSource
from llm_reliability_analytics.storage.trace_repository import fetch_traces


def load_trace_replay_test_cases(
    source_run_id: str,
    dataset_version: str,
    only_failed: bool = True,
    max_cases: int = 200,
) -> list[TestCase]:
    traces = fetch_traces(run_id=source_run_id, only_failed=only_failed, max_rows=max_cases)
    test_cases: list[TestCase] = []
    for trace in traces:
        oracle_value = str(trace.get("oracle_type") or "exact_match").strip().lower()
        try:
            oracle_type = OracleType(oracle_value)
        except ValueError:
            oracle_type = OracleType.EXACT_MATCH

        prompt = str(trace.get("prompt") or "").strip()
        if not prompt:
            continue

        expected_answer = str(trace.get("raw_output") or "").strip()
        if not expected_answer:
            expected_answer = str(trace.get("normalized_output") or "").strip()

        test_cases.append(
            TestCase(
                id=f"trace-replay-{trace['trace_id']}",
                test_source=TestSource.TRACE_REPLAY,
                dataset_version=dataset_version,
                category=str(trace.get("category") or "trace_replay"),
                difficulty="medium",
                prompt=prompt,
                expected_answer=expected_answer,
                oracle_type=oracle_type,
                metadata={
                    "source_trace_id": trace["trace_id"],
                    "source_run_id": source_run_id,
                    "source_error_type": trace.get("error_type"),
                    "source_score": trace.get("score"),
                },
            )
        )
    return test_cases
