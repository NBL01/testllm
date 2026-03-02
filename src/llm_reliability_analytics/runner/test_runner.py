from time import perf_counter
from uuid import uuid4

from llm_reliability_analytics.models.domain import TestCase, TestResult
from llm_reliability_analytics.runner.llm_client import BaseLLMClient
from llm_reliability_analytics.runner.mock_client import MockLLMClient


class TestRunner:
    """Minimal runner that executes prompts and captures latency.

    Scoring is intentionally handled in the oracle layer, not here.
    """

    def __init__(self, llm_client: BaseLLMClient | None = None) -> None:
        self.llm_client = llm_client or MockLLMClient()

    def run(
        self,
        test_cases: list[TestCase],
        run_id: str | None = None,
        repeats_per_case: int = 1,
    ) -> list[TestResult]:
        if repeats_per_case < 1:
            raise ValueError("repeats_per_case must be >= 1")

        active_run_id = run_id or str(uuid4())
        results: list[TestResult] = []

        for test_case in test_cases:
            for attempt_index in range(1, repeats_per_case + 1):
                start = perf_counter()
                actual_answer: str | None = None
                error_type: str | None = None
                latency_source = "measured"
                latency_ms = 0.0

                try:
                    generation = self.llm_client.generate_with_metadata(test_case.prompt)
                    actual_answer = generation.text
                    measured_latency_ms = (perf_counter() - start) * 1000
                    if generation.latency_ms is not None:
                        latency_ms = float(generation.latency_ms)
                        latency_source = "provider_reported"
                    else:
                        latency_ms = measured_latency_ms
                except Exception as exc:  # noqa: BLE001 - demo runner should be fault tolerant
                    error_type = type(exc).__name__
                    latency_ms = (perf_counter() - start) * 1000

                results.append(
                    TestResult(
                        run_id=active_run_id,
                        test_case_id=test_case.id,
                        attempt_index=attempt_index,
                        category=test_case.category,
                        test_source=test_case.test_source.value,
                        dataset_version=test_case.dataset_version,
                        raw_output=actual_answer,
                        actual_answer=actual_answer,
                        is_correct=False,
                        score=0.0,
                        latency_ms=latency_ms,
                        latency_source=latency_source,
                        error_type=error_type,
                    )
                )

        return results
