import json

from llm_reliability_analytics.datasets.candidate_promoter import (
    build_export_jsonl_path,
    promote_candidates_to_test_cases,
)
from llm_reliability_analytics.models.domain import DifficultyLevel, TestSource as DomainTestSource
from llm_reliability_analytics.storage.candidate_repository import upsert_candidate_test_cases
from llm_reliability_analytics.storage.db import get_connection
from llm_reliability_analytics.storage.duckdb_store import initialize_storage_schema
from llm_reliability_analytics.test_authoring.models import CandidateStatus, CandidateTestCase


def test_promote_candidates_requires_approved_status(monkeypatch, tmp_path) -> None:
    db_path = tmp_path / "candidate_promoter.duckdb"
    monkeypatch.setenv("LLM_RELIABILITY_DB_PATH", str(db_path))
    initialize_storage_schema()

    approved = CandidateTestCase(
        candidate_id="cand-approved",
        category="factual_qa",
        difficulty=DifficultyLevel.EASY,
        prompt="Output only the capital of Italy.",
        expected_answer="Rome",
        oracle_type="exact_match",
        status=CandidateStatus.APPROVED,
        metadata={"strict_output": True},
    )
    not_approved = CandidateTestCase(
        candidate_id="cand-reviewed",
        category="classification",
        difficulty=DifficultyLevel.MEDIUM,
        prompt="Output only positive/negative/neutral for text 'Great support'.",
        expected_answer="positive",
        oracle_type="exact_match",
        status=CandidateStatus.REVIEWED,
        metadata={"strict_output": True},
    )
    upsert_candidate_test_cases([approved, not_approved])

    result = promote_candidates_to_test_cases(
        candidate_ids=["cand-approved", "cand-reviewed", "cand-missing"],
        dataset_version="v2.2-candidate-promo",
        target_source=DomainTestSource.REGRESSION,
    )
    assert result.requested == 3
    assert result.promoted == 1
    assert result.skipped_not_approved == 1
    assert result.skipped_not_found == 1
    assert result.promoted_ids == ["cand-approved"]

    conn = get_connection()
    rows = conn.execute(
        """
        SELECT test_case_id, dataset_version, test_source, category, prompt, expected_answer
        FROM test_cases
        ORDER BY test_case_id;
        """
    ).fetchall()
    conn.close()

    assert len(rows) == 1
    stored = rows[0]
    assert stored[0] == "candidate-cand-approved"
    assert stored[1] == "v2.2-candidate-promo"
    assert stored[2] == "regression"


def test_promote_candidates_can_export_jsonl(monkeypatch, tmp_path) -> None:
    db_path = tmp_path / "candidate_promoter_export.duckdb"
    monkeypatch.setenv("LLM_RELIABILITY_DB_PATH", str(db_path))
    initialize_storage_schema()

    candidate = CandidateTestCase(
        candidate_id="cand-export-1",
        category="numeric_reasoning",
        difficulty=DifficultyLevel.MEDIUM,
        prompt="Compute 9 * 9. Output only integer.",
        expected_answer="81",
        oracle_type="numeric_tolerance",
        status=CandidateStatus.APPROVED,
        metadata={"strict_output": True},
    )
    upsert_candidate_test_cases([candidate])

    project_root = tmp_path / "project"
    export_path = build_export_jsonl_path(
        project_root=project_root,
        dataset_version="v3.0-export",
        target_source=DomainTestSource.REGRESSION,
    )
    result = promote_candidates_to_test_cases(
        candidate_ids=["cand-export-1"],
        dataset_version="v3.0-export",
        target_source=DomainTestSource.REGRESSION,
        export_jsonl_path=export_path,
    )
    assert result.promoted == 1
    assert result.exported_count == 1
    assert result.export_path == str(export_path)
    assert export_path.exists()

    rows = [line for line in export_path.read_text(encoding="utf-8").splitlines() if line.strip()]
    assert len(rows) == 1
    payload = json.loads(rows[0])
    assert payload["dataset_version"] == "v3.0-export"
    assert payload["test_source"] == "regression"
