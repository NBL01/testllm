from collections import Counter, defaultdict
from math import ceil

from pydantic import BaseModel, Field

from llm_reliability_analytics.analytics.coverage_metrics import compute_coverage_metrics
from llm_reliability_analytics.models.domain import (
    CategoryLevelReport,
    ErrorTaxonomy,
    RunLevelReport,
    TestResult,
)


class WeakCategorySummary(BaseModel):
    category: str
    accuracy: float = Field(ge=0.0, le=1.0)
    failed: int = Field(ge=0)
    total_test_cases: int = Field(ge=0)


class FrequentErrorTypeSummary(BaseModel):
    error_type: str
    count: int = Field(ge=0)
    rate: float = Field(ge=0.0, le=1.0)


class RunComparisonItem(BaseModel):
    run_id: str
    dataset_version: str = "v1"
    repetition_index: int = Field(default=1, ge=1)
    accuracy: float = Field(ge=0.0, le=1.0)
    overall_reliability_score: float = Field(ge=0.0, le=1.0)
    average_latency_ms: float = Field(ge=0.0)
    p95_latency_ms: float = Field(ge=0.0)
    consistency_score: float = Field(ge=0.0, le=1.0)
    repeatability_score: float = Field(ge=0.0, le=1.0)
    schema_compliance_rate: float = Field(ge=0.0, le=1.0)
    critical_error_rate: float = Field(ge=0.0, le=1.0)
    failure_density_per_1000: float = Field(ge=0.0)


class RunComparisonReport(BaseModel):
    compared_runs: int = Field(ge=0)
    baseline_run_id: str = ""
    best_run_id: str | None = None
    ranking_by_reliability: list[str] = Field(default_factory=list)
    runs: list[RunComparisonItem] = Field(default_factory=list)
    deltas_vs_baseline: dict[str, dict[str, float]] = Field(default_factory=dict)
    weakest_categories: list[WeakCategorySummary] = Field(default_factory=list)
    most_frequent_error_types: list[FrequentErrorTypeSummary] = Field(default_factory=list)


class ReliabilityReport(BaseModel):
    run_id: str = "unknown-run"
    dataset_version: str = "v1"
    repetition_index: int = Field(default=1, ge=1)
    total_test_cases: int = Field(ge=0)
    unique_test_cases: int = Field(default=0, ge=0)
    attempts_per_case: float = Field(default=1.0, ge=0.0)
    passed: int = Field(ge=0)
    failed: int = Field(ge=0)
    accuracy: float = Field(ge=0.0, le=1.0)
    average_latency_ms: float = Field(ge=0.0)
    p95_latency_ms: float = Field(default=0.0, ge=0.0)
    category_reports: list[CategoryLevelReport] = Field(default_factory=list)
    category_wise_accuracy: dict[str, float] = Field(default_factory=dict)
    oracle_type_pass_rate: dict[str, float] = Field(default_factory=dict)
    error_distribution: dict[str, int] = Field(default_factory=dict)
    error_taxonomy_distribution: dict[str, int] = Field(default_factory=dict)
    consistency_score: float = Field(ge=0.0, le=1.0)
    repeatability_score: float = Field(default=0.0, ge=0.0, le=1.0)
    schema_compliance_rate: float = Field(default=0.0, ge=0.0, le=1.0)
    critical_error_rate: float = Field(default=0.0, ge=0.0, le=1.0)
    failure_density_per_1000: float = Field(default=0.0, ge=0.0)
    category_coverage: float = Field(default=0.0, ge=0.0, le=1.0)
    source_coverage: int = Field(default=0, ge=0)
    failure_concentration: float = Field(default=0.0, ge=0.0, le=1.0)
    zero_score_categories: int = Field(default=0, ge=0)
    low_score_cases: int = Field(default=0, ge=0)
    source_distribution: dict[str, int] = Field(default_factory=dict)
    failure_by_source: dict[str, int] = Field(default_factory=dict)
    unstable_case_count: int = Field(default=0, ge=0)
    unstable_case_ids: list[str] = Field(default_factory=list)
    weakest_categories: list[WeakCategorySummary] = Field(default_factory=list)
    most_frequent_error_types: list[FrequentErrorTypeSummary] = Field(default_factory=list)
    overall_reliability_score: float = Field(ge=0.0, le=1.0)
    run_level_report: RunLevelReport | None = None


