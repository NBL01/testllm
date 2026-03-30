"""Promote approved candidate test cases into reusable datasets."""

from __future__ import annotations

import json
from pathlib import Path

from pydantic import BaseModel, Field

from llm_reliability_analytics.models.domain import TestCase, TestSource
from llm_reliability_analytics.storage.candidate_repository import get_candidate_test_case
from llm_reliability_analytics.storage.duckdb_store import upsert_test_cases
from llm_reliability_analytics.test_authoring.models import CandidateStatus


class CandidatePromotionResult(BaseModel):
    requested: int = Field(ge=0)
    promoted: int = Field(ge=0)
    skipped_not_found: int = Field(ge=0)
    skipped_not_approved: int = Field(ge=0)
    promoted_ids: list[str] = Field(default_factory=list)
    skipped_ids: list[str] = Field(default_factory=list)
    exported_count: int = Field(default=0, ge=0)
    export_path: str | None = None


def promote_candidates_to_test_cases(
    candidate_ids: list[str],
    dataset_version: str,
    target_source: TestSource,
    export_jsonl_path: Path | None = None,
) -> CandidatePromotionResult:
    if not candidate_ids:
        return CandidatePromotionResult(requested=0, promoted=0)

    requested = len(candidate_ids)
    to_insert: list[TestCase] = []
    promoted_ids: list[str] = []
    skipped_ids: list[str] = []
    skipped_not_found = 0
    skipped_not_approved = 0

    for candidate_id in candidate_ids:
        candidate = get_candidate_test_case(candidate_id)
        if candidate is None:
            skipped_not_found += 1
            skipped_ids.append(candidate_id)
            continue
        if candidate.status != CandidateStatus.APPROVED:
            skipped_not_approved += 1
            skipped_ids.append(candidate_id)
            continue
        to_insert.append(candidate.to_test_case(dataset_version=dataset_version, test_source=target_source))
        promoted_ids.append(candidate_id)

    promoted = upsert_test_cases(to_insert) if to_insert else 0
    result = CandidatePromotionResult(
        requested=requested,
        promoted=promoted,
        skipped_not_found=skipped_not_found,
        skipped_not_approved=skipped_not_approved,
        promoted_ids=promoted_ids,
        skipped_ids=skipped_ids,
        exported_count=0,
        export_path=None,
    )
    if export_jsonl_path is not None and to_insert:
        exported = _export_test_cases_jsonl(to_insert, export_jsonl_path)
        result.exported_count = exported
        result.export_path = str(export_jsonl_path)
    return result


def build_export_jsonl_path(project_root: Path, dataset_version: str, target_source: TestSource) -> Path:
    safe_version = dataset_version.strip().replace(" ", "_")
    filename = f"{safe_version}_{target_source.value}_promoted.jsonl"
    if target_source == TestSource.ADVERSARIAL:
        return project_root / "data" / "adversarial" / filename
    return project_root / "data" / "raw" / filename


def _export_test_cases_jsonl(test_cases: list[TestCase], output_path: Path) -> int:
    output_path.parent.mkdir(parents=True, exist_ok=True)
    with output_path.open("w", encoding="utf-8") as handle:
        for test_case in test_cases:
            handle.write(json.dumps(test_case.model_dump(mode="json"), ensure_ascii=False) + "\n")
    return len(test_cases)
