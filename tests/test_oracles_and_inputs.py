"""Oracle and job-input property tests written by an agy agent run (2026-11-21); its findings on invalid
schemas and unbounded repeat counts are fixed. Dataset paths outside the repository remain allowed by
design (trusted local operators), so that probe is not kept here."""

"""Focused edge cases and boundary tests for evaluation oracles and job creation validation."""

import json
import pytest
from fastapi.testclient import TestClient

from llm_reliability_analytics.main import app
from llm_reliability_analytics.oracles.engine import (
    CompositeRuleOracle,
    ExactMatchOracle,
    JsonSchemaOracle,
    KeywordMatchOracle,
    NumericToleranceOracle,
    OracleFactory,
    RegexMatchOracle,
    SemanticSimilarityOracle,
)


# ---------------------------------------------------------------------------
# 1. RegexMatchOracle: search vs fullmatch, invalid patterns, ignore_case
# ---------------------------------------------------------------------------

def test_regex_match_oracle_uses_search_semantics() -> None:
    oracle = RegexMatchOracle()
    # Unanchored pattern matches as a substring inside actual_answer
    res = oracle.evaluate(expected_answer=r"\d{3}", actual_answer="Order id is 123 completed")
    assert res.is_correct is True
    assert res.score == 1.0
    assert res.error_type is None
    assert res.details["matched_count"] == 1


def test_regex_match_oracle_anchored_requires_fullmatch() -> None:
    oracle = RegexMatchOracle()
    # Anchored pattern behaves like fullmatch
    res_pass = oracle.evaluate(expected_answer=r"^\d{3}$", actual_answer="123")
    assert res_pass.is_correct is True
    assert res_pass.score == 1.0

    res_fail = oracle.evaluate(expected_answer=r"^\d{3}$", actual_answer="order-123")
    assert res_fail.is_correct is False
    assert res_fail.score == 0.0
    assert res_fail.error_type == "wrong_answer"


def test_regex_match_oracle_invalid_patterns_clean_error() -> None:
    oracle = RegexMatchOracle()
    # Invalid regex pattern does not raise; returns invalid_regex_pattern cleanly
    res = oracle.evaluate(
        expected_answer=r"[a-z+(",
        actual_answer="abc",
        metadata={"strict_patterns": True},
    )
    assert res.is_correct is False
    assert res.score == 0.0
    assert res.error_type == "invalid_regex_pattern"
    assert "invalid_patterns" in res.details
    assert r"[a-z+(" in res.details["invalid_patterns"]


def test_regex_match_oracle_invalid_pattern_lenient_mode() -> None:
    oracle = RegexMatchOracle()
    # With strict_patterns=False and mode=any, a valid pattern can still succeed
    res = oracle.evaluate(
        expected_answer=r"abc||[0-9+(",
        actual_answer="abc",
        metadata={"strict_patterns": False, "mode": "any"},
    )
    assert res.is_correct is True
    assert res.error_type is None
    assert res.details["invalid_patterns"] == [r"[0-9+("]


def test_regex_match_oracle_ignore_case_metadata() -> None:
    oracle = RegexMatchOracle()
    # Default is ignore_case=True
    res_default = oracle.evaluate(expected_answer=r"^token$", actual_answer="TOKEN")
    assert res_default.is_correct is True

    # Explicit ignore_case=True
    res_case_insensitive = oracle.evaluate(
        expected_answer=r"^token$",
        actual_answer="TOKEN",
        metadata={"ignore_case": True},
    )
    assert res_case_insensitive.is_correct is True

    # Explicit ignore_case=False
    res_case_sensitive = oracle.evaluate(
        expected_answer=r"^token$",
        actual_answer="TOKEN",
        metadata={"ignore_case": False},
    )
    assert res_case_sensitive.is_correct is False
    assert res_case_sensitive.error_type == "wrong_answer"


# ---------------------------------------------------------------------------
# 2. KeywordMatchOracle: mode all/any, case handling, substring semantics
# ---------------------------------------------------------------------------

