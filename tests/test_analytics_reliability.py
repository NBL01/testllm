import pytest

from llm_reliability_analytics.analytics.reliability import compute_reliability_report
from llm_reliability_analytics.models.domain import TestResult as DomainTestResult


def test_compute_reliability_report_core_metrics() -> None:
    results = [
        DomainTestResult(
            run_id="run-1",
            test_case_id="tc-1",
            category="math",
            actual_answer="4",
            is_correct=True,
            score=1.0,
            latency_ms=100.0,
            error_type=None,
        ),
        DomainTestResult(
            run_id="run-1",
            test_case_id="tc-2",
            category="math",
            actual_answer="5",
            is_correct=False,
            score=0.0,
            latency_ms=300.0,
            error_type="wrong_answer",
        ),
        DomainTestResult(
            run_id="run-1",
            test_case_id="tc-3",
            category="factual",
            actual_answer="Tokyo",
            is_correct=True,
            score=1.0,
            latency_ms=500.0,
            error_type=None,
        ),
    ]

    report = compute_reliability_report(results, latency_slo_ms=1000.0)

    assert report.total_test_cases == 3
    assert report.passed == 2
    assert report.failed == 1
    assert report.accuracy == pytest.approx(2 / 3)
    assert report.average_latency_ms == pytest.approx(300.0)
    assert report.category_wise_accuracy["math"] == pytest.approx(0.5)
    assert report.category_wise_accuracy["factual"] == pytest.approx(1.0)
    assert report.error_distribution == {"wrong_answer": 1}

    # Explicit formula checks for explainability
    expected_consistency = 1.0 - (((1 - (2 / 3)) ** 2 + (0 - (2 / 3)) ** 2 + (1 - (2 / 3)) ** 2) / 3) ** 0.5
    expected_latency_score = 1.0 - (300.0 / 1000.0)
    expected_overall = (0.6 * (2 / 3)) + (0.3 * expected_consistency) + (0.1 * expected_latency_score)
    assert report.consistency_score == pytest.approx(expected_consistency)
    assert report.overall_reliability_score == pytest.approx(expected_overall)


def test_compute_reliability_report_handles_empty_input() -> None:
    report = compute_reliability_report([])

    assert report.total_test_cases == 0
    assert report.passed == 0
    assert report.failed == 0
    assert report.accuracy == 0.0
    assert report.average_latency_ms == 0.0
    assert report.category_wise_accuracy == {}
    assert report.error_distribution == {}
    assert report.consistency_score == 0.0
    assert report.overall_reliability_score == 0.0


def test_compute_reliability_report_uses_unknown_category_when_missing() -> None:
    results = [
        DomainTestResult(
            run_id="run-2",
            test_case_id="tc-10",
            category=None,
            actual_answer="demo",
            is_correct=True,
            score=0.8,
            latency_ms=50.0,
            error_type=None,
        )
    ]
    report = compute_reliability_report(results)
    assert report.category_wise_accuracy == {"unknown": 1.0}