def compute_reliability_report(
    results: list[TestResult],
    run_id: str | None = None,
    dataset_version: str | None = None,
    repetition_index: int | None = None,
    latency_slo_ms: float = 1000.0,
    low_score_threshold: float = 0.3,
) -> ReliabilityReport:
    """Compute reliability analytics from a list of TestResult objects.

    Explicit formulas:
    - total_test_cases = len(results)
    - unique_test_cases = count(unique test_case_id)
    - attempts_per_case = total_test_cases / unique_test_cases
    - passed = count(is_correct == True)
    - failed = total_test_cases - passed
    - accuracy = passed / total_test_cases
    - average_latency_ms = mean(latency_ms)
    - p95_latency_ms = nearest-rank percentile (95th)
    - category_accuracy = passed_in_category / total_in_category
    - oracle_type_pass_rate = passed_for_oracle / total_for_oracle
    - consistency_score = mean(case_consistency)
      case_consistency = 0.5 * answer_consistency + 0.5 * score_consistency
      answer_consistency = 1 / unique_normalized_answers
      score_consistency = max(0, 1 - stddev(case_scores))
    - repeatability_score = mean(case_repeatable)
      case_repeatable = 1 if all answers and correctness labels are stable across repeats else 0
    - schema_compliance_rate = compliant_cases / total_test_cases
      compliant_cases exclude parsing/validation/schema-json errors
    - critical_error_rate = critical_errors / total_test_cases
      critical_errors include timeout/runtime/oracle/unknown taxonomy
    - failure_density_per_1000 = (failed / total_test_cases) * 1000
    - overall_reliability_score =
      0.35*accuracy +
      0.15*consistency_score +
      0.15*repeatability_score +
      0.10*schema_compliance_rate +
      0.10*(1-critical_error_rate) +
      0.10*latency_score +
      0.05*(1-failure_density_per_1000/1000)
    """
    total_test_cases = len(results)
    resolved_run_id = run_id or (results[0].run_id if results else "unknown-run")
    resolved_dataset_version = dataset_version or (results[0].dataset_version if results else "v1") or "v1"
    resolved_repetition_index = repetition_index or 1

    if total_test_cases == 0:
        return _empty_report(
            run_id=resolved_run_id,
            dataset_version=resolved_dataset_version,
            repetition_index=resolved_repetition_index,
        )

    unique_test_cases = len({result.test_case_id for result in results})
    attempts_per_case = (total_test_cases / unique_test_cases) if unique_test_cases else 0.0

    passed = sum(1 for result in results if result.is_correct)
    failed = total_test_cases - passed

    accuracy = passed / total_test_cases
    latencies = [result.latency_ms for result in results]
    average_latency_ms = sum(latencies) / total_test_cases
    p95_latency_ms = _compute_p95(latencies)

    category_reports = _compute_category_reports(results)
    category_wise_accuracy = {report.category: report.accuracy for report in category_reports}
    oracle_type_pass_rate = _compute_oracle_type_pass_rates(results)

    error_distribution = dict(Counter(result.error_type for result in results if result.error_type))
    error_taxonomy_distribution = dict(
        Counter(
            result.error_taxonomy.value
            for result in results
            if result.error_taxonomy != ErrorTaxonomy.NONE
        )
    )

    consistency_score, unstable_case_ids = _compute_consistency_and_instability(results)
    repeatability_score = _compute_repeatability_score(results)
    schema_compliance_rate = _compute_schema_compliance_rate(results)
    critical_error_rate = _compute_critical_error_rate(results)
    failure_density_per_1000 = (failed / total_test_cases) * 1000.0
    coverage_metrics = compute_coverage_metrics(results=results, low_score_threshold=low_score_threshold)

    latency_score = _compute_latency_score(average_latency_ms=average_latency_ms, latency_slo_ms=latency_slo_ms)
    failure_density_score = _clamp01(1.0 - (failure_density_per_1000 / 1000.0))

    overall_reliability_score = _clamp01(
        (0.35 * accuracy)
        + (0.15 * consistency_score)
        + (0.15 * repeatability_score)
        + (0.10 * schema_compliance_rate)
        + (0.10 * (1.0 - critical_error_rate))
        + (0.10 * latency_score)
        + (0.05 * failure_density_score)
    )

    weakest_categories = _compute_weakest_categories(category_reports)
    most_frequent_error_types = _compute_most_frequent_error_types(error_distribution, total_test_cases)

    run_level_report = RunLevelReport(
        run_id=resolved_run_id,
        dataset_version=resolved_dataset_version,
        repetition_index=resolved_repetition_index,
        total_test_cases=total_test_cases,
        unique_test_cases=unique_test_cases,
        attempts_per_case=attempts_per_case,
        passed=passed,
        failed=failed,
        accuracy=accuracy,
        average_latency_ms=average_latency_ms,
        p95_latency_ms=p95_latency_ms,
        consistency_score=consistency_score,
        repeatability_score=repeatability_score,
        schema_compliance_rate=schema_compliance_rate,
        critical_error_rate=critical_error_rate,
        failure_density_per_1000=failure_density_per_1000,
        category_coverage=coverage_metrics.category_coverage,
        source_coverage=coverage_metrics.source_coverage,
        failure_concentration=coverage_metrics.failure_concentration,
        zero_score_categories=coverage_metrics.zero_score_categories,
        low_score_cases=coverage_metrics.low_score_cases,
        unstable_case_count=len(unstable_case_ids),
        error_taxonomy_distribution=error_taxonomy_distribution,
    )

    return ReliabilityReport(
        run_id=resolved_run_id,
        dataset_version=resolved_dataset_version,
        repetition_index=resolved_repetition_index,
        total_test_cases=total_test_cases,
        unique_test_cases=unique_test_cases,
        attempts_per_case=attempts_per_case,
        passed=passed,
        failed=failed,
        accuracy=accuracy,
        average_latency_ms=average_latency_ms,
        p95_latency_ms=p95_latency_ms,
        category_reports=category_reports,
        category_wise_accuracy=category_wise_accuracy,
        oracle_type_pass_rate=oracle_type_pass_rate,
        error_distribution=error_distribution,
        error_taxonomy_distribution=error_taxonomy_distribution,
        consistency_score=consistency_score,
        repeatability_score=repeatability_score,
        schema_compliance_rate=schema_compliance_rate,
        critical_error_rate=critical_error_rate,
        failure_density_per_1000=failure_density_per_1000,
        category_coverage=coverage_metrics.category_coverage,
        source_coverage=coverage_metrics.source_coverage,
        failure_concentration=coverage_metrics.failure_concentration,
        zero_score_categories=coverage_metrics.zero_score_categories,
        low_score_cases=coverage_metrics.low_score_cases,
        source_distribution=coverage_metrics.source_distribution,
        failure_by_source=coverage_metrics.failure_by_source,
        unstable_case_count=len(unstable_case_ids),
        unstable_case_ids=unstable_case_ids,
        weakest_categories=weakest_categories,
        most_frequent_error_types=most_frequent_error_types,
        overall_reliability_score=overall_reliability_score,
        run_level_report=run_level_report,
    )


