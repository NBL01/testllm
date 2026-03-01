from llm_reliability_analytics.models.domain import TestCase as DomainTestCase
from llm_reliability_analytics.runner.mock_client import MockLLMClient
from llm_reliability_analytics.runner.test_runner import TestRunner as BatchRunner


def test_mock_client_deterministic_mode_is_reproducible() -> None:
    client = MockLLMClient(mode="deterministic", seed=123)
    answer_a = client.generate("What is 2 + 2?")
    answer_b = client.generate("What is 2 + 2?")
    assert answer_a == answer_b
    assert answer_a == "4"


def test_test_runner_returns_result_per_case_with_latency() -> None:
    test_cases = [
        DomainTestCase(
            id="tc-001",
            category="math",
            difficulty="easy",
            prompt="What is 2 + 2?",
            expected_answer="4",
            oracle_type="exact_match",
            metadata={},
        ),
        DomainTestCase(
            id="tc-002",
            category="factual",
            difficulty="easy",
            prompt="Capital of Japan?",
            expected_answer="Tokyo",
            oracle_type="exact_match",
            metadata={},
        ),
    ]

    runner = BatchRunner(llm_client=MockLLMClient(mode="deterministic", seed=7))
    results = runner.run(test_cases, run_id="run-001")

    assert len(results) == 2
    assert all(result.run_id == "run-001" for result in results)
    assert [result.test_case_id for result in results] == ["tc-001", "tc-002"]
    assert all(result.latency_ms >= 0 for result in results)
    assert all(result.error_type is None for result in results)


def test_test_runner_supports_repeated_attempts() -> None:
    test_cases = [
        DomainTestCase(
            id="tc-repeat-1",
            category="math",
            difficulty="easy",
            prompt="What is 2 + 2?",
            expected_answer="4",
            oracle_type="exact_match",
            metadata={},
        )
    ]

    runner = BatchRunner(llm_client=MockLLMClient(mode="semi_random", seed=7))
    results = runner.run(test_cases, run_id="run-repeat-001", repeats_per_case=3)

    assert len(results) == 3
    assert all(result.run_id == "run-repeat-001" for result in results)
    assert [result.test_case_id for result in results] == ["tc-repeat-1", "tc-repeat-1", "tc-repeat-1"]
    assert [result.attempt_index for result in results] == [1, 2, 3]
