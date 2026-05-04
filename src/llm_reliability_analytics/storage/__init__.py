"""Persistence module."""

from llm_reliability_analytics.storage.duckdb_store import (
    RunAggregatedSummary,
    create_test_run,
    fetch_results_for_run,
    fetch_aggregated_summaries,
    initialize_storage_schema,
    insert_batch_results,
    insert_test_cases,
    upsert_test_cases,
)
from llm_reliability_analytics.storage.candidate_repository import (
    CandidateReviewEvent,
    get_candidate_test_case,
    list_candidate_review_events,
    list_candidate_test_cases,
    update_candidate_status,
    upsert_candidate_test_cases,
)
from llm_reliability_analytics.storage.trace_repository import capture_traces_for_run, fetch_traces
from llm_reliability_analytics.storage.evaluation_job_repository import (
    EvaluationJob,
    EvaluationJobCreate,
    EvaluationJobStatus,
    create_evaluation_job,
    get_evaluation_job,
    list_evaluation_jobs,
    update_evaluation_job,
)

__all__ = [
    "RunAggregatedSummary",
    "initialize_storage_schema",
    "insert_test_cases",
    "upsert_test_cases",
    "create_test_run",
    "insert_batch_results",
    "fetch_aggregated_summaries",
    "fetch_results_for_run",
    "capture_traces_for_run",
    "fetch_traces",
    "CandidateReviewEvent",
    "upsert_candidate_test_cases",
    "list_candidate_test_cases",
    "get_candidate_test_case",
    "update_candidate_status",
    "list_candidate_review_events",
    "EvaluationJob",
    "EvaluationJobCreate",
    "EvaluationJobStatus",
    "create_evaluation_job",
    "get_evaluation_job",
    "list_evaluation_jobs",
    "update_evaluation_job",
]
