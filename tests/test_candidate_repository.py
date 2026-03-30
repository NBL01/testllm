from llm_reliability_analytics.models.domain import DifficultyLevel
from llm_reliability_analytics.storage.candidate_repository import (
    get_candidate_test_case,
    list_candidate_review_events,
    list_candidate_test_cases,
    update_candidate_status,
    upsert_candidate_test_cases,
)
from llm_reliability_analytics.storage.duckdb_store import initialize_storage_schema
from llm_reliability_analytics.test_authoring.models import CandidateStatus, CandidateTestCase


def test_upsert_and_list_candidates(monkeypatch, tmp_path) -> None:
    db_path = tmp_path / "candidates_repo.duckdb"
    monkeypatch.setenv("LLM_RELIABILITY_DB_PATH", str(db_path))
    initialize_storage_schema()

    candidates = [
        CandidateTestCase(
            candidate_id="cand-1",
            category="factual_qa",
            difficulty=DifficultyLevel.EASY,
            prompt="Output only the capital of Spain.",
            expected_answer="Madrid",
            oracle_type="exact_match",
            status=CandidateStatus.REVIEWED,
            metadata={"strict_output": True},
        ),
        CandidateTestCase(
            candidate_id="cand-2",
            category="classification",
            difficulty=DifficultyLevel.MEDIUM,
            prompt="Output only positive/negative/neutral for text 'Great product'.",
            expected_answer="positive",
            oracle_type="exact_match",
            status=CandidateStatus.DRAFT,
            metadata={"strict_output": True},
        ),
    ]
    inserted = upsert_candidate_test_cases(candidates)
    assert inserted == 2

    all_items = list_candidate_test_cases(max_rows=20)
    assert len(all_items) == 2
    reviewed_items = list_candidate_test_cases(status=CandidateStatus.REVIEWED, max_rows=20)
    assert len(reviewed_items) == 1
    assert reviewed_items[0].candidate_id == "cand-1"


def test_update_candidate_status_creates_review_event(monkeypatch, tmp_path) -> None:
    db_path = tmp_path / "candidate_status.duckdb"
    monkeypatch.setenv("LLM_RELIABILITY_DB_PATH", str(db_path))
    initialize_storage_schema()

    candidate = CandidateTestCase(
        candidate_id="cand-status-1",
        category="numeric_reasoning",
        difficulty=DifficultyLevel.HARD,
        prompt="Compute 12 * 11. Output only integer.",
        expected_answer="132",
        oracle_type="numeric_tolerance",
        status=CandidateStatus.REVIEWED,
        metadata={"strict_output": True},
    )
    upsert_candidate_test_cases([candidate])

    updated = update_candidate_status(
        candidate_id="cand-status-1",
        new_status=CandidateStatus.APPROVED,
        reviewer="qa-user",
        note="Approved for next regression dataset",
    )
    assert updated is not None
    assert updated.status == CandidateStatus.APPROVED

    loaded = get_candidate_test_case("cand-status-1")
    assert loaded is not None
    assert loaded.status == CandidateStatus.APPROVED

    events = list_candidate_review_events(candidate_id="cand-status-1", max_rows=10)
    assert len(events) == 1
    assert events[0].old_status == CandidateStatus.REVIEWED
    assert events[0].new_status == CandidateStatus.APPROVED
    assert events[0].reviewer == "qa-user"
