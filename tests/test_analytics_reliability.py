import pytest

from llm_reliability_analytics.analytics.reliability import (
    compute_reliability_report,
    compute_run_comparison_report,
)
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

    assert report.run_id == "run-1"
    assert report.dataset_version == "v1"
    assert report.repetition_index == 1
    assert report.total_test_cases == 3
    assert report.unique_test_cases == 3
    assert report.attempts_per_case == pytest.approx(1.0)
    assert report.passed == 2
    assert report.failed == 1
    assert report.accuracy == pytest.approx(2 / 3)
    assert report.average_latency_ms == pytest.approx(300.0)
    assert report.category_wise_accuracy["math"] == pytest.approx(0.5)
    assert report.category_wise_accuracy["factual"] == pytest.approx(1.0)
    assert report.error_distribution == {"wrong_answer": 1}
    assert report.oracle_type_pass_rate == {"unknown": pytest.approx(2 / 3)}
    assert len(report.category_reports) == 2
    assert report.p95_latency_ms == pytest.approx(500.0)
    assert report.repeatability_score == 1.0
    assert report.schema_compliance_rate == 1.0
    assert report.critical_error_rate == 0.0
    assert report.failure_density_per_1000 == pytest.approx((1 / 3) * 1000.0)
    assert report.weakest_categories[0].category == "math"
    assert report.most_frequent_error_types[0].error_type == "wrong_answer"
    assert report.run_level_report is not None
    assert report.run_level_report.run_id == "run-1"
    assert report.unstable_case_count == 0
    assert report.unstable_case_ids == []
    assert report.run_level_report.p95_latency_ms == pytest.approx(500.0)

    # Explicit formula checks for explainability
    expected_consistency = 1.0 - (((1 - (2 / 3)) ** 2 + (0 - (2 / 3)) ** 2 + (1 - (2 / 3)) ** 2) / 3) ** 0.5
    expected_latency_score = 1.0 - (300.0 / 1000.0)  # 0.7
    expected_failure_density_score = 1.0 - (((1 / 3) * 1000.0) / 1000.0)  # 2/3
    expected_overall = (
        (0.35 * (2 / 3))
        + (0.15 * expected_consistency)
        + (0.15 * 1.0)
        + (0.10 * 1.0)
        + (0.10 * (1.0 - 0.0))
        + (0.10 * expected_latency_score)
        + (0.05 * expected_failure_density_score)
    )
    assert report.consistency_score == pytest.approx(expected_consistency)
    assert report.overall_reliability_score == pytest.approx(expected_overall)


def test_compute_reliability_report_handles_empty_input() -> None:
    report = compute_reliability_report([])

    assert report.total_test_cases == 0
    assert report.unique_test_cases == 0
    assert report.attempts_per_case == 0.0
    assert report.passed == 0
    assert report.failed == 0
    assert report.accuracy == 0.0
    assert report.average_latency_ms == 0.0
    assert report.category_wise_accuracy == {}
    assert report.error_distribution == {}
    assert report.error_taxonomy_distribution == {}
    assert report.oracle_type_pass_rate == {}
    assert report.p95_latency_ms == 0.0
    assert report.consistency_score == 0.0
    assert report.repeatability_score == 0.0
    assert report.schema_compliance_rate == 0.0
    assert report.critical_error_rate == 0.0
    assert report.failure_density_per_1000 == 0.0
    assert report.overall_reliability_score == 0.0
    assert report.weakest_categories == []
    assert report.most_frequent_error_types == []
    assert report.run_level_report is not None


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


def test_compute_reliability_report_detects_unstable_cases_across_repeats() -> None:
    results = [
        DomainTestResult(
            run_id="run-repeat",
            test_case_id="tc-stable",
            attempt_index=1,
            category="factual",
            actual_answer="Paris",
            actual_answer_normalized="paris",
            is_correct=True,
            score=1.0,
            latency_ms=90.0,
            error_type=None,
        ),
        DomainTestResult(
            run_id="run-repeat",
            test_case_id="tc-stable",
            attempt_index=2,
            category="factual",
            actual_answer="Paris",
            actual_answer_normalized="paris",
            is_correct=True,
            score=1.0,
            latency_ms=100.0,
            error_type=None,
        ),
        DomainTestResult(
            run_id="run-repeat",
            test_case_id="tc-unstable",
            attempt_index=1,
            category="reasoning",
            actual_answer="42",
            actual_answer_normalized="42",
            is_correct=True,
            score=1.0,
            latency_ms=120.0,
            error_type=None,
        ),
        DomainTestResult(
            run_id="run-repeat",
            test_case_id="tc-unstable",
            attempt_index=2,
            category="reasoning",
            actual_answer="41",
            actual_answer_normalized="41",
            is_correct=False,
            score=0.0,
            latency_ms=140.0,
            error_type="wrong_answer",
        ),
    ]

    report = compute_reliability_report(results)
    assert report.total_test_cases == 4
    assert report.unique_test_cases == 2
    assert report.attempts_per_case == pytest.approx(2.0)
    assert report.unstable_case_count == 1
    assert report.unstable_case_ids == ["tc-unstable"]
    assert report.consistency_score < 1.0
    assert report.repeatability_score == pytest.approx(0.5)


def test_run_comparison_report_highlights_ranking_weaknesses_and_errors() -> None:
    run_a_results = [
        DomainTestResult(
            run_id="run-a",
            test_case_id="a-1",
            category="math",
            oracle_type="exact_match",
            actual_answer="4",
            is_correct=True,
            score=1.0,
            latency_ms=100.0,
            error_type=None,
        ),
        DomainTestResult(
            run_id="run-a",
            test_case_id="a-2",
            category="factual",
            oracle_type="regex_match",
            actual_answer="wrong",
            is_correct=False,
            score=0.0,
            latency_ms=300.0,
            error_type="wrong_answer",
        ),
    ]
    run_b_results = [
        DomainTestResult(
            run_id="run-b",
            test_case_id="b-1",
            category="math",
            oracle_type="exact_match",
            actual_answer="4",
            is_correct=True,
            score=1.0,
            latency_ms=90.0,
            error_type=None,
        ),
        DomainTestResult(
            run_id="run-b",
            test_case_id="b-2",
            category="factual",
            oracle_type="regex_match",
            actual_answer="Paris",
            is_correct=True,
            score=1.0,
            latency_ms=110.0,
            error_type=None,
        ),
    ]

    report_a = compute_reliability_report(run_a_results)
    report_b = compute_reliability_report(run_b_results)
    comparison = compute_run_comparison_report([report_a, report_b], baseline_run_id="run-a")

    assert comparison.compared_runs == 2
    assert comparison.baseline_run_id == "run-a"
    assert comparison.best_run_id == "run-b"
    assert comparison.ranking_by_reliability == ["run-b", "run-a"]
    assert "run-b" in comparison.deltas_vs_baseline
    assert comparison.weakest_categories[0].category == "factual"
    assert comparison.most_frequent_error_types[0].error_type == "wrong_answer"
