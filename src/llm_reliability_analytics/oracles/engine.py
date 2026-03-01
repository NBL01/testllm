import json
import re
from abc import ABC, abstractmethod
from typing import Any

from jsonschema import ValidationError as JsonSchemaValidationError
from jsonschema import validate
from pydantic import BaseModel


class OracleEvaluation(BaseModel):
    is_correct: bool
    score: float
    explanation: str | None = None


class BaseOracle(ABC):
    @abstractmethod
    def evaluate(
        self,
        expected_answer: str,
        actual_answer: str,
        metadata: dict[str, Any] | None = None,
    ) -> OracleEvaluation:
        """Evaluate actual answer against the expected answer."""


class ExactMatchOracle(BaseOracle):
    def evaluate(
        self,
        expected_answer: str,
        actual_answer: str,
        metadata: dict[str, Any] | None = None,
    ) -> OracleEvaluation:
        expected = expected_answer.strip().lower()
        actual = actual_answer.strip().lower()
        is_correct = expected == actual
        return OracleEvaluation(
            is_correct=is_correct,
            score=1.0 if is_correct else 0.0,
            explanation="Exact string match" if is_correct else "Answers differ",
        )


class RegexMatchOracle(BaseOracle):
    def evaluate(
        self,
        expected_answer: str,
        actual_answer: str,
        metadata: dict[str, Any] | None = None,
    ) -> OracleEvaluation:
        flags = re.IGNORECASE if (metadata or {}).get("ignore_case", True) else 0
        try:
            matched = re.search(expected_answer, actual_answer, flags=flags) is not None
        except re.error as exc:
            return OracleEvaluation(
                is_correct=False,
                score=0.0,
                explanation=f"Invalid regex pattern: {exc}",
            )
        return OracleEvaluation(
            is_correct=matched,
            score=1.0 if matched else 0.0,
            explanation="Regex matched" if matched else "Regex did not match",
        )


class KeywordMatchOracle(BaseOracle):
    def evaluate(
        self,
        expected_answer: str,
        actual_answer: str,
        metadata: dict[str, Any] | None = None,
    ) -> OracleEvaluation:
        metadata = metadata or {}
        raw_keywords = metadata.get("keywords")
        if not raw_keywords:
            raw_keywords = [keyword.strip() for keyword in expected_answer.split(",") if keyword.strip()]
        keywords = [str(keyword).strip().lower() for keyword in raw_keywords if str(keyword).strip()]

        if not keywords:
            return OracleEvaluation(
                is_correct=False,
                score=0.0,
                explanation="No keywords provided",
            )

        actual_lower = actual_answer.lower()
        matched_keywords = [keyword for keyword in keywords if keyword in actual_lower]
        score = len(matched_keywords) / len(keywords)
        mode = str(metadata.get("mode", "all")).lower()

        is_correct = score == 1.0 if mode == "all" else len(matched_keywords) > 0
        explanation = (
            f"Matched {len(matched_keywords)}/{len(keywords)} keywords: {matched_keywords}"
        )
        return OracleEvaluation(is_correct=is_correct, score=score, explanation=explanation)


class NumericToleranceOracle(BaseOracle):
    def evaluate(
        self,
        expected_answer: str,
        actual_answer: str,
        metadata: dict[str, Any] | None = None,
    ) -> OracleEvaluation:
        metadata = metadata or {}
        tolerance = float(metadata.get("tolerance", 0.0))

        expected_value = _parse_number(expected_answer)
        actual_value = _parse_number(actual_answer)
        if expected_value is None or actual_value is None:
            return OracleEvaluation(
                is_correct=False,
                score=0.0,
                explanation="Could not parse numeric values",
            )

        difference = abs(expected_value - actual_value)
        is_correct = difference <= tolerance
        if is_correct:
            score = 1.0
        else:
            denominator = max(abs(expected_value), 1.0)
            score = max(0.0, 1.0 - (difference / denominator))

        return OracleEvaluation(
            is_correct=is_correct,
            score=score,
            explanation=(
                f"Difference={difference:.6f}, tolerance={tolerance:.6f}"
            ),
        )


class JsonSchemaOracle(BaseOracle):
    def evaluate(
        self,
        expected_answer: str,
        actual_answer: str,
        metadata: dict[str, Any] | None = None,
    ) -> OracleEvaluation:
        metadata = metadata or {}
        try:
            schema = _get_schema(expected_answer=expected_answer, metadata=metadata)
        except ValueError as exc:
            return OracleEvaluation(is_correct=False, score=0.0, explanation=str(exc))

        try:
            candidate_json = json.loads(actual_answer)
        except json.JSONDecodeError as exc:
            return OracleEvaluation(
                is_correct=False,
                score=0.0,
                explanation=f"Invalid JSON answer: {exc}",
            )

        try:
            validate(instance=candidate_json, schema=schema)
        except JsonSchemaValidationError as exc:
            return OracleEvaluation(
                is_correct=False,
                score=0.0,
                explanation=f"Schema validation failed: {exc.message}",
            )

        return OracleEvaluation(
            is_correct=True,
            score=1.0,
            explanation="JSON matches schema",
        )


class OracleFactory:
    _registry: dict[str, type[BaseOracle]] = {
        "exact_match": ExactMatchOracle,
        "regex_match": RegexMatchOracle,
        "keyword_match": KeywordMatchOracle,
        "numeric_tolerance": NumericToleranceOracle,
        "json_schema": JsonSchemaOracle,
    }

    @classmethod
    def create(cls, oracle_type: str) -> BaseOracle:
        normalized_type = oracle_type.strip().lower()
        if normalized_type not in cls._registry:
            available = ", ".join(sorted(cls._registry.keys()))
            raise ValueError(f"Unsupported oracle_type '{oracle_type}'. Available: {available}")
        return cls._registry[normalized_type]()


def evaluate_with_oracle(
    oracle_type: str,
    expected_answer: str,
    actual_answer: str,
    metadata: dict[str, Any] | None = None,
) -> OracleEvaluation:
    oracle = OracleFactory.create(oracle_type)
    return oracle.evaluate(expected_answer=expected_answer, actual_answer=actual_answer, metadata=metadata)


def _parse_number(value: str) -> float | None:
    try:
        return float(value.strip())
    except (AttributeError, ValueError):
        number_match = re.search(r"-?\d+(\.\d+)?", str(value))
        if number_match is None:
            return None
        return float(number_match.group(0))


def _get_schema(expected_answer: str, metadata: dict[str, Any]) -> dict[str, Any]:
    schema = metadata.get("schema")
    if isinstance(schema, dict):
        return schema
    if isinstance(schema, str):
        try:
            parsed = json.loads(schema)
        except json.JSONDecodeError as exc:
            raise ValueError("metadata['schema'] must contain valid JSON") from exc
        if not isinstance(parsed, dict):
            raise ValueError("metadata['schema'] must decode to a JSON object")
        return parsed

    try:
        parsed_expected = json.loads(expected_answer)
    except json.JSONDecodeError as exc:
        raise ValueError(
            "For json_schema oracle, provide schema in metadata['schema'] or expected_answer JSON"
        ) from exc
    if not isinstance(parsed_expected, dict):
        raise ValueError("Expected schema must be a JSON object")
    return parsed_expected
