from __future__ import annotations

import json
from pathlib import Path
from uuid import uuid4

from llm_reliability_analytics.models.domain import DifficultyLevel
from llm_reliability_analytics.runner.llm_client import BaseLLMClient
from llm_reliability_analytics.test_authoring.models import CandidateStatus, CandidateTestCase
from llm_reliability_analytics.test_authoring.validators import score_candidate_quality, validate_candidate


DEFAULT_WEAK_CATEGORY_SEEDS: dict[str, dict[str, str]] = {
    "factual_qa": {
        "oracle_type": "exact_match",
        "prompt": "Factual task: output ONLY the capital city for {subject}.",
        "expected_answer": "{target}",
        "subject": "Portugal",
        "target": "Lisbon",
    },
    "classification": {
        "oracle_type": "exact_match",
        "prompt": "Classification task: output EXACTLY one label [positive, negative, neutral] for text: '{subject}'.",
        "expected_answer": "{target}",
        "subject": "The software was useful and stable.",
        "target": "positive",
    },
    "information_extraction": {
        "oracle_type": "regex_match",
        "prompt": "Information extraction task: output ONLY the email address from: '{subject}'.",
        "expected_answer": "{target}",
        "subject": "Primary contact is owner42@example.com.",
        "target": "owner42@example.com",
    },
    "numeric_reasoning": {
        "oracle_type": "numeric_tolerance",
        "prompt": "Numeric reasoning task: compute {subject}. Output ONLY the final integer.",
        "expected_answer": "{target}",
        "subject": "19 * 7",
        "target": "133",
    },
    "format_constrained_json": {
        "oracle_type": "json_schema",
        "prompt": "Format task: return ONLY valid JSON object with city and country for {subject}.",
        "expected_answer": "{target}",
        "subject": "city=Seoul, country=South Korea",
        "target": (
            '{"type":"object","properties":{"city":{"type":"string"},"country":{"type":"string"}},'
            '"required":["city","country"],"additionalProperties":false}'
        ),
    },
    "instruction_following": {
        "oracle_type": "keyword_match",
        "prompt": "Instruction-following task: repeat EXACTLY token '{subject}'. Output only that token.",
        "expected_answer": "{target}",
        "subject": "OMEGA",
        "target": "omega",
    },
    "consistency_check": {
        "oracle_type": "exact_match",
        "prompt": "Consistency task: output EXACTLY one label [consistent, inconsistent] for statement: {subject}",
        "expected_answer": "{target}",
        "subject": "All birds have wings. Sparrow is a bird.",
        "target": "consistent",
    },
}


class CandidateAuthoringService:
    """Generate and validate candidate test cases for later human review."""

    def __init__(self, llm_client: BaseLLMClient | None = None) -> None:
        self.llm_client = llm_client

    def generate_candidates(self, categories: list[str], per_category: int = 5) -> list[CandidateTestCase]:
        normalized_categories = [category.strip() for category in categories if category.strip()]
        if not normalized_categories:
            normalized_categories = sorted(DEFAULT_WEAK_CATEGORY_SEEDS.keys())

        candidates: list[CandidateTestCase] = []
        for category in normalized_categories:
            seed = DEFAULT_WEAK_CATEGORY_SEEDS.get(category)
            if not seed:
                continue
            for index in range(per_category):
                candidate = self._generate_single_candidate(category=category, seed=seed, index=index)
                candidate.validation_errors = validate_candidate(candidate)
                candidate.quality_score = score_candidate_quality(candidate)
                candidate.status = CandidateStatus.REVIEWED if not candidate.validation_errors else CandidateStatus.DRAFT
                candidates.append(candidate)

        return candidates

    def save_candidates(self, candidates: list[CandidateTestCase], output_path: Path) -> None:
        output_path.parent.mkdir(parents=True, exist_ok=True)
        with output_path.open("w", encoding="utf-8") as handle:
            for candidate in candidates:
                handle.write(json.dumps(candidate.model_dump(mode="json"), ensure_ascii=False) + "\n")

    def _generate_single_candidate(self, category: str, seed: dict[str, str], index: int) -> CandidateTestCase:
        prompt = self._prompt_variation(seed["prompt"], seed["subject"], index)
        expected_answer = seed["expected_answer"].format(target=seed["target"])
        rationale = "Seeded candidate for weak-category reinforcement."

        if self.llm_client is not None:
            suggested_prompt = self._rewrite_prompt_with_model(prompt=prompt)
            if suggested_prompt:
                prompt = suggested_prompt
                rationale = "LLM-assisted prompt rewrite from seed candidate."

        return CandidateTestCase(
            candidate_id=str(uuid4()),
            category=category,
            difficulty=[DifficultyLevel.EASY, DifficultyLevel.MEDIUM, DifficultyLevel.HARD][index % 3],
            prompt=prompt,
            expected_answer=expected_answer,
            oracle_type=seed["oracle_type"],
            source_context="auto_generated",
            rationale=rationale,
            metadata={
                "strict_output": True,
                "seed_subject": seed["subject"],
                "seed_target": seed["target"],
                "seed_index": index,
            },
        )

    def _rewrite_prompt_with_model(self, prompt: str) -> str | None:
        try:
            rewritten = self.llm_client.generate(
                "Rewrite this evaluation prompt to be clear and deterministic. Keep same task. "
                "Return only the rewritten prompt.\n\n"
                f"Prompt: {prompt}"
            )
        except Exception:  # noqa: BLE001 - candidate generation should remain fault tolerant
            return None
        normalized = rewritten.strip()
        return normalized if len(normalized) >= 12 else None

    @staticmethod
    def _prompt_variation(template: str, subject: str, index: int) -> str:
        variants = [
            template.format(subject=subject),
            f"{template.format(subject=subject)} No explanation.",
            f"{template.format(subject=subject)} Output only the final answer.",
        ]
        return variants[index % len(variants)]
