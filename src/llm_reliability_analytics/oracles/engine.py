import json
import re
from abc import ABC, abstractmethod
from typing import Any

from jsonschema import ValidationError as JsonSchemaValidationError
from jsonschema import validate
from pydantic import BaseModel, Field

from llm_reliability_analytics.oracles.normalization import normalize_answer


class OracleEvaluation(BaseModel):
    is_correct: bool
    score: float
    error_type: str | None = None
    explanation: str | None = None
    details: dict[str, Any] = Field(default_factory=dict)


class BaseOracle(ABC):
    @abstractmethod
    def evaluate(
        self,
        expected_answer: str,
        actual_answer: str | None,
        metadata: dict[str, Any] | None = None,
    ) -> OracleEvaluation:
        """Evaluate actual answer against expected answer and return trace details."""


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
        strict_exact = bool(metadata.get("strict_exact", False))
        allow_substring_match = bool(metadata.get("allow_substring_match", not strict_exact))
        number_tolerance = float(metadata.get("number_tolerance", 0.0))

        if not normalized_candidates:
            return OracleEvaluation(
                is_correct=False,
                score=0.0,
                error_type="invalid_oracle_config",
                explanation="No valid expected answers were provided.",
                details={
                    "expected_normalized": [],
                    "actual_normalized": actual_normalized,
                    "comparison_result": "no_expected_candidates",
                    "strict_exact": strict_exact,
                },
            )

        matched_candidate = next((candidate for candidate in normalized_candidates if actual_normalized == candidate), None)
        if matched_candidate is not None:
            return OracleEvaluation(
                is_correct=True,
                score=1.0,
                error_type=None,
                explanation="Exact normalized match.",
                details={
                    "expected_normalized": normalized_candidates,
                    "actual_normalized": actual_normalized,
                    "comparison_result": "exact_match",
                    "matched_candidate": matched_candidate,
                    "strict_exact": strict_exact,
                },
            )

        if allow_substring_match:
            contained_candidate = next(
                (
                    candidate
                    for candidate in normalized_candidates
                    if _contains_normalized_phrase(actual_normalized, candidate)
                ),
                None,
            )
            if contained_candidate is not None:
                return OracleEvaluation(
                    is_correct=True,
                    score=1.0,
                    error_type=None,
                    explanation="Expected answer found in normalized model output.",
                    details={
                        "expected_normalized": normalized_candidates,
                        "actual_normalized": actual_normalized,
                        "comparison_result": "contains_match",
                        "matched_candidate": contained_candidate,
                        "strict_exact": strict_exact,
                    },
                )

        actual_value = _parse_number(actual_answer or "")
        numeric_candidates = [value for value in (_parse_number(candidate) for candidate in valid_answers) if value is not None]
        if actual_value is not None and numeric_candidates:
            closest_expected = min(numeric_candidates, key=lambda value: abs(value - actual_value))
            difference = abs(closest_expected - actual_value)
            if difference <= number_tolerance:
                return OracleEvaluation(
                    is_correct=True,
                    score=1.0,
                    error_type=None,
                    explanation="Numeric value matches expected answer within tolerance.",
                    details={
                        "expected_normalized": normalized_candidates,
                        "actual_normalized": actual_normalized,
                        "comparison_result": "numeric_equivalent",
                        "expected_value": closest_expected,
                        "actual_value": actual_value,
                        "absolute_difference": difference,
                        "number_tolerance": number_tolerance,
                        "strict_exact": strict_exact,
                    },
                )

        best_similarity = max(_token_overlap_score(candidate, actual_normalized) for candidate in normalized_candidates)
        partial_threshold = float(metadata.get("partial_threshold", 0.85))
        partial_as_correct = bool(metadata.get("partial_as_correct", False))
        is_correct = partial_as_correct and best_similarity >= partial_threshold
        comparison_result = "partial_match" if best_similarity > 0 else "no_match"

        return OracleEvaluation(
            is_correct=is_correct,
            score=best_similarity,
            error_type=None if is_correct else "wrong_answer",
            explanation=f"Exact match not found. Best overlap={best_similarity:.3f}.",
            details={
                "expected_normalized": normalized_candidates,
                "actual_normalized": actual_normalized,
                "comparison_result": comparison_result,
                "partial_threshold": partial_threshold,
                "partial_as_correct": partial_as_correct,
                "strict_exact": strict_exact,
            },
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
                error_type="invalid_oracle_config",
                explanation="No regex patterns provided.",
                details={"pattern": None, "matched": False, "extracted_groups": []},
            )

        actual_text = actual_answer or ""
        total_patterns = len(patterns)
        matched_count = 0
        invalid_patterns: list[str] = []
        matched_patterns: list[str] = []
        extracted_groups: dict[str, list[str]] = {}

        for pattern in patterns:
            pattern_text = str(pattern)
            try:
                match = re.search(pattern_text, actual_text, flags=flags)
                if match:
                    matched_count += 1
                    matched_patterns.append(pattern_text)
                    if match.groups():
                        extracted_groups[pattern_text] = [str(group) for group in match.groups()]
            except re.error:
                invalid_patterns.append(pattern_text)

        score = matched_count / total_patterns if total_patterns else 0.0
        base_correct = matched_count == total_patterns if mode == "all" else matched_count > 0
        is_correct = base_correct and (not invalid_patterns or not strict_patterns)
        if invalid_patterns and strict_patterns:
            error_type = "invalid_regex_pattern"
        elif is_correct:
            error_type = None
        else:
            error_type = "wrong_answer"

        explanation = f"Matched {matched_count}/{total_patterns} regex patterns."
        if invalid_patterns:
            explanation += f" invalid_patterns={invalid_patterns}"

        return OracleEvaluation(
            is_correct=is_correct,
            score=score,
            error_type=error_type,
            explanation=explanation,
            details={
                "pattern": patterns[0] if len(patterns) == 1 else patterns,
                "matched": bool(matched_count),
                "matched_count": matched_count,
                "total_patterns": total_patterns,
                "mode": mode,
                "invalid_patterns": invalid_patterns,
                "matched_patterns": matched_patterns,
                "extracted_groups": extracted_groups,
            },
        )


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
                error_type="invalid_oracle_config",
                explanation="No keywords provided.",
                details={
                    "required_keywords": [],
                    "found_keywords": [],
                    "missing_keywords": [],
                    "coverage": 0.0,
                    "threshold": 1.0,
                },
            )

        actual_normalized = normalize_answer(actual_answer)
        found_keywords = [keyword for keyword in keywords if keyword in actual_normalized]
        missing_keywords = [keyword for keyword in keywords if keyword not in found_keywords]
        coverage = len(found_keywords) / len(keywords)
        mode = str(metadata.get("mode", "all")).lower()
        threshold = float(metadata.get("threshold", 1.0 if mode == "all" else 0.01))

        if mode == "all":
            is_correct = coverage >= threshold and len(missing_keywords) == 0
        else:
            is_correct = coverage >= threshold and len(found_keywords) > 0

        return OracleEvaluation(
            is_correct=is_correct,
            score=coverage,
            error_type=None if is_correct else "wrong_answer",
            explanation=f"Matched {len(found_keywords)}/{len(keywords)} keywords.",
            details={
                "required_keywords": keywords,
                "found_keywords": found_keywords,
                "missing_keywords": missing_keywords,
                "coverage": coverage,
                "threshold": threshold,
                "mode": mode,
            },
        )


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
                error_type="numeric_parse_error",
                explanation="Could not parse numeric values.",
                details={
                    "expected_value": expected_values,
                    "actual_value": actual_value,
                    "absolute_difference": None,
                    "tolerance": tolerance,
                },
            )

        closest_expected = min(expected_values, key=lambda value: abs(value - actual_value))
        difference = abs(closest_expected - actual_value)
        is_correct = difference <= tolerance
        if is_correct:
            score = 1.0
        else:
            denominator = max(max(abs(expected_value) for expected_value in expected_values), 1.0)
            score = max(0.0, 1.0 - (difference / denominator))

        return OracleEvaluation(
            is_correct=is_correct,
            score=score,
            error_type=None if is_correct else "wrong_answer",
            explanation=f"Absolute difference={difference:.6f} (tolerance={tolerance:.6f}).",
            details={
                "expected_value": closest_expected,
                "all_expected_values": expected_values,
                "actual_value": actual_value,
                "absolute_difference": difference,
                "tolerance": tolerance,
            },
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
            return OracleEvaluation(
                is_correct=False,
                score=0.0,
                error_type="invalid_oracle_config",
                explanation=str(exc),
                details={
                    "parse_success": False,
                    "schema_valid": False,
                    "missing_fields": [],
                    "extra_fields": [],
                    "parse_error": str(exc),
                },
            )

        try:
            candidate_json = json.loads(actual_answer or "")
        except json.JSONDecodeError as exc:
            return OracleEvaluation(
                is_correct=False,
                score=0.0,
                error_type="json_parse_error",
                explanation=f"Invalid JSON output: {exc.msg}",
                details={
                    "parse_success": False,
                    "schema_valid": False,
                    "missing_fields": [],
                    "extra_fields": [],
                    "parse_error": str(exc),
                },
            )

        required_fields = _required_fields(schema)
        if isinstance(candidate_json, dict):
            keys = set(candidate_json.keys())
            missing_fields = sorted(required_fields - keys)
            extra_fields = sorted(keys - schema.get("properties", {}).keys()) if isinstance(schema.get("properties"), dict) else []
        else:
            missing_fields = sorted(required_fields)
            extra_fields = []

        try:
            validate(instance=candidate_json, schema=schema)
        except JsonSchemaValidationError as exc:
            return OracleEvaluation(
                is_correct=False,
                score=0.0,
                error_type="json_schema_validation_error",
                explanation=f"Schema validation failed: {exc.message}",
                details={
                    "parse_success": True,
                    "schema_valid": False,
                    "missing_fields": missing_fields,
                    "extra_fields": extra_fields,
                    "parse_error": None,
                },
            )

        return OracleEvaluation(
            is_correct=True,
            score=1.0,
            error_type=None,
            explanation="JSON output matches schema.",
            details={
                "parse_success": True,
                "schema_valid": True,
                "missing_fields": missing_fields,
                "extra_fields": extra_fields,
                "parse_error": None,
            },
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
            return OracleEvaluation(
                is_correct=False,
                score=0.0,
                error_type="invalid_oracle_config",
                explanation="No expected answers provided.",
                details={"similarity_threshold": threshold, "candidate_count": 0},
            )

        best_score = max(_token_overlap_score(candidate, actual_normalized) for candidate in normalized_candidates)
        is_correct = best_score >= threshold
        return OracleEvaluation(
            is_correct=is_correct,
            score=best_score,
            error_type=None if is_correct else "wrong_answer",
            explanation=(
                "Semantic similarity placeholder based on token overlap. "
                f"score={best_score:.3f}, threshold={threshold:.3f}"
            ),
            details={
                "similarity_threshold": threshold,
                "best_similarity": best_score,
                "comparison_type": "token_overlap_placeholder",
                "expected_candidates": normalized_candidates,
                "actual_normalized": actual_normalized,
            },
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
        must_misses = [keyword for keyword in must_contain if keyword not in must_hits]
        forbidden_hits = [keyword for keyword in forbidden_keywords if keyword in actual_normalized]

        regex_hits = 0
        invalid_patterns: list[str] = []
        matched_patterns: list[str] = []
        for pattern in regex_constraints:
            try:
                if re.search(pattern, actual_text, flags=flags):
                    regex_hits += 1
                    matched_patterns.append(pattern)
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
        error_type = "invalid_regex_pattern" if invalid_patterns else (None if is_correct else "wrong_answer")

        explanation = (
            f"must={len(must_hits)}/{len(must_contain) if must_contain else 0}, "
            f"forbidden_hits={len(forbidden_hits)}, "
            f"regex={regex_hits}/{len(regex_constraints) if regex_constraints else 0}"
        )
        if invalid_patterns:
            explanation += f", invalid_patterns={invalid_patterns}"

        return OracleEvaluation(
            is_correct=is_correct,
            score=score,
            error_type=error_type,
            explanation=explanation,
            details={
                "must_contain": must_contain,
                "must_hits": must_hits,
                "must_misses": must_misses,
                "forbidden_keywords": forbidden_keywords,
                "forbidden_hits": forbidden_hits,
                "regex_constraints": regex_constraints,
                "regex_hits": matched_patterns,
                "invalid_patterns": invalid_patterns,
            },
        )


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


def _contains_normalized_phrase(text: str, phrase: str) -> bool:
    if not text or not phrase:
        return False
    if text == phrase:
        return True
    text_tokens = text.split()
    phrase_tokens = phrase.split()
    phrase_len = len(phrase_tokens)
    if phrase_len == 0 or phrase_len > len(text_tokens):
        return False
    for index in range(len(text_tokens) - phrase_len + 1):
        if text_tokens[index : index + phrase_len] == phrase_tokens:
            return True
    return False


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


def _required_fields(schema: dict[str, Any]) -> set[str]:
    raw_required = schema.get("required")
    if not isinstance(raw_required, list):
        return set()
    return {str(field) for field in raw_required}
