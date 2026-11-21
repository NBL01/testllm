"""Persistence module."""

from llm_reliability_analytics.storage.duckdb_store import (
    RunAggregatedSummary,
    create_test_run,
    fetch_results_for_run,
    fetch_aggregated_summaries,
    initialize_storage_schema,
    insert_batch_results,
    upsert_test_cases,
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
    "upsert_test_cases",
    "create_test_run",
    "insert_batch_results",
    "fetch_aggregated_summaries",
    "fetch_results_for_run",
    "capture_traces_for_run",
    "fetch_traces",
    "EvaluationJob",
    "EvaluationJobCreate",
    "EvaluationJobStatus",
    "create_evaluation_job",
    "get_evaluation_job",
    "list_evaluation_jobs",
    "update_evaluation_job",
]
