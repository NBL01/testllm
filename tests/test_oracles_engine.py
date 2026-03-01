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


def test_exact_match_oracle_supports_normalization_and_multi_answers() -> None:
    oracle = ExactMatchOracle()
    result = oracle.evaluate(
        expected_answer="Paris || City of Paris",
        actual_answer="  city, of PARIS! ",
    )
    assert result.is_correct is True
    assert result.score == 1.0
    assert result.explanation is not None


def test_exact_match_oracle_partial_scoring() -> None:
    oracle = ExactMatchOracle()
    result = oracle.evaluate(
        expected_answer="capital of france",
        actual_answer="the capital france",
    )
    assert result.is_correct is False
    assert 0.0 < result.score < 1.0


def test_regex_match_oracle_with_multiple_patterns_partial_score() -> None:
    oracle = RegexMatchOracle()
    result = oracle.evaluate(
        expected_answer=r"^order-\d{3}$||invoice-\d{2}",
        actual_answer="order-123",
        metadata={"mode": "all"},
    )
    assert result.is_correct is False
    assert result.score == 0.5


def test_regex_match_oracle_invalid_pattern_edge_case() -> None:
    oracle = RegexMatchOracle()
    result = oracle.evaluate(
        expected_answer=r"order-\d+||(",
        actual_answer="order-123",
        metadata={"mode": "any", "strict_patterns": True},
    )
    assert result.is_correct is False
    assert result.score == 0.5
    assert "invalid_patterns" in (result.explanation or "")


def test_regex_match_oracle() -> None:
    oracle = RegexMatchOracle()
    result = oracle.evaluate(expected_answer=r"^order-\d{3}$", actual_answer="order-123")
    assert result.is_correct is True
    assert result.score == 1.0


def test_keyword_match_oracle() -> None:
    oracle = KeywordMatchOracle()
    result = oracle.evaluate(
        expected_answer="reliability, accuracy, latency",
        actual_answer="This report includes reliability and latency metrics.",
        metadata={"mode": "any"},
    )
    assert result.is_correct is True
    assert 0.0 < result.score < 1.0
    assert "Matched" in (result.explanation or "")


def test_keyword_match_uses_normalization() -> None:
    oracle = KeywordMatchOracle()
    result = oracle.evaluate(
        expected_answer="hello world",
        actual_answer="HELLO, world!!!",
        metadata={"keywords": ["hello world"], "mode": "all"},
    )
    assert result.is_correct is True
    assert result.score == 1.0


def test_numeric_tolerance_oracle() -> None:
    oracle = NumericToleranceOracle()
    result = oracle.evaluate(
        expected_answer="100.0",
        actual_answer="100.4",
        metadata={"tolerance": 0.5},
    )
    assert result.is_correct is True
    assert result.score == 1.0


def test_numeric_tolerance_supports_multiple_valid_answers() -> None:
    oracle = NumericToleranceOracle()
    result = oracle.evaluate(
        expected_answer="3.1415",
        actual_answer="3.14",
        metadata={"valid_answers": ["3.1415", "3.14"], "tolerance": 0.0},
    )
    assert result.is_correct is True
    assert result.score == 1.0


def test_json_schema_oracle() -> None:
    oracle = JsonSchemaOracle()
    schema = {
        "type": "object",
        "properties": {"name": {"type": "string"}, "score": {"type": "number"}},
        "required": ["name", "score"],
    }
    result = oracle.evaluate(
        expected_answer="{}",
        actual_answer='{"name":"alice","score":0.82}',
        metadata={"schema": schema},
    )
    assert result.is_correct is True
    assert result.score == 1.0


def test_semantic_similarity_oracle_placeholder() -> None:
    oracle = SemanticSimilarityOracle()
    result = oracle.evaluate(
        expected_answer="renewable energy reduces emissions",
        actual_answer="renewable sources reduce carbon emissions",
        metadata={"similarity_threshold": 0.25},
    )
    assert result.is_correct is True
    assert 0.0 <= result.score <= 1.0
    assert "placeholder" in (result.explanation or "")


def test_composite_rule_oracle_success_case() -> None:
    oracle = CompositeRuleOracle()
    result = oracle.evaluate(
        expected_answer="",
        actual_answer="Order ID: ORD-123 status: confirmed",
        metadata={
            "must_contain": ["order", "confirmed"],
            "forbidden_keywords": ["cancelled"],
            "regex_constraints": [r"ORD-\d{3}"],
        },
    )
    assert result.is_correct is True
    assert result.score == 1.0


def test_composite_rule_oracle_forbidden_keyword_edge_case() -> None:
    oracle = CompositeRuleOracle()
    result = oracle.evaluate(
        expected_answer="",
        actual_answer="Order is confirmed but then cancelled",
        metadata={
            "must_contain": ["order", "confirmed"],
            "forbidden_keywords": ["cancelled"],
            "regex_constraints": [],
        },
    )
    assert result.is_correct is False
    assert result.score < 1.0


def test_composite_rule_oracle_invalid_regex_edge_case() -> None:
    oracle = CompositeRuleOracle()
    result = oracle.evaluate(
        expected_answer="",
        actual_answer="Order ID: ORD-123",
        metadata={"regex_constraints": ["("]},
    )
    assert result.is_correct is False
    assert "invalid_patterns" in (result.explanation or "")


def test_oracle_factory_selects_correct_type() -> None:
    oracle = OracleFactory.create("keyword_match")
    result = oracle.evaluate(
        expected_answer="llm, reliability",
        actual_answer="We evaluate llm systems for reliability.",
    )
    assert result.is_correct is True


def test_oracle_factory_supports_new_oracles() -> None:
    assert isinstance(OracleFactory.create("semantic_similarity"), SemanticSimilarityOracle)
    assert isinstance(OracleFactory.create("composite_rule"), CompositeRuleOracle)
