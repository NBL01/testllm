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
    REGEX_MATCH = "regex_match"
    KEYWORD_MATCH = "keyword_match"
    NUMERIC_TOLERANCE = "numeric_tolerance"
    JSON_SCHEMA = "json_schema"
    SEMANTIC_SIMILARITY = "semantic_similarity"
    COMPOSITE_RULE = "composite_rule"


class RunStatus(str, Enum):
    PENDING = "pending"
    RUNNING = "running"
    COMPLETED = "completed"
    FAILED = "failed"


class ErrorTaxonomy(str, Enum):
    NONE = "none"
    RUNTIME = "runtime"
    ORACLE = "oracle"
    VALIDATION = "validation"
    PARSING = "parsing"
    TIMEOUT = "timeout"
    UNKNOWN = "unknown"


class TestCase(BaseModel):
    id: str = Field(default_factory=lambda: str(uuid4()))
    dataset_version: str = "v1"
    category: str
    difficulty: DifficultyLevel
    prompt: str
    expected_answer: str
    oracle_type: OracleType
    metadata: dict[str, Any] = Field(default_factory=dict)


class TestRun(BaseModel):
    id: str = Field(default_factory=lambda: str(uuid4()))
    name: str
    run_label: str | None = None
    model_name: str
    provider: str = "local"
    model_version: str = "n/a"
    dataset_version: str = "v1"
    created_at: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))
    temperature: float = 0.0
    repeat_count: int = Field(default=1, ge=1)
    mode: str = "mock"
    notes: str = ""
    run_group_id: str = ""
    repetition_index: int = Field(default=1, ge=1)
    status: RunStatus = RunStatus.PENDING
    started_at: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))
    finished_at: datetime | None = None
    metadata: dict[str, Any] = Field(default_factory=dict)


class TestResult(BaseModel):
    run_id: str
    test_case_id: str
    attempt_index: int = Field(default=1, ge=1)
    category: str | None = None
    oracle_type: str | None = None
    dataset_version: str | None = None
    actual_answer: str | None = None
    expected_answer_normalized: str | None = None
    actual_answer_normalized: str | None = None
    is_correct: bool
    score: float = Field(ge=0.0, le=1.0)
    latency_ms: float = Field(ge=0.0)
    latency_source: str = "measured"
    error_type: str | None = None
    error_taxonomy: ErrorTaxonomy = ErrorTaxonomy.NONE
    critical_error_flag: bool = False
    normalized_answer: str | None = None


class CategoryLevelReport(BaseModel):
    category: str
    total_test_cases: int = Field(ge=0)
    passed: int = Field(ge=0)
    failed: int = Field(ge=0)
    accuracy: float = Field(ge=0.0, le=1.0)
    average_latency_ms: float = Field(ge=0.0)


class RunLevelReport(BaseModel):
    run_id: str
    dataset_version: str
    repetition_index: int = Field(ge=1)
    total_test_cases: int = Field(ge=0)
    unique_test_cases: int = Field(default=0, ge=0)
    attempts_per_case: float = Field(default=1.0, ge=0.0)
    passed: int = Field(ge=0)
    failed: int = Field(ge=0)
    accuracy: float = Field(ge=0.0, le=1.0)
    average_latency_ms: float = Field(ge=0.0)
    p95_latency_ms: float = Field(default=0.0, ge=0.0)
    consistency_score: float = Field(default=0.0, ge=0.0, le=1.0)
    repeatability_score: float = Field(default=0.0, ge=0.0, le=1.0)
    schema_compliance_rate: float = Field(default=0.0, ge=0.0, le=1.0)
    critical_error_rate: float = Field(default=0.0, ge=0.0, le=1.0)
    failure_density_per_1000: float = Field(default=0.0, ge=0.0)
    unstable_case_count: int = Field(default=0, ge=0)
    error_taxonomy_distribution: dict[str, int] = Field(default_factory=dict)
