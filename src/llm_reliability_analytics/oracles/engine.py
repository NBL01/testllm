import json
import re
from abc import ABC, abstractmethod
from typing import Any

from jsonschema import ValidationError as JsonSchemaValidationError
from jsonschema import validate
from pydantic import BaseModel

from llm_reliability_analytics.oracles.normalization import normalize_answer


class OracleEvaluation(BaseModel):
    is_correct: bool
    score: float
    explanation: str | None = None


class BaseOracle(ABC):
    @abstractmethod
    def evaluate(
        self,
        expected_answer: str,
        actual_answer: str | None,
        metadata: dict[str, Any] | None = None,
    ) -> OracleEvaluation:
        """Evaluate actual answer against the expected answer."""


class ExactMatchOracle(BaseOracle):
    def evaluate(
        self,
        expected_answer: str,
        actual_answer: str | None,
        metadata: dict[str, Any] | None = None,
    ) -> OracleEvaluation:
        metadata = metadata or {}
        actual_normalized = normalize_answer(actual_answer)
        valid_answers = _extract_valid_answers(expected_answer, metadata)
        normalized_candidates = [normalize_answer(answer) for answer in valid_answers if normalize_answer(answer)]
        if not normalized_candidates:
            return OracleEvaluation(
                is_correct=False,
                score=0.0,
                explanation="No valid expected answers were provided",
            )

        if actual_normalized in normalized_candidates:
            return OracleEvaluation(
                is_correct=True,
                score=1.0,
                explanation="Exact match after normalization",
            )

        best_similarity = max(
            _token_overlap_score(candidate, actual_normalized)
            for candidate in normalized_candidates
        )
        partial_threshold = float(metadata.get("partial_threshold", 0.85))
        partial_as_correct = bool(metadata.get("partial_as_correct", False))
        is_correct = partial_as_correct and best_similarity >= partial_threshold
        return OracleEvaluation(
            is_correct=is_correct,
            score=best_similarity,
            explanation=(
                "Exact match not found. "
                f"Best normalized overlap score={best_similarity:.3f}"
            ),
        )


class RegexMatchOracle(BaseOracle):
    def evaluate(
        self,
        expected_answer: str,
        actual_answer: str | None,
        metadata: dict[str, Any] | None = None,
    ) -> OracleEvaluation:
        metadata = metadata or {}
        flags = re.IGNORECASE if metadata.get("ignore_case", True) else 0
        strict_patterns = bool(metadata.get("strict_patterns", True))
        mode = str(metadata.get("mode", "any")).lower()

        patterns = metadata.get("valid_patterns")
        if patterns is None:
            patterns = [part.strip() for part in expected_answer.split("||") if part.strip()]
        if not patterns:
            return OracleEvaluation(
                is_correct=False,
                score=0.0,
                explanation="No regex patterns provided",
            )

        actual_text = actual_answer or ""
        total_patterns = len(patterns)
        matched_count = 0
        invalid_patterns: list[str] = []

        for pattern in patterns:
            try:
                if re.search(str(pattern), actual_text, flags=flags):
                    matched_count += 1
            except re.error:
                invalid_patterns.append(str(pattern))

        score = matched_count / total_patterns if total_patterns else 0.0
        base_correct = matched_count == total_patterns if mode == "all" else matched_count > 0
        is_correct = base_correct and (not invalid_patterns or not strict_patterns)

        explanation_parts = [f"Matched {matched_count}/{total_patterns} patterns"]
        if invalid_patterns:
            explanation_parts.append(f"invalid_patterns={invalid_patterns}")
        return OracleEvaluation(is_correct=is_correct, score=score, explanation=", ".join(explanation_parts))


class KeywordMatchOracle(BaseOracle):
    def evaluate(
        self,
        expected_answer: str,
        actual_answer: str | None,
        metadata: dict[str, Any] | None = None,
    ) -> OracleEvaluation:
        metadata = metadata or {}
        raw_keywords = metadata.get("keywords")
        if not raw_keywords:
            raw_keywords = [keyword.strip() for keyword in expected_answer.replace("||", ",").split(",") if keyword.strip()]
        keywords = [normalize_answer(str(keyword)) for keyword in raw_keywords if normalize_answer(str(keyword))]

        if not keywords:
            return OracleEvaluation(
                is_correct=False,
                score=0.0,
                explanation="No keywords provided",
            )

        actual_normalized = normalize_answer(actual_answer)
        matched_keywords = [keyword for keyword in keywords if keyword in actual_normalized]
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
        actual_answer: str | None,
        metadata: dict[str, Any] | None = None,
    ) -> OracleEvaluation:
        metadata = metadata or {}
        tolerance = float(metadata.get("tolerance", 0.0))

        expected_candidates = _extract_valid_answers(expected_answer, metadata)
        expected_values = [parsed for parsed in (_parse_number(candidate) for candidate in expected_candidates) if parsed is not None]
        actual_value = _parse_number(actual_answer or "")
        if not expected_values or actual_value is None:
            return OracleEvaluation(
                is_correct=False,
                score=0.0,
                explanation="Could not parse numeric values",
            )

        difference = min(abs(expected_value - actual_value) for expected_value in expected_values)
        is_correct = difference <= tolerance
        if is_correct:
            score = 1.0
        else:
            denominator = max(max(abs(expected_value) for expected_value in expected_values), 1.0)
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
        actual_answer: str | None,
        metadata: dict[str, Any] | None = None,
    ) -> OracleEvaluation:
        metadata = metadata or {}
        try:
            schema = _get_schema(expected_answer=expected_answer, metadata=metadata)
        except ValueError as exc:
            return OracleEvaluation(is_correct=False, score=0.0, explanation=str(exc))

        try:
            candidate_json = json.loads(actual_answer or "")
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


