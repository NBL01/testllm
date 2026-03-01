from llm_reliability_analytics.oracles.engine import (
    ExactMatchOracle,
    JsonSchemaOracle,
    KeywordMatchOracle,
    NumericToleranceOracle,
    OracleFactory,
    RegexMatchOracle,
)


def test_exact_match_oracle() -> None:
    oracle = ExactMatchOracle()
    result = oracle.evaluate(expected_answer="Paris", actual_answer="paris")
    assert result.is_correct is True
    assert result.score == 1.0
    assert result.explanation is not None


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


def test_numeric_tolerance_oracle() -> None:
    oracle = NumericToleranceOracle()
    result = oracle.evaluate(
        expected_answer="100.0",
        actual_answer="100.4",
        metadata={"tolerance": 0.5},
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


def test_oracle_factory_selects_correct_type() -> None:
    oracle = OracleFactory.create("keyword_match")
    result = oracle.evaluate(
        expected_answer="llm, reliability",
        actual_answer="We evaluate llm systems for reliability.",
    )
    assert result.is_correct is True