def compute_run_comparison_report(
    reports: list[ReliabilityReport],
    baseline_run_id: str | None = None,
    top_k: int = 3,
) -> RunComparisonReport:
    """Compare multiple runs with explicit deltas to a baseline run.

    Formulas:
    - delta(metric) = run.metric - baseline.metric
    - weakest category across runs = min aggregated category accuracy
    - most frequent error type = max aggregated error count
    """
    if not reports:
        return RunComparisonReport(compared_runs=0)

    baseline = next((r for r in reports if r.run_id == baseline_run_id), reports[0])
    ranking = sorted(reports, key=lambda r: r.overall_reliability_score, reverse=True)
    items = [
        RunComparisonItem(
            run_id=report.run_id,
            dataset_version=report.dataset_version,
            repetition_index=report.repetition_index,
            accuracy=report.accuracy,
            overall_reliability_score=report.overall_reliability_score,
            average_latency_ms=report.average_latency_ms,
            p95_latency_ms=report.p95_latency_ms,
            consistency_score=report.consistency_score,
            repeatability_score=report.repeatability_score,
            schema_compliance_rate=report.schema_compliance_rate,
            critical_error_rate=report.critical_error_rate,
            failure_density_per_1000=report.failure_density_per_1000,
        )
        for report in reports
    ]

    deltas_vs_baseline: dict[str, dict[str, float]] = {}
    for report in reports:
        if report.run_id == baseline.run_id:
            continue
        deltas_vs_baseline[report.run_id] = {
            "accuracy_delta": report.accuracy - baseline.accuracy,
            "overall_reliability_score_delta": report.overall_reliability_score - baseline.overall_reliability_score,
            "average_latency_ms_delta": report.average_latency_ms - baseline.average_latency_ms,
            "critical_error_rate_delta": report.critical_error_rate - baseline.critical_error_rate,
        }

    weakest_categories = _aggregate_weakest_categories_across_runs(reports, top_k=top_k)
    most_frequent_error_types = _aggregate_most_frequent_error_types_across_runs(reports, top_k=top_k)

    return RunComparisonReport(
        compared_runs=len(reports),
        baseline_run_id=baseline.run_id,
        best_run_id=ranking[0].run_id,
        ranking_by_reliability=[report.run_id for report in ranking],
        runs=items,
        deltas_vs_baseline=deltas_vs_baseline,
        weakest_categories=weakest_categories,
        most_frequent_error_types=most_frequent_error_types,
    )