class SemanticSimilarityOracle(BaseOracle):
    """Simple placeholder semantic similarity using token overlap."""

    def evaluate(
        self,
        expected_answer: str,
        actual_answer: str | None,
        metadata: dict[str, Any] | None = None,
    ) -> OracleEvaluation:
        metadata = metadata or {}
        threshold = float(metadata.get("similarity_threshold", 0.7))
        actual_normalized = normalize_answer(actual_answer)
        candidates = _extract_valid_answers(expected_answer, metadata)
        normalized_candidates = [normalize_answer(candidate) for candidate in candidates if normalize_answer(candidate)]
        if not normalized_candidates:
            return OracleEvaluation(is_correct=False, score=0.0, explanation="No expected answers provided")

        best_score = max(
            _token_overlap_score(candidate, actual_normalized)
            for candidate in normalized_candidates
        )
        return OracleEvaluation(
            is_correct=best_score >= threshold,
            score=best_score,
            explanation=(
                "Semantic similarity placeholder based on token overlap. "
                f"score={best_score:.3f}, threshold={threshold:.3f}"
            ),
        )


class CompositeRuleOracle(BaseOracle):
    """Composite validator combining keyword and regex rules."""

    def evaluate(
        self,
        expected_answer: str,
        actual_answer: str | None,
        metadata: dict[str, Any] | None = None,
    ) -> OracleEvaluation:
        metadata = metadata or {}
        actual_text = actual_answer or ""
        actual_normalized = normalize_answer(actual_text)
        flags = re.IGNORECASE if metadata.get("ignore_case", True) else 0

        must_contain = [normalize_answer(value) for value in metadata.get("must_contain", []) if normalize_answer(value)]
        forbidden_keywords = [normalize_answer(value) for value in metadata.get("forbidden_keywords", []) if normalize_answer(value)]
        regex_constraints = [str(pattern).strip() for pattern in metadata.get("regex_constraints", []) if str(pattern).strip()]

        if not must_contain and expected_answer.strip():
            must_contain = [normalize_answer(part) for part in expected_answer.split("||") if normalize_answer(part)]

        must_hits = [keyword for keyword in must_contain if keyword in actual_normalized]
        forbidden_hits = [keyword for keyword in forbidden_keywords if keyword in actual_normalized]

        regex_hits = 0
        invalid_patterns: list[str] = []
        for pattern in regex_constraints:
            try:
                if re.search(pattern, actual_text, flags=flags):
                    regex_hits += 1
            except re.error:
                invalid_patterns.append(pattern)

        must_score = (len(must_hits) / len(must_contain)) if must_contain else 1.0
        forbidden_score = (
            max(0.0, 1.0 - (len(forbidden_hits) / len(forbidden_keywords)))
            if forbidden_keywords
            else 1.0
        )
        regex_score = (regex_hits / len(regex_constraints)) if regex_constraints else 1.0

        score = (must_score + forbidden_score + regex_score) / 3
        is_correct = (
            must_score == 1.0
            and forbidden_score == 1.0
            and regex_score == 1.0
            and not invalid_patterns
        )

        explanation = (
            f"must={len(must_hits)}/{len(must_contain) if must_contain else 0}, "
            f"forbidden_hits={len(forbidden_hits)}, "
            f"regex={regex_hits}/{len(regex_constraints) if regex_constraints else 0}"
        )
        if invalid_patterns:
            explanation += f", invalid_patterns={invalid_patterns}"

        return OracleEvaluation(is_correct=is_correct, score=score, explanation=explanation)


class OracleFactory:
    _registry: dict[str, type[BaseOracle]] = {
        "exact_match": ExactMatchOracle,
        "regex_match": RegexMatchOracle,
        "keyword_match": KeywordMatchOracle,
        "numeric_tolerance": NumericToleranceOracle,
        "json_schema": JsonSchemaOracle,
        "semantic_similarity": SemanticSimilarityOracle,
        "composite_rule": CompositeRuleOracle,
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
    actual_answer: str | None,
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


def _extract_valid_answers(expected_answer: str, metadata: dict[str, Any]) -> list[str]:
    candidates = metadata.get("valid_answers")
    if candidates is None:
        candidates = [part.strip() for part in expected_answer.split("||") if part.strip()]
    elif isinstance(candidates, str):
        candidates = [part.strip() for part in candidates.split("||") if part.strip()]
    elif isinstance(candidates, (list, tuple, set)):
        candidates = [str(value).strip() for value in candidates if str(value).strip()]
    else:
        candidates = [expected_answer]

    return list(candidates) if candidates else [expected_answer]


def _token_overlap_score(expected: str, actual: str) -> float:
    expected_tokens = set(_tokenize(expected))
    actual_tokens = set(_tokenize(actual))
    if not expected_tokens and not actual_tokens:
        return 1.0
    if not expected_tokens or not actual_tokens:
        return 0.0
    return len(expected_tokens.intersection(actual_tokens)) / len(expected_tokens.union(actual_tokens))


def _tokenize(text: str) -> list[str]:
    return re.findall(r"[a-z0-9]+", text.lower())


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