def test_keyword_match_oracle_mode_all_and_any() -> None:
    oracle = KeywordMatchOracle()
    expected = "apple, banana, cherry"
    actual = "I bought an apple and a banana."

    # mode="all": missing "cherry" -> fails
    res_all = oracle.evaluate(expected_answer=expected, actual_answer=actual, metadata={"mode": "all"})
    assert res_all.is_correct is False
    assert pytest.approx(res_all.score, 0.01) == 2 / 3
    assert res_all.error_type == "wrong_answer"
    assert res_all.details["missing_keywords"] == ["cherry"]

    # mode="any": matches at least one -> passes
    res_any = oracle.evaluate(expected_answer=expected, actual_answer=actual, metadata={"mode": "any"})
    assert res_any.is_correct is True
    assert pytest.approx(res_any.score, 0.01) == 2 / 3
    assert res_any.error_type is None

    # mode="any": zero matches -> fails
    res_none = oracle.evaluate(expected_answer=expected, actual_answer="nothing here", metadata={"mode": "any"})
    assert res_none.is_correct is False
    assert res_none.score == 0.0
    assert res_none.error_type == "wrong_answer"


def test_keyword_match_oracle_case_handling() -> None:
    oracle = KeywordMatchOracle()
    # normalize_answer lowers case and strips punctuation
    res = oracle.evaluate(
        expected_answer="Artificial Intelligence, Deep Learning",
        actual_answer="ARTIFICIAL INTELLIGENCE and deep learning!",
        metadata={"mode": "all"},
    )
    assert res.is_correct is True
    assert res.score == 1.0
    assert res.error_type is None


def test_keyword_match_oracle_substring_in_word_semantics() -> None:
    oracle = KeywordMatchOracle()
    # In engine.py:307: found_keywords = [k for k in keywords if k in actual_normalized].
    # Inferred semantics from code: keywords use substring containment in normalized text,
    # which allows keyword stems (e.g. "cat" in "concatenate", or "refuse" in "refuses").
    res = oracle.evaluate(expected_answer="cat", actual_answer="concatenate")
    assert res.is_correct is True
    assert res.score == 1.0
    assert res.error_type is None
    assert "cat" in res.details["found_keywords"]


# ---------------------------------------------------------------------------
# 3. JsonSchemaOracle: valid, additionalProperties, fences, trailing, etc.
# ---------------------------------------------------------------------------

def test_json_schema_oracle_valid_json() -> None:
    oracle = JsonSchemaOracle()
    schema = {
        "type": "object",
        "properties": {"status": {"type": "string"}},
        "required": ["status"],
    }
    res = oracle.evaluate(expected_answer=json.dumps(schema), actual_answer='{"status": "ok"}')
    assert res.is_correct is True
    assert res.score == 1.0
    assert res.error_type is None
    assert res.details["parse_success"] is True
    assert res.details["schema_valid"] is True


def test_json_schema_oracle_additional_properties_false_with_extra_keys() -> None:
    oracle = JsonSchemaOracle()
    schema = {
        "type": "object",
        "properties": {"status": {"type": "string"}},
        "required": ["status"],
        "additionalProperties": False,
    }
    res = oracle.evaluate(
        expected_answer=json.dumps(schema),
        actual_answer='{"status": "ok", "unexpected_field": 123}',
    )
    assert res.is_correct is False
    assert res.score == 0.0
    assert res.error_type == "json_schema_validation_error"
    assert res.details["parse_success"] is True
    assert res.details["schema_valid"] is False
    assert "unexpected_field" in res.details["extra_fields"]


def test_json_schema_oracle_json_inside_markdown_fences() -> None:
    oracle = JsonSchemaOracle()
    schema = {"type": "object", "properties": {"a": {"type": "number"}}}
    actual_fenced = "```json\n{\"a\": 1}\n```"
    res = oracle.evaluate(expected_answer=json.dumps(schema), actual_answer=actual_fenced)
    # The oracle does strict JSON parsing; markdown fences fail json.loads cleanly
    assert res.is_correct is False
    assert res.score == 0.0
    assert res.error_type == "json_parse_error"
    assert res.details["parse_success"] is False


def test_json_schema_oracle_trailing_text() -> None:
    oracle = JsonSchemaOracle()
    schema = {"type": "object", "properties": {"a": {"type": "number"}}}
    actual_trailing = '{"a": 1}\nHere is an explanation of the result.'
    res = oracle.evaluate(expected_answer=json.dumps(schema), actual_answer=actual_trailing)
    assert res.is_correct is False
    assert res.score == 0.0
    assert res.error_type == "json_parse_error"
    assert res.details["parse_success"] is False


