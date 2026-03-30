from pathlib import Path

from llm_reliability_analytics.test_authoring.models import CandidateStatus, CandidateTestCase
from llm_reliability_analytics.test_authoring.service import CandidateAuthoringService
from llm_reliability_analytics.test_authoring.validators import score_candidate_quality, validate_candidate


def test_generate_candidates_returns_expected_count() -> None:
    service = CandidateAuthoringService(llm_client=None)
    candidates = service.generate_candidates(categories=["factual_qa", "classification"], per_category=3)
    assert len(candidates) == 6
    assert all(candidate.category in {"factual_qa", "classification"} for candidate in candidates)
    assert all(candidate.status in {CandidateStatus.DRAFT, CandidateStatus.REVIEWED} for candidate in candidates)


def test_validate_candidate_detects_invalid_oracle() -> None:
    candidate = CandidateTestCase(
        category="factual_qa",
        prompt="Output only the capital for Spain.",
        expected_answer="Madrid",
        oracle_type="unknown_oracle",
    )
    errors = validate_candidate(candidate)
    assert "invalid_oracle_type" in errors


def test_score_candidate_quality_in_range() -> None:
    candidate = CandidateTestCase(
        category="instruction_following",
        prompt="Instruction-following task: output only token OMEGA.",
        expected_answer="omega",
        oracle_type="keyword_match",
        metadata={"strict_output": True},
    )
    score = score_candidate_quality(candidate)
    assert 0.0 <= score <= 1.0


def test_save_candidates_writes_jsonl(tmp_path: Path) -> None:
    service = CandidateAuthoringService(llm_client=None)
    candidates = service.generate_candidates(categories=["numeric_reasoning"], per_category=2)
    output = tmp_path / "candidates.jsonl"
    service.save_candidates(candidates, output)
    assert output.exists()
    lines = [line for line in output.read_text(encoding="utf-8").splitlines() if line.strip()]
    assert len(lines) == 2