def _empty_report(run_id: str, dataset_version: str, repetition_index: int) -> ReliabilityReport:
    run_level_report = RunLevelReport(
        run_id=run_id,
        dataset_version=dataset_version,
        repetition_index=repetition_index,
        total_test_cases=0,
        unique_test_cases=0,
        attempts_per_case=0.0,
        passed=0,
        failed=0,
        accuracy=0.0,
        average_latency_ms=0.0,
        p95_latency_ms=0.0,
        consistency_score=0.0,
        repeatability_score=0.0,
        schema_compliance_rate=0.0,
        critical_error_rate=0.0,
        failure_density_per_1000=0.0,
        category_coverage=0.0,
        source_coverage=0,
        failure_concentration=0.0,
        zero_score_categories=0,
        low_score_cases=0,
        unstable_case_count=0,
        error_taxonomy_distribution={},
    )
    return ReliabilityReport(
        run_id=run_id,
        dataset_version=dataset_version,
        repetition_index=repetition_index,
        total_test_cases=0,
        unique_test_cases=0,
        attempts_per_case=0.0,
        passed=0,
        failed=0,
        accuracy=0.0,
        average_latency_ms=0.0,
        p95_latency_ms=0.0,
        category_reports=[],
        category_wise_accuracy={},
        oracle_type_pass_rate={},
        error_distribution={},
        error_taxonomy_distribution={},
        consistency_score=0.0,
        repeatability_score=0.0,
        schema_compliance_rate=0.0,
        critical_error_rate=0.0,
        failure_density_per_1000=0.0,
        category_coverage=0.0,
        source_coverage=0,
        failure_concentration=0.0,
        zero_score_categories=0,
        low_score_cases=0,
        source_distribution={},
        failure_by_source={},
        unstable_case_count=0,
        unstable_case_ids=[],
        weakest_categories=[],
        most_frequent_error_types=[],
        overall_reliability_score=0.0,
        run_level_report=run_level_report,
    )


