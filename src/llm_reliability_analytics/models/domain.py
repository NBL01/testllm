from datetime import datetime, timezone
from enum import Enum
from typing import Any
from uuid import uuid4

from pydantic import BaseModel, Field


class DifficultyLevel(str, Enum):
    EASY = "easy"
    MEDIUM = "medium"
    HARD = "hard"


class OracleType(str, Enum):
    EXACT_MATCH = "exact_match"
    SEMANTIC_MATCH = "semantic_match"
    CUSTOM = "custom"


class RunStatus(str, Enum):
    PENDING = "pending"
    RUNNING = "running"
    COMPLETED = "completed"
    FAILED = "failed"


class TestCase(BaseModel):
    id: str = Field(default_factory=lambda: str(uuid4()))
    category: str
    difficulty: DifficultyLevel
    prompt: str
    expected_answer: str
    oracle_type: OracleType
    metadata: dict[str, Any] = Field(default_factory=dict)


class TestRun(BaseModel):
    id: str = Field(default_factory=lambda: str(uuid4()))
    name: str
    model_name: str
    status: RunStatus = RunStatus.PENDING
    started_at: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))
    finished_at: datetime | None = None
    metadata: dict[str, Any] = Field(default_factory=dict)


class TestResult(BaseModel):
    run_id: str
    test_case_id: str
    category: str | None = None
    actual_answer: str | None = None
    is_correct: bool
    score: float = Field(ge=0.0, le=1.0)
    latency_ms: float = Field(ge=0.0)
    error_type: str | None = None