def test_json_schema_oracle_top_level_arrays() -> None:
    oracle = JsonSchemaOracle()
    schema = {"type": "array", "items": {"type": "string"}}
    res_pass = oracle.evaluate(expected_answer=json.dumps(schema), actual_answer='["hello", "world"]')
    assert res_pass.is_correct is True
    assert res_pass.score == 1.0

    # Schema expects array, actual is object
    res_fail = oracle.evaluate(expected_answer=json.dumps(schema), actual_answer='{"hello": "world"}')
    assert res_fail.is_correct is False
    assert res_fail.error_type == "json_schema_validation_error"


def test_json_schema_oracle_numbers_as_strings() -> None:
    oracle = JsonSchemaOracle()
    schema = {
        "type": "object",
        "properties": {"score": {"type": "number"}},
        "required": ["score"],
    }
    # "0.85" as a string is not of type number
    res = oracle.evaluate(expected_answer=json.dumps(schema), actual_answer='{"score": "0.85"}')
    assert res.is_correct is False
    assert res.score == 0.0
    assert res.error_type == "json_schema_validation_error"


def test_json_schema_oracle_invalid_json_in_expected_answer() -> None:
    oracle = JsonSchemaOracle()
    res = oracle.evaluate(expected_answer="not a valid json {", actual_answer='{"status": "ok"}')
    assert res.is_correct is False
    assert res.score == 0.0
    assert res.error_type == "invalid_oracle_config"


def test_json_schema_oracle_semantically_invalid_schema_in_expected_answer() -> None:
    oracle = JsonSchemaOracle()
    # A JSON object that is not a valid JSON schema (e.g. invalid type identifier)
    # The oracle should handle SchemaError cleanly without bubbling an unhandled exception
    res = oracle.evaluate(expected_answer='{"type": 123}', actual_answer='{"status": "ok"}')
    assert res.is_correct is False
    assert res.score == 0.0
    assert res.error_type in {"invalid_oracle_config", "json_schema_validation_error"}


# ---------------------------------------------------------------------------
# 4. SemanticSimilarityOracle & CompositeRuleOracle: thresholds, empty, etc.
# ---------------------------------------------------------------------------

def test_semantic_similarity_oracle_threshold_boundaries() -> None:
    oracle = SemanticSimilarityOracle()
    # 2 matching tokens out of 4 total unique tokens: overlap = 2/4 = 0.5
    expected = "token1 token2 token3"
    actual = "token1 token2 token4"

    res_at_boundary = oracle.evaluate(
        expected_answer=expected,
        actual_answer=actual,
        metadata={"similarity_threshold": 0.5},
    )
    assert res_at_boundary.score == 0.5
    assert res_at_boundary.is_correct is True
    assert res_at_boundary.error_type is None

    res_above_boundary = oracle.evaluate(
        expected_answer=expected,
        actual_answer=actual,
        metadata={"similarity_threshold": 0.501},
    )
    assert res_above_boundary.score == 0.5
    assert res_above_boundary.is_correct is False
    assert res_above_boundary.error_type == "wrong_answer"


def test_semantic_similarity_oracle_empty_actual() -> None:
    oracle = SemanticSimilarityOracle()
    for empty_val in ("", None):
        res = oracle.evaluate(expected_answer="expected output", actual_answer=empty_val)
        assert res.is_correct is False
        assert res.score == 0.0
        assert res.error_type == "wrong_answer"


def test_composite_rule_oracle_empty_actual() -> None:
    oracle = CompositeRuleOracle()
    metadata = {
        "must_contain": ["order"],
        "forbidden_keywords": ["cancelled"],
        "regex_constraints": [r"ORD-\d+"],
    }
    for empty_val in ("", None):
        res = oracle.evaluate(expected_answer="", actual_answer=empty_val, metadata=metadata)
        assert res.is_correct is False
        # must=0, forbidden=1, regex=0 -> score = 1/3
        assert pytest.approx(res.score, 0.01) == 1 / 3
        assert res.error_type == "wrong_answer"


