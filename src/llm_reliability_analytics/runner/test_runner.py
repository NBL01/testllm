from time import perf_counter
from uuid import uuid4

from llm_reliability_analytics.models.domain import TestCase, TestResult
from llm_reliability_analytics.runner.mock_client import MockLLMClient


class TestRunner:
    """Minimal runner that executes prompts and captures latency.

    Scoring is intentionally handled in the oracle layer, not here.
    """

    def __init__(self, llm_client: MockLLMClient | None = None) -> None:
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

                try:
                    actual_answer = self.llm_client.generate(test_case.prompt)
                except Exception as exc:  # noqa: BLE001 - demo runner should be fault tolerant
                    error_type = type(exc).__name__

                latency_ms = (perf_counter() - start) * 1000
                results.append(
                    TestResult(
                        run_id=active_run_id,
                        test_case_id=test_case.id,
                        attempt_index=attempt_index,
                        category=test_case.category,
                        dataset_version=test_case.dataset_version,
                        actual_answer=actual_answer,
                        is_correct=False,
                        score=0.0,
                        latency_ms=latency_ms,
                        error_type=error_type,
                    )
                )

        return results
