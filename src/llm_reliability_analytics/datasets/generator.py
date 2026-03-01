"""Structured synthetic dataset generator for LLM evaluation demos."""

import json
from pathlib import Path

import duckdb
import pandas as pd
from pydantic import BaseModel, Field

from llm_reliability_analytics.models.domain import DifficultyLevel, TestCase

DEFAULT_CATEGORIES: tuple[str, ...] = (
    "factual_qa",
    "classification",
    "information_extraction",
    "numeric_reasoning",
    "format_constrained_json",
    "instruction_following",
    "consistency_check",
)


class DatasetGenerationConfig(BaseModel):
    total_cases: int = 300
    dataset_version: str = "v2.0-demo"
    output_jsonl: Path = Path("data/raw/llm_eval_dataset_v2_300.jsonl")
    output_parquet: Path = Path("data/raw/llm_eval_dataset_v2_300.parquet")


def generate_dataset_records(config: DatasetGenerationConfig) -> list[TestCase]:
    """Generate balanced synthetic test cases across core evaluation categories."""
    per_category = _balanced_category_counts(config.total_cases, list(DEFAULT_CATEGORIES))
    records: list[TestCase] = []
    case_counter = 1

    for category in DEFAULT_CATEGORIES:
        count = per_category[category]
        for local_idx in range(count):
            difficulty = _difficulty_for_index(local_idx)
            test_case = _build_test_case(
                case_index=case_counter,
                local_index=local_idx,
                category=category,
                difficulty=difficulty,
                dataset_version=config.dataset_version,
            )
            records.append(test_case)
            case_counter += 1
    return records


def save_dataset_files(records: list[TestCase], output_jsonl: Path, output_parquet: Path) -> None:
    """Save records as JSONL + Parquet for ingestion and analytics workflows."""
    output_jsonl.parent.mkdir(parents=True, exist_ok=True)
    output_parquet.parent.mkdir(parents=True, exist_ok=True)

    with output_jsonl.open("w", encoding="utf-8") as fh:
        for record in records:
            fh.write(json.dumps(record.model_dump(), ensure_ascii=False) + "\n")

    df = pd.DataFrame(record.model_dump() for record in records)
    for column in ("difficulty", "oracle_type"):
        if column in df.columns:
            df[column] = df[column].astype(str)
    conn = duckdb.connect()
    conn.register("dataset_df", df)
    conn.execute(
        """
        COPY dataset_df
        TO ?
        (FORMAT PARQUET);
        """,
        [str(output_parquet)],
    )
    conn.close()


def _balanced_category_counts(total: int, categories: list[str]) -> dict[str, int]:
    base = total // len(categories)
    remainder = total % len(categories)
    counts: dict[str, int] = {}
    for idx, category in enumerate(categories):
        counts[category] = base + (1 if idx < remainder else 0)
    return counts


def _difficulty_for_index(index: int) -> DifficultyLevel:
    cycle = [DifficultyLevel.EASY, DifficultyLevel.MEDIUM, DifficultyLevel.HARD]
    return cycle[index % len(cycle)]


def _build_test_case(
    case_index: int,
    local_index: int,
    category: str,
    difficulty: DifficultyLevel,
    dataset_version: str,
) -> TestCase:
    case_id = f"tc-{dataset_version.replace('.', '-')}-{case_index:04d}"

    if category == "factual_qa":
        country_capitals = [
            ("Japan", "Tokyo"),
            ("France", "Paris"),
            ("Germany", "Berlin"),
            ("Canada", "Ottawa"),
            ("Italy", "Rome"),
        ]
        country, capital = country_capitals[local_index % len(country_capitals)]
        prompt = f"What is the capital of {country}?"
        expected_answer = capital
        oracle_type = "exact_match"
        metadata = {"task_type": "single_hop_qa", "source": "synthetic"}

    elif category == "classification":
        samples = [
            ("This movie was excellent and inspiring.", "positive"),
            ("The service was terrible and slow.", "negative"),
            ("The product is average overall.", "neutral"),
        ]
        text, label = samples[local_index % len(samples)]
        prompt = f"Classify sentiment as positive, negative, or neutral: '{text}'"
        expected_answer = label
        oracle_type = "exact_match"
        metadata = {"labels": ["positive", "negative", "neutral"], "source": "synthetic"}

    elif category == "information_extraction":
        user_num = local_index + 1
        email = f"user{user_num}@example.com"
        prompt = f"Extract the email address only: 'Contact user is {email}.'"
        expected_answer = email
        oracle_type = "regex_match"
        metadata = {"ignore_case": True, "source": "synthetic", "entity": "email"}

    elif category == "numeric_reasoning":
        a = (local_index % 20) + 3
        b = (local_index % 10) + 2
        result = a * b
        prompt = f"Compute {a} * {b}. Return only the number."
        expected_answer = str(result)
        oracle_type = "numeric_tolerance"
        metadata = {"tolerance": 0.0, "source": "synthetic", "operation": "multiply"}

    elif category == "format_constrained_json":
        cities = [("Almaty", "Kazakhstan"), ("Paris", "France"), ("Berlin", "Germany")]
        city, country = cities[local_index % len(cities)]
        schema = {
            "type": "object",
            "properties": {
                "city": {"type": "string"},
                "country": {"type": "string"},
            },
            "required": ["city", "country"],
            "additionalProperties": False,
        }
        prompt = (
            f"Return ONLY JSON with keys city and country. "
            f"Values must be city='{city}' and country='{country}'."
        )
        expected_answer = json.dumps(schema, separators=(",", ":"))
        oracle_type = "json_schema"
        metadata = {"schema": schema, "source": "synthetic", "target_city": city, "target_country": country}

    elif category == "instruction_following":
        tokens = ["ALPHA", "BETA", "GAMMA", "DELTA"]
        token = tokens[local_index % len(tokens)]
        prompt = f"Repeat exactly one token: {token}. Output only that token."
        expected_answer = token.lower()
        oracle_type = "keyword_match"
        metadata = {"keywords": [token.lower()], "mode": "all", "source": "synthetic"}

    elif category == "consistency_check":
        statements = [
            ("All mammals are warm-blooded. Whales are mammals.", "consistent"),
            ("All birds can fly. Penguins are birds that cannot fly.", "inconsistent"),
            ("Every square is a rectangle. Some rectangles are squares.", "consistent"),
        ]
        statement, label = statements[local_index % len(statements)]
        prompt = f"Respond with 'consistent' or 'inconsistent': {statement}"
        expected_answer = label
        oracle_type = "exact_match"
        metadata = {"labels": ["consistent", "inconsistent"], "source": "synthetic"}

    else:
        raise ValueError(f"Unsupported category: {category}")

    return TestCase(
        id=case_id,
        dataset_version=dataset_version,
        category=category,
        difficulty=difficulty,
        prompt=prompt,
        expected_answer=expected_answer,
        oracle_type=oracle_type,
        metadata=metadata,
    )
