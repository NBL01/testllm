"""Frontend adapter for candidate test authoring and review workflow."""

from __future__ import annotations

from pathlib import Path
from typing import Literal

import pandas as pd

from llm_reliability_analytics.datasets.candidate_promoter import (
    CandidatePromotionResult,
    build_export_jsonl_path,
    promote_candidates_to_test_cases,
)
from llm_reliability_analytics.models.domain import TestSource
from llm_reliability_analytics.runner.client_factory import build_llm_client
from llm_reliability_analytics.storage.candidate_repository import (
    list_candidate_review_events,
    list_candidate_test_cases,
    update_candidate_status,
    upsert_candidate_test_cases,
)
from llm_reliability_analytics.test_authoring.models import CandidateStatus, CandidateTestCase
from llm_reliability_analytics.test_authoring.service import CandidateAuthoringService


DEFAULT_AUTHORING_CATEGORIES: list[str] = [
    "factual_qa",
    "classification",
    "information_extraction",
    "numeric_reasoning",
    "format_constrained_json",
    "instruction_following",
    "consistency_check",
]


def generate_candidates_and_store(
    categories: list[str],
    per_category: int,
    provider: Literal["none", "mock", "ollama"] = "none",
    model_name: str | None = None,
    temperature: float = 0.1,
    max_output_tokens: int = 120,
    timeout_seconds: float = 20.0,
) -> list[CandidateTestCase]:
    llm_client = None
    if provider != "none":
        resolved_model_name = model_name or ("mock-baseline" if provider == "mock" else None)
        llm_client = build_llm_client(
            provider=provider,
            run_mode="real_local" if provider == "ollama" else "mock",
            model_name=resolved_model_name,
            temperature=temperature,
            max_output_tokens=max_output_tokens,
            timeout_seconds=timeout_seconds,
        )

    service = CandidateAuthoringService(llm_client=llm_client)
    generated = service.generate_candidates(
        categories=categories or DEFAULT_AUTHORING_CATEGORIES,
        per_category=max(1, per_category),
    )
    upsert_candidate_test_cases(generated)
    return generated


def list_candidates_frame(
    status: CandidateStatus | None = None,
    category: str | None = None,
    limit: int = 1000,
) -> pd.DataFrame:
    items = list_candidate_test_cases(status=status, category=category, max_rows=limit)
    rows = []
    for item in items:
        rows.append(
            {
                "candidate_id": item.candidate_id,
                "category": item.category,
                "difficulty": item.difficulty.value,
                "oracle_type": item.oracle_type,
                "status": item.status.value,
                "quality_score": float(item.quality_score),
                "validation_error_count": len(item.validation_errors),
                "validation_errors": ", ".join(item.validation_errors),
                "prompt": item.prompt,
                "expected_answer": item.expected_answer,
                "source_context": item.source_context,
                "rationale": item.rationale,
                "created_at": item.created_at,
            }
        )
    if not rows:
        return pd.DataFrame(
            columns=[
                "candidate_id",
                "category",
                "difficulty",
                "oracle_type",
                "status",
                "quality_score",
                "validation_error_count",
                "validation_errors",
                "prompt",
                "expected_answer",
                "source_context",
                "rationale",
                "created_at",
            ]
        )
    return pd.DataFrame(rows)


def set_candidate_status(
    candidate_id: str,
    new_status: CandidateStatus,
    reviewer: str = "",
    note: str = "",
) -> CandidateTestCase | None:
    return update_candidate_status(
        candidate_id=candidate_id,
        new_status=new_status,
        reviewer=reviewer,
        note=note,
    )


def candidate_events_frame(candidate_id: str, limit: int = 100) -> pd.DataFrame:
    events = list_candidate_review_events(candidate_id=candidate_id, max_rows=limit)
    rows = [
        {
            "event_id": event.event_id,
            "old_status": event.old_status.value if event.old_status else "",
            "new_status": event.new_status.value,
            "reviewer": event.reviewer,
            "note": event.note,
            "created_at": event.created_at,
        }
        for event in events
    ]
    if not rows:
        return pd.DataFrame(columns=["event_id", "old_status", "new_status", "reviewer", "note", "created_at"])
    return pd.DataFrame(rows)


def promote_candidates(
    candidate_ids: list[str],
    dataset_version: str,
    target_source: Literal["regression", "adversarial", "synthetic"],
    export_to_jsonl: bool = True,
    project_root: Path | None = None,
) -> CandidatePromotionResult:
    source_enum = TestSource(target_source)
    export_path = None
    if export_to_jsonl:
        if project_root is None:
            raise ValueError("project_root is required when export_to_jsonl=True")
        export_path = build_export_jsonl_path(
            project_root=project_root,
            dataset_version=dataset_version,
            target_source=source_enum,
        )

    return promote_candidates_to_test_cases(
        candidate_ids=candidate_ids,
        dataset_version=dataset_version,
        target_source=source_enum,
        export_jsonl_path=export_path,
    )
