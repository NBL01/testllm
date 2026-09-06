"""Build replay datasets from captured evaluation traces."""

from __future__ import annotations

from copy import deepcopy

from llm_reliability_analytics.models.domain import OracleType, TestCase, TestSource
from llm_reliability_analytics.storage.trace_repository import fetch_traces


class TraceReplayReviewRequiredError(ValueError):
    """Replay needs reviewed original evidence, never an inferred model answer."""


def load_trace_replay_test_cases(
    source_run_id: str,
    dataset_version: str,
    only_failed: bool = True,
    max_cases: int = 200,
) -> list[TestCase]:
    traces = fetch_traces(run_id=source_run_id, only_failed=only_failed, max_rows=max_cases)
    test_cases: list[TestCase] = []
    for trace in traces:
        review_message = f"Review required for trace {trace['trace_id']}: "
        oracle_value = str(trace.get("oracle_type") or "").strip().lower()
        try:
            oracle_type = OracleType(oracle_value)
        except ValueError as exc:
            raise TraceReplayReviewRequiredError(
                review_message + "missing or unsupported original oracle_type."
            ) from exc

        prompt = trace.get("prompt")
        if not isinstance(prompt, str) or not prompt.strip():
            raise TraceReplayReviewRequiredError(review_message + "missing original prompt.")

        expected_answer = trace.get("expected_answer")
        if not isinstance(expected_answer, str):
            raise TraceReplayReviewRequiredError(
                review_message + "missing expected_answer snapshot; supply reviewed original evidence."
            )
        config = trace.get("oracle_config")
        if not isinstance(config, dict):
            raise TraceReplayReviewRequiredError(
                review_message + "missing oracle input_config snapshot; supply reviewed original configuration."
            )

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
                    **deepcopy(config),
                    "source_trace_id": trace["trace_id"],
                    "source_run_id": source_run_id,
                    "source_error_type": trace.get("error_type"),
                    "source_score": trace.get("score"),
                },
            )
        )
    return test_cases