def test_composite_rule_oracle_forbidden_keywords() -> None:
    oracle = CompositeRuleOracle()
    metadata = {
        "must_contain": ["order", "placed"],
        "forbidden_keywords": ["fraud", "declined"],
        "regex_constraints": [],
    }
    res = oracle.evaluate(
        expected_answer="",
        actual_answer="Order placed successfully, but flagged as fraud.",
        metadata=metadata,
    )
    assert res.is_correct is False
    assert res.error_type == "wrong_answer"
    assert "fraud" in res.details["forbidden_hits"]


def test_composite_rule_oracle_regex_constraints_and_invalid_pattern() -> None:
    oracle = CompositeRuleOracle()
    # Missing regex pattern
    res_missing = oracle.evaluate(
        expected_answer="",
        actual_answer="order without id",
        metadata={"must_contain": ["order"], "regex_constraints": [r"ORD-\d{4}"]},
    )
    assert res_missing.is_correct is False
    assert res_missing.error_type == "wrong_answer"

    # Invalid regex pattern cleanly flagged
    res_invalid = oracle.evaluate(
        expected_answer="",
        actual_answer="order ORD-1234",
        metadata={"must_contain": ["order"], "regex_constraints": [r"(?P<invalid"]},
    )
    assert res_invalid.is_correct is False
    assert res_invalid.error_type == "invalid_regex_pattern"
    assert r"(?P<invalid" in res_invalid.details["invalid_patterns"]


# ---------------------------------------------------------------------------
# 5. Invariants for every oracle class: None/"" safe, score in [0, 1], etc.
# ---------------------------------------------------------------------------

ALL_ORACLE_NAMES = [
    "exact_match",
    "regex_match",
    "keyword_match",
    "numeric_tolerance",
    "json_schema",
    "semantic_similarity",
    "composite_rule",
]


@pytest.mark.parametrize("oracle_name", ALL_ORACLE_NAMES)
@pytest.mark.parametrize("actual_input", [None, ""])
def test_every_oracle_none_and_empty_actual_never_raise(oracle_name: str, actual_input: str | None) -> None:
    oracle = OracleFactory.create(oracle_name)
    expected_answer = "100" if oracle_name != "json_schema" else '{"type": "object"}'

    res = oracle.evaluate(expected_answer=expected_answer, actual_answer=actual_input)

    assert isinstance(res.is_correct, bool)
    assert isinstance(res.score, (int, float))
    assert 0.0 <= res.score <= 1.0
    if res.is_correct:
        assert res.error_type is None
    else:
        assert res.error_type is not None


@pytest.mark.parametrize("oracle_name", ALL_ORACLE_NAMES)
def test_every_oracle_is_correct_true_implies_error_type_none(oracle_name: str) -> None:
    oracle = OracleFactory.create(oracle_name)
    # Valid matching pair for each oracle
    pairs = {
        "exact_match": ("paris", "paris", {}),
        "regex_match": (r"^\d+$", "123", {}),
        "keyword_match": ("apple, orange", "apple and orange", {}),
        "numeric_tolerance": ("42", "42", {"tolerance": 0.0}),
        "json_schema": ('{"type": "object"}', "{}", {}),
        "semantic_similarity": ("test sentence", "test sentence", {"similarity_threshold": 0.5}),
        "composite_rule": ("", "order completed", {"must_contain": ["order"]}),
    }
    exp, act, meta = pairs[oracle_name]
    res = oracle.evaluate(expected_answer=exp, actual_answer=act, metadata=meta)
    assert res.is_correct is True
    assert res.error_type is None
    assert 0.0 <= res.score <= 1.0


# ---------------------------------------------------------------------------
# 6. POST /evaluation-jobs validation: temperature, tokens, timeouts, limits, etc.
# ---------------------------------------------------------------------------

def test_evaluation_job_create_temperature_validation(monkeypatch, tmp_path) -> None:
    monkeypatch.setenv("LLM_RELIABILITY_DB_PATH", str(tmp_path / "temp.duckdb"))
    client = TestClient(app)

    # temperature -1 -> rejected by ge=0
    res_neg = client.post("/evaluation-jobs", json={"input_path": "sample_test_cases.jsonl", "temperature": -1})
    assert res_neg.status_code == 422

    # temperature NaN (as string in JSON payload) -> rejected by allow_inf_nan=False
    res_nan_str = client.post(
        "/evaluation-jobs",
        json={"input_path": "sample_test_cases.jsonl", "temperature": "NaN"},
    )
    assert res_nan_str.status_code == 422

    # temperature inf (as string in JSON payload) -> rejected by allow_inf_nan=False
    res_inf_str = client.post(
        "/evaluation-jobs",
        json={"input_path": "sample_test_cases.jsonl", "temperature": "inf"},
    )
    assert res_inf_str.status_code == 422


