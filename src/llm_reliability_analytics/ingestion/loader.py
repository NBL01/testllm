import csv
import json
import logging
from collections import Counter
from pathlib import Path
from typing import Any

from pydantic import BaseModel, Field, ValidationError

from llm_reliability_analytics.models.domain import TestCase

logger = logging.getLogger(__name__)

PROJECT_ROOT = Path(__file__).resolve().parents[3]
RAW_DATA_DIR = PROJECT_ROOT / "data" / "raw"


class IngestionSummary(BaseModel):
    total_rows: int
    valid_rows: int
    invalid_rows: int
    dataset_versions: list[str] = Field(default_factory=list)
    category_distribution: dict[str, int] = Field(default_factory=dict)
    oracle_type_distribution: dict[str, int] = Field(default_factory=dict)


def load_test_cases(file_path: str | Path) -> tuple[list[TestCase], IngestionSummary]:
    """Load test cases from a JSONL or CSV file.

    Relative paths are first checked as-is, then under ``data/raw/``.
    """
    path = _resolve_input_path(file_path)
    suffix = path.suffix.lower()

    if suffix == ".jsonl":
        return _load_from_jsonl(path)
    if suffix == ".csv":
        return _load_from_csv(path)
    raise ValueError(f"Unsupported file format: {path.suffix}. Use .jsonl or .csv")


def load_test_cases_from_raw(filename: str) -> tuple[list[TestCase], IngestionSummary]:
    """Load test cases from the default raw dataset directory."""
    return load_test_cases(RAW_DATA_DIR / filename)


def _load_from_jsonl(path: Path) -> tuple[list[TestCase], IngestionSummary]:
    test_cases: list[TestCase] = []
    total_rows = 0
    valid_rows = 0
    invalid_rows = 0

    with path.open("r", encoding="utf-8") as file_handle:
        for line_number, line in enumerate(file_handle, start=1):
            content = line.strip()
            if not content:
                continue

            total_rows += 1
            try:
                parsed = json.loads(content)
                test_case = _validate_row(parsed)
            except (json.JSONDecodeError, ValidationError, ValueError, TypeError) as exc:
                invalid_rows += 1
                logger.warning(
                    "Skipping invalid JSONL row %s in %s: %s",
                    line_number,
                    path.name,
                    exc,
                )
                continue

            test_cases.append(test_case)
            valid_rows += 1

    summary = _build_ingestion_summary(
        test_cases=test_cases,
        total_rows=total_rows,
        valid_rows=valid_rows,
        invalid_rows=invalid_rows,
    )
    return test_cases, summary


def _load_from_csv(path: Path) -> tuple[list[TestCase], IngestionSummary]:
    test_cases: list[TestCase] = []
    total_rows = 0
    valid_rows = 0
    invalid_rows = 0

    with path.open("r", encoding="utf-8", newline="") as file_handle:
        reader = csv.DictReader(file_handle)
        for row_index, row in enumerate(reader, start=1):
            total_rows += 1
            try:
                test_case = _validate_row(row)
            except (ValidationError, ValueError, TypeError) as exc:
                invalid_rows += 1
                logger.warning(
                    "Skipping invalid CSV row %s in %s: %s",
                    row_index,
                    path.name,
                    exc,
                )
                continue

            test_cases.append(test_case)
            valid_rows += 1

    summary = _build_ingestion_summary(
        test_cases=test_cases,
        total_rows=total_rows,
        valid_rows=valid_rows,
        invalid_rows=invalid_rows,
    )
    return test_cases, summary


def _validate_row(raw_row: Any) -> TestCase:
    if not isinstance(raw_row, dict):
        raise ValueError("Each row must be a JSON object/dict")

    row = dict(raw_row)
    row = {key: value for key, value in row.items() if key is not None}

    if "id" in row and (row["id"] is None or str(row["id"]).strip() == ""):
        row.pop("id")

    row["metadata"] = _parse_metadata(row.get("metadata"))
    return TestCase.model_validate(row)


def _parse_metadata(value: Any) -> dict[str, Any]:
    if value is None or value == "":
        return {}
    if isinstance(value, dict):
        return value
    if isinstance(value, str):
        try:
            parsed = json.loads(value)
        except json.JSONDecodeError as exc:
            raise ValueError("metadata must be valid JSON when provided as a string") from exc
        if not isinstance(parsed, dict):
            raise ValueError("metadata must decode to a JSON object")
        return parsed
    raise ValueError("metadata must be a dictionary or JSON object string")


def _resolve_input_path(file_path: str | Path) -> Path:
    path = Path(file_path)
    if path.exists():
        return path

    raw_path = RAW_DATA_DIR / path
    if raw_path.exists():
        return raw_path

    raise FileNotFoundError(f"Input file not found: {file_path}")


def _build_ingestion_summary(
    test_cases: list[TestCase],
    total_rows: int,
    valid_rows: int,
    invalid_rows: int,
) -> IngestionSummary:
    category_distribution = Counter(test_case.category for test_case in test_cases)
    oracle_type_distribution = Counter(test_case.oracle_type.value for test_case in test_cases)
    dataset_versions = sorted({test_case.dataset_version for test_case in test_cases})

    return IngestionSummary(
        total_rows=total_rows,
        valid_rows=valid_rows,
        invalid_rows=invalid_rows,
        dataset_versions=dataset_versions,
        category_distribution=dict(category_distribution),
        oracle_type_distribution=dict(oracle_type_distribution),
    )