def _compute_category_reports(results: list[TestResult]) -> list[CategoryLevelReport]:
    grouped: dict[str, list[TestResult]] = defaultdict(list)

    for result in results:
        category = result.category or "unknown"
        grouped[category].append(result)

    reports: list[CategoryLevelReport] = []
    for category, category_results in sorted(grouped.items()):
        total_test_cases = len(category_results)
        passed = sum(1 for result in category_results if result.is_correct)
        failed = total_test_cases - passed
        average_latency_ms = (
            sum(result.latency_ms for result in category_results) / total_test_cases
            if total_test_cases
            else 0.0
        )
        reports.append(
            CategoryLevelReport(
                category=category,
                total_test_cases=total_test_cases,
                passed=passed,
                failed=failed,
                accuracy=(passed / total_test_cases) if total_test_cases else 0.0,
                average_latency_ms=average_latency_ms,
            )
        )
    return reports


def _compute_oracle_type_pass_rates(results: list[TestResult]) -> dict[str, float]:
    grouped: dict[str, list[TestResult]] = defaultdict(list)
    for result in results:
        oracle_type = result.oracle_type or "unknown"
        grouped[oracle_type].append(result)

    pass_rates: dict[str, float] = {}
    for oracle_type, oracle_results in sorted(grouped.items()):
        total = len(oracle_results)
        passed = sum(1 for result in oracle_results if result.is_correct)
        pass_rates[oracle_type] = (passed / total) if total else 0.0
    return pass_rates


def _compute_consistency_and_instability(
    results: list[TestResult], unstable_threshold: float = 0.75
) -> tuple[float, list[str]]:
    if not results:
        return 0.0, []

    grouped: dict[str, list[TestResult]] = defaultdict(list)
    for result in results:
        grouped[result.test_case_id].append(result)

    max_attempts = max(len(case_results) for case_results in grouped.values())
    if max_attempts <= 1:
        return _compute_score_variance_consistency(results), []

    case_consistency_scores: list[float] = []
    unstable_case_ids: list[str] = []

    for test_case_id, case_results in sorted(grouped.items()):
        normalized_answers = [
            (result.actual_answer_normalized or (result.actual_answer or "").strip().lower())
            for result in case_results
        ]
        non_empty_answers = [answer for answer in normalized_answers if answer]
        unique_answers = len(set(non_empty_answers)) if non_empty_answers else 1
        answer_consistency = _clamp01(1.0 / unique_answers)

        score_consistency = _compute_score_variance_consistency(case_results)
        case_consistency = _clamp01((0.5 * answer_consistency) + (0.5 * score_consistency))
        case_consistency_scores.append(case_consistency)

        if case_consistency < unstable_threshold:
            unstable_case_ids.append(test_case_id)

    overall_consistency = (
        sum(case_consistency_scores) / len(case_consistency_scores)
        if case_consistency_scores
        else 0.0
    )
    return _clamp01(overall_consistency), unstable_case_ids


def _compute_repeatability_score(results: list[TestResult]) -> float:
    if not results:
        return 0.0

    grouped: dict[str, list[TestResult]] = defaultdict(list)
    for result in results:
        grouped[result.test_case_id].append(result)

    max_attempts = max(len(case_results) for case_results in grouped.values())
    if max_attempts <= 1:
        return 1.0

    repeatable_cases = 0
    for case_results in grouped.values():
        normalized_answers = {
            result.actual_answer_normalized or (result.actual_answer or "").strip().lower()
            for result in case_results
        }
        correctness_labels = {result.is_correct for result in case_results}
        if len(normalized_answers) <= 1 and len(correctness_labels) <= 1:
            repeatable_cases += 1

    return _clamp01(repeatable_cases / len(grouped))


def _compute_schema_compliance_rate(results: list[TestResult]) -> float:
    if not results:
        return 0.0

    compliant = sum(1 for result in results if _is_schema_compliant(result))
    return _clamp01(compliant / len(results))


def _is_schema_compliant(result: TestResult) -> bool:
    if result.error_taxonomy in {ErrorTaxonomy.VALIDATION, ErrorTaxonomy.PARSING}:
        return False

    if not result.error_type:
        return True

    normalized_error = result.error_type.strip().lower()
    schema_error_tokens = ("schema", "json", "validation", "parse")
    return not any(token in normalized_error for token in schema_error_tokens)


