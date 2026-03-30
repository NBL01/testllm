from __future__ import annotations

from datetime import datetime, timezone
from enum import Enum
from uuid import uuid4

from pydantic import BaseModel, Field

from llm_reliability_analytics.models.domain import DifficultyLevel, TestCase, TestSource


class CandidateStatus(str, Enum):
    DRAFT = "draft"
    REVIEWED = "reviewed"
    APPROVED = "approved"
    REJECTED = "rejected"


class CandidateTestCase(BaseModel):
    candidate_id: str = Field(default_factory=lambda: str(uuid4()))
    category: str
    difficulty: DifficultyLevel = DifficultyLevel.MEDIUM
    prompt: str
    expected_answer: str
    oracle_type: str
    source_context: str = ""
    rationale: str = ""
    quality_score: float = Field(default=0.0, ge=0.0, le=1.0)
    validation_errors: list[str] = Field(default_factory=list)
    status: CandidateStatus = CandidateStatus.DRAFT
    metadata: dict[str, object] = Field(default_factory=dict)
    created_at: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))

    def to_test_case(self, dataset_version: str, test_source: TestSource = TestSource.SYNTHETIC) -> TestCase:
        return TestCase(
            id=f"candidate-{self.candidate_id}",
            test_source=test_source,
            dataset_version=dataset_version,
            category=self.category,
            difficulty=self.difficulty,
            prompt=self.prompt,
            expected_answer=self.expected_answer,
            oracle_type=self.oracle_type,
            metadata={
                **self.metadata,
                "candidate_id": self.candidate_id,
                "candidate_status": self.status.value,
                "candidate_quality_score": self.quality_score,
                "candidate_rationale": self.rationale,
                "candidate_source_context": self.source_context,
            },
        )
