import pytest

from llm_reliability_analytics.analytics.reliability import compute_reliability_report
from llm_reliability_analytics.models.domain import TestResult as Result


def attempt(case="case", index=1, **updates):
    return Result(**(dict(run_id="run", test_case_id=case, attempt_index=index,
                         actual_answer="wrong", is_correct=False, score=0,
                         latency_ms=0, latency_source="mock_simulated") | updates))


def test_single_attempt_preserves_legacy_score_but_discloses_unmeasured_scope():
    report = compute_reliability_report([attempt()])
    assert report.overall_reliability_score == pytest.approx(0.6)
    assert report.repeatability_score == 1
    assert report.schema_compliance_rate == 1
    assert report.metric_version == "legacy-v1"
    assert report.repeated_case_count == 0
    assert report.schema_case_count == 0
    assert report.schema_attempt_count == 0
    assert report.latency_sources == {"mock_simulated": 1}
    notes = " ".join(report.measurement_notes).lower()
    for text in ["not measured", "single-attempt", "across different cases", "0.40", "all attempts", "exact_match", "lenient"]:
        assert text in notes
    assert report.model_dump()["metric_version"] == "legacy-v1"


def test_mixed_repeat_and_schema_scope_counts_cases_separately_from_attempts():
    results = [attempt("schema", i, oracle_type="json_schema") for i in (1, 2, 3)]
    results += [attempt("single", latency_source="observed")]
    report = compute_reliability_report(results)
    assert report.total_test_cases == 4
    assert report.unique_test_cases == 2
    assert report.repeated_case_count == 1
    assert report.schema_case_count == 1
    assert report.schema_attempt_count == 3
    assert report.latency_sources == {"mock_simulated": 3, "observed": 1}
    assert "singleton" in " ".join(report.measurement_notes).lower()


def test_empty_report_has_explicit_unmeasured_scope():
    report = compute_reliability_report([])
    assert report.metric_version == "legacy-v1"
    assert report.repeated_case_count == report.schema_case_count == report.schema_attempt_count == 0
    assert report.latency_sources == {}
    assert "no attempts" in " ".join(report.measurement_notes).lower()
