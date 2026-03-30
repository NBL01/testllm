from __future__ import annotations

from llm_reliability_analytics.models.domain import OracleType
from llm_reliability_analytics.test_authoring.models import CandidateTestCase

AMBIGUOUS_TOKENS: tuple[str, ...] = ("maybe", "could", "might", "any answer", "approximately")


def validate_candidate(candidate: CandidateTestCase) -> list[str]:
    errors: list[str] = []

    if not candidate.prompt.strip():
        errors.append("prompt_is_empty")
    if not candidate.expected_answer.strip():
        errors.append("expected_answer_is_empty")
    if len(candidate.prompt.strip()) < 12:
        errors.append("prompt_too_short")

    valid_oracle_types = {item.value for item in OracleType}
    if candidate.oracle_type not in valid_oracle_types:
        errors.append("invalid_oracle_type")

    prompt_lower = candidate.prompt.lower()
    if any(token in prompt_lower for token in AMBIGUOUS_TOKENS):
        errors.append("prompt_may_be_ambiguous")

    return errors


def score_candidate_quality(candidate: CandidateTestCase) -> float:
    score = 1.0
    score -= 0.25 if len(candidate.prompt.strip()) < 30 else 0.0
    score -= 0.25 if len(candidate.expected_answer.strip()) < 1 else 0.0
    score -= 0.10 if "output only" not in candidate.prompt.lower() else 0.0
    score -= 0.10 if "strict_output" not in candidate.metadata else 0.0
    score -= 0.10 if candidate.oracle_type in {"semantic_similarity", "semantic_match"} else 0.0
    return max(0.0, min(1.0, score))
