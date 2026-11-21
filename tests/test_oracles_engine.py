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
    assert result.error_type is None
    assert result.details["comparison_result"] == "exact_match"


def test_exact_match_oracle_partial_scoring() -> None:
    oracle = ExactMatchOracle()
    result = oracle.evaluate(
        expected_answer="capital of france",
        actual_answer="the capital france",
    )
    assert result.is_correct is False
    assert 0.0 < result.score < 1.0


def test_exact_match_oracle_lenient_contains_match() -> None:
    oracle = ExactMatchOracle()
    result = oracle.evaluate(
        expected_answer="4",
        actual_answer="2 + 2 = 4.",
    )
    assert result.is_correct is True
    assert result.score == 1.0
    assert result.details["comparison_result"] == "contains_match"


def test_exact_match_oracle_strict_mode_disables_contains_match() -> None:
    oracle = ExactMatchOracle()
    result = oracle.evaluate(
        expected_answer="4",
        actual_answer="2 + 2 = 4.",
        metadata={"strict_exact": True},
    )
    assert result.is_correct is False
    assert result.error_type == "wrong_answer"


def test_regex_match_oracle_with_multiple_patterns_partial_score() -> None:
    oracle = RegexMatchOracle()
    result = oracle.evaluate(
        expected_answer=r"^order-\d{3}$||invoice-\d{2}",
        actual_answer="order-123",
        metadata={"mode": "all"},
    )
    assert result.is_correct is False
    assert result.score == 0.5
    assert result.details["matched_count"] == 1


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
    assert result.error_type == "invalid_regex_pattern"


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
    assert result.details["coverage"] == result.score


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
    assert result.details["absolute_difference"] is not None


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
    assert result.details["parse_success"] is True
    assert result.details["schema_valid"] is True


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
    assert result.error_type == "invalid_regex_pattern"


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


def test_numeric_strict_output_rejects_extra_text_as_format_violation() -> None:
    oracle = NumericToleranceOracle()
    strict = {"tolerance": 0.0, "strict_output": True}
    # Correct final answer inside an equation: a format failure, not a wrong calculation.
    shown_work = oracle.evaluate(expected_answer="11", actual_answer="24 - 13 = 11", metadata=strict)
    assert (shown_work.is_correct, shown_work.error_type) == (False, "format_violation")
    assert "first number found: 24" in shown_work.explanation
    # The first-number fallback used to pass non-compliant text like this one.
    accidental = oracle.evaluate(expected_answer="11", actual_answer="11, since 24 - 13 = 11", metadata=strict)
    assert accidental.is_correct is False
    assert oracle.evaluate(expected_answer="11", actual_answer=" 11 ", metadata=strict).is_correct is True
    # Without strict_output the legacy lenient extraction is unchanged.
    assert oracle.evaluate(expected_answer="11", actual_answer="11, since 24 - 13 = 11", metadata={"tolerance": 0.0}).is_correct is True


def test_strict_numeric_scoring_records_enforcement_in_effective_config() -> None:
    import json
    from llm_reliability_analytics.models.domain import TestCase as Case, TestResult as Result
    from llm_reliability_analytics.workflow.service import score_results_with_oracles

    case = Case(id="n1", category="math", difficulty="easy", prompt="24 - 13?", expected_answer="11",
                oracle_type="numeric_tolerance", metadata={"tolerance": 0.0, "strict_output": True})
    result = Result(run_id="r", test_case_id="n1", category="math", actual_answer="24 - 13 = 11",
                    is_correct=False, score=0.0, latency_ms=1.0)
    score_results_with_oracles(test_cases=[case], results=[result])
    assert result.error_type == "format_violation" and result.error_taxonomy.value == "parsing"
    assert json.loads(result.oracle_details_json)["input_config"]["strict_output_enforced"] is True
    assert "strict_output_enforced" not in case.metadata  # the frozen case itself is untouched