def test_evaluation_job_create_max_output_tokens_validation(monkeypatch, tmp_path) -> None:
    monkeypatch.setenv("LLM_RELIABILITY_DB_PATH", str(tmp_path / "tokens.duckdb"))
    client = TestClient(app)

    # max_output_tokens 0 -> ge=1 violation
    res_zero = client.post("/evaluation-jobs", json={"input_path": "sample_test_cases.jsonl", "max_output_tokens": 0})
    assert res_zero.status_code == 422

    # max_output_tokens 1025 -> le=1024 violation
    res_high = client.post("/evaluation-jobs", json={"input_path": "sample_test_cases.jsonl", "max_output_tokens": 1025})
    assert res_high.status_code == 422


def test_evaluation_job_create_timeout_seconds_validation(monkeypatch, tmp_path) -> None:
    monkeypatch.setenv("LLM_RELIABILITY_DB_PATH", str(tmp_path / "timeout.duckdb"))
    client = TestClient(app)

    # timeout_seconds 4.9 -> ge=5.0 violation
    res_low = client.post("/evaluation-jobs", json={"input_path": "sample_test_cases.jsonl", "timeout_seconds": 4.9})
    assert res_low.status_code == 422

    # timeout_seconds 300.1 -> le=300.0 violation
    res_high = client.post("/evaluation-jobs", json={"input_path": "sample_test_cases.jsonl", "timeout_seconds": 300.1})
    assert res_high.status_code == 422


def test_evaluation_job_create_repeat_count_validation(monkeypatch, tmp_path) -> None:
    monkeypatch.setenv("LLM_RELIABILITY_DB_PATH", str(tmp_path / "repeat.duckdb"))
    client = TestClient(app)

    # repeat_count 0 -> ge=1 violation
    res_zero = client.post("/evaluation-jobs", json={"input_path": "sample_test_cases.jsonl", "repeat_count": 0})
    assert res_zero.status_code == 422

    # repeat_count -1 -> ge=1 violation
    res_neg = client.post("/evaluation-jobs", json={"input_path": "sample_test_cases.jsonl", "repeat_count": -1})
    assert res_neg.status_code == 422


def test_evaluation_job_create_repeat_count_unbounded_upper_bound(monkeypatch, tmp_path) -> None:
    monkeypatch.setenv("LLM_RELIABILITY_DB_PATH", str(tmp_path / "repeat_unbounded.duckdb"))
    client = TestClient(app)

    # 1,000,000 repeats multiplies evaluation work unboundedly and should be rejected
    res = client.post("/evaluation-jobs", json={"input_path": "sample_test_cases.jsonl", "repeat_count": 1000000})
    assert res.status_code in {400, 422}


def test_evaluation_job_create_limit_validation(monkeypatch, tmp_path) -> None:
    monkeypatch.setenv("LLM_RELIABILITY_DB_PATH", str(tmp_path / "limit.duckdb"))
    client = TestClient(app)

    # limit 0 -> ge=1 violation
    res_zero = client.post("/evaluation-jobs", json={"input_path": "sample_test_cases.jsonl", "limit": 0})
    assert res_zero.status_code == 422

    # limit -1 -> ge=1 violation
    res_neg = client.post("/evaluation-jobs", json={"input_path": "sample_test_cases.jsonl", "limit": -1})
    assert res_neg.status_code == 422


def test_evaluation_job_create_input_path_traversal_and_txt_rejected(monkeypatch, tmp_path) -> None:
    monkeypatch.setenv("LLM_RELIABILITY_DB_PATH", str(tmp_path / "path_reject.duckdb"))
    client = TestClient(app)

    # Traversal to /etc/passwd
    res_passwd = client.post("/evaluation-jobs", json={"input_path": "../../etc/passwd"})
    assert res_passwd.status_code == 400

    # .txt file rejected (must be jsonl or csv)
    txt_file = tmp_path / "test.txt"
    txt_file.write_text("sample content")
    res_txt = client.post("/evaluation-jobs", json={"input_path": str(txt_file)})
    assert res_txt.status_code == 400


