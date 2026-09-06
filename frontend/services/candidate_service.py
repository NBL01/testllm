"""Frontend adapter for candidate test authoring and review workflow."""

from __future__ import annotations

from pathlib import Path
from dataclasses import dataclass
from urllib.parse import quote
from typing import Literal

import pandas as pd

from frontend.services.api_client import APIClient, BackendAPIError
from llm_reliability_analytics.test_authoring.models import CandidateStatus, CandidateTestCase


@dataclass
class CandidatePromotionResult:
    requested: int
    promoted: int
    skipped_not_found: int
    skipped_not_approved: int
    promoted_ids: list[str]
    skipped_ids: list[str]
    exported_count: int = 0
    export_path: str | None = None


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
    payload = APIClient().request("POST", "/candidates/generate", json={
        "categories": categories or DEFAULT_AUTHORING_CATEGORIES,
        "per_category": max(1, per_category), "provider": provider,
        "model_name": model_name, "temperature": temperature,
        "max_output_tokens": max_output_tokens, "timeout_seconds": timeout_seconds,
    })
    return [CandidateTestCase.model_validate(item) for item in payload["candidates"]]


def list_candidates_frame(
    status: CandidateStatus | None = None,
    category: str | None = None,
    limit: int = 1000,
) -> pd.DataFrame:
    payload = APIClient().request("GET", "/candidates", params={
        "status": status.value if status else None, "category": category, "limit": limit,
    })
    items = [CandidateTestCase.model_validate(item) for item in payload["items"]]
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
    try:
        payload = APIClient().request("POST", f"/candidates/{quote(candidate_id, safe='')}/status", json={
            "new_status": new_status.value, "reviewer": reviewer, "note": note,
        })
    except BackendAPIError as exc:
        if exc.status_code == 404:
            return None
        raise
    return CandidateTestCase.model_validate(payload["candidate"])


def candidate_events_frame(candidate_id: str, limit: int = 100) -> pd.DataFrame:
    payload = APIClient().request("GET", f"/candidates/{quote(candidate_id, safe='')}/events", params={"limit": limit})
    rows = [
        {key: (event.get(key) or "") for key in
         ["event_id", "old_status", "new_status", "reviewer", "note", "created_at"]}
        for event in payload["events"]
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
    payload = APIClient().request("POST", "/internal/candidates/promote", json={
        "candidate_ids": candidate_ids, "dataset_version": dataset_version,
        "target_source": target_source, "export_to_jsonl": export_to_jsonl,
    })
    return CandidatePromotionResult(**payload)