def _compute_critical_error_rate(results: list[TestResult]) -> float:
    if not results:
        return 0.0

    critical_taxonomies = {
        ErrorTaxonomy.TIMEOUT,
        ErrorTaxonomy.RUNTIME,
        ErrorTaxonomy.ORACLE,
        ErrorTaxonomy.UNKNOWN,
    }
    critical_errors = sum(1 for result in results if result.error_taxonomy in critical_taxonomies)
    return _clamp01(critical_errors / len(results))


def _compute_weakest_categories(
    category_reports: list[CategoryLevelReport], top_k: int = 3
) -> list[WeakCategorySummary]:
    ordered = sorted(
        category_reports,
        key=lambda report: (report.accuracy, -report.failed, -report.total_test_cases, report.category),
    )
    return [
        WeakCategorySummary(
            category=report.category,
            accuracy=report.accuracy,
            failed=report.failed,
            total_test_cases=report.total_test_cases,
        )
        for report in ordered[:top_k]
    ]


def _compute_most_frequent_error_types(
    error_distribution: dict[str, int], total_test_cases: int, top_k: int = 3
) -> list[FrequentErrorTypeSummary]:
    if not error_distribution or total_test_cases == 0:
        return []

    ordered = sorted(error_distribution.items(), key=lambda item: (-item[1], item[0]))
    return [
        FrequentErrorTypeSummary(
            error_type=error_type,
            count=count,
            rate=_clamp01(count / total_test_cases),
        )
        for error_type, count in ordered[:top_k]
    ]


def _aggregate_weakest_categories_across_runs(
    reports: list[ReliabilityReport], top_k: int = 3
) -> list[WeakCategorySummary]:
    category_totals: dict[str, tuple[int, int]] = defaultdict(lambda: (0, 0))

    for report in reports:
        for category_report in report.category_reports:
            passed_total, case_total = category_totals[category_report.category]
            category_totals[category_report.category] = (
                passed_total + category_report.passed,
                case_total + category_report.total_test_cases,
            )

    summaries: list[WeakCategorySummary] = []
    for category, (passed_total, case_total) in category_totals.items():
        failed_total = case_total - passed_total
        accuracy = (passed_total / case_total) if case_total else 0.0
        summaries.append(
            WeakCategorySummary(
                category=category,
                accuracy=accuracy,
                failed=failed_total,
                total_test_cases=case_total,
            )
        )

    return sorted(
        summaries,
        key=lambda summary: (summary.accuracy, -summary.failed, -summary.total_test_cases, summary.category),
    )[:top_k]


def _aggregate_most_frequent_error_types_across_runs(
    reports: list[ReliabilityReport], top_k: int = 3
) -> list[FrequentErrorTypeSummary]:
    combined_counts: Counter[str] = Counter()
    total_test_cases = sum(report.total_test_cases for report in reports)

    for report in reports:
        combined_counts.update(report.error_distribution)

    if total_test_cases == 0 or not combined_counts:
        return []

    ordered = sorted(combined_counts.items(), key=lambda item: (-item[1], item[0]))
    return [
        FrequentErrorTypeSummary(
            error_type=error_type,
            count=count,
            rate=_clamp01(count / total_test_cases),
        )
        for error_type, count in ordered[:top_k]
    ]


def _compute_score_variance_consistency(results: list[TestResult]) -> float:
    if not results:
        return 0.0
    scores = [result.score for result in results]
    mean_score = sum(scores) / len(scores)
    variance = sum((score - mean_score) ** 2 for score in scores) / len(scores)
    return _clamp01(1.0 - (variance**0.5))


def _compute_latency_score(average_latency_ms: float, latency_slo_ms: float) -> float:
    if latency_slo_ms <= 0:
        return 0.0
    return _clamp01(1.0 - (average_latency_ms / latency_slo_ms))


def _compute_p95(values: list[float]) -> float:
    if not values:
        return 0.0
    sorted_values = sorted(values)
    rank = max(1, ceil(0.95 * len(sorted_values)))
    return float(sorted_values[rank - 1])


def _clamp01(value: float) -> float:
    return max(0.0, min(1.0, value))
