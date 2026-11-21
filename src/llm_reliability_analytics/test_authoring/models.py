from __future__ import annotations

from datetime import datetime, timezone
from enum import Enum
from uuid import uuid4

from pydantic import BaseModel, Field

from llm_reliability_analytics.models.domain import DifficultyLevel


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

