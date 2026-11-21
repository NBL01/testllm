import pytest

from llm_reliability_analytics.analytics.reliability import compute_reliability_report
from llm_reliability_analytics.models.domain import TestResult as DomainTestResult


def _result(case: str, category: str | None, correct: bool, latency: float, error: str | None = None) -> DomainTestResult:
    return DomainTestResult(run_id="run-1", test_case_id=case, category=category, actual_answer="x", is_correct=correct,
                            score=float(correct), latency_ms=latency, error_type=error)


def test_compute_reliability_report_core_metrics() -> None:
    report = compute_reliability_report([
        _result("tc-1", "math", True, 100.0),
        _result("tc-2", "math", False, 300.0, "wrong_answer"),
        _result("tc-3", "factual", True, 500.0),
    ])
    assert (report.run_id, report.dataset_version) == ("run-1", "v1")
    assert (report.total_test_cases, report.unique_test_cases, report.passed, report.failed) == (3, 3, 2, 1)
    assert report.accuracy == pytest.approx(2 / 3)
    assert report.average_latency_ms == pytest.approx(300.0)
    assert (report.p50_latency_ms, report.p95_latency_ms) == (300.0, 500.0)
    assert {item.category: item.accuracy for item in report.category_reports} == {"factual": 1.0, "math": 0.5}
    assert report.error_distribution == {"wrong_answer": 1}
    assert report.oracle_type_pass_rate == {"unknown": pytest.approx(2 / 3)}
    assert report.repeat_k is None and report.schema_pass_rate is None  # single attempts, no schema cases


def test_compute_reliability_report_handles_empty_input() -> None:
    report = compute_reliability_report([])
    assert (report.total_test_cases, report.unique_test_cases, report.passed, report.failed) == (0, 0, 0, 0)
    assert report.accuracy == 0.0 and report.category_reports == [] and report.error_distribution == {}
    assert report.measurement_notes == ["No attempts were recorded for this run."]


def test_compute_reliability_report_uses_unknown_category_when_missing() -> None:
    report = compute_reliability_report([_result("tc-10", None, True, 50.0)])
    assert [(item.category, item.accuracy) for item in report.category_reports] == [("unknown", 1.0)]


def test_measurement_notes_explain_what_is_not_measured() -> None:
    notes = compute_reliability_report([_result("a", "math", True, 1.0).model_copy(update={"latency_source": "mock_simulated"})]).measurement_notes
    assert any("pass@k and pass^k need the same number of attempts" in note for note in notes)
    assert any("schema-only pass rate is not measured" in note for note in notes)
    assert any("Mock latency is simulated" in note for note in notes)


def _attempt(case: str, attempt: int, ok: bool, latency: float, oracle: str = "exact_match") -> DomainTestResult:
    return DomainTestResult(run_id="run-k", test_case_id=case, attempt_index=attempt, category="math", actual_answer="x",
                            is_correct=ok, score=float(ok), latency_ms=latency, error_type=None if ok else "wrong_answer",
                            oracle_type=oracle)


def test_pass_at_k_and_pass_hat_k_are_per_case_and_only_for_uniform_repeats() -> None:
    results = [_attempt("a", i, True, 10.0 * i) for i in (1, 2, 3)]             # always passes
    results += [_attempt("b", i, i == 2, 50.0) for i in (1, 2, 3)]              # flaky: 1 of 3
    results += [_attempt("s", i, i != 3, 5.0, "json_schema") for i in (1, 2, 3)]  # schema: 2 of 3
    report = compute_reliability_report(results, run_id="run-k")
    assert report.repeat_k == 3
    assert report.pass_at_k == pytest.approx(1.0)        # every case passed at least once
    assert report.pass_hat_k == pytest.approx(1 / 3)     # only "a" passed all three
    assert report.schema_pass_rate == pytest.approx(2 / 3)
    assert report.p50_latency_ms == 20.0 and report.p95_latency_ms == 50.0  # nearest rank over 9 attempts

    single = compute_reliability_report([_attempt("a", 1, True, 1.0), _attempt("b", 1, False, 1.0)], run_id="run-1")
    assert (single.repeat_k, single.pass_at_k, single.pass_hat_k, single.schema_pass_rate) == (None, None, None, None)
    partial = compute_reliability_report(results[:5], run_id="run-p")   # "b" has only 2 attempts
    assert partial.pass_hat_k is None
