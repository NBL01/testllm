"""Correctness oracles."""

from llm_reliability_analytics.oracles.engine import (
    BaseOracle,
    CompositeRuleOracle,
    ExactMatchOracle,
    JsonSchemaOracle,
    KeywordMatchOracle,
    NumericToleranceOracle,
    OracleEvaluation,
    OracleFactory,
    RegexMatchOracle,
    SemanticSimilarityOracle,
    evaluate_with_oracle,
)
from llm_reliability_analytics.oracles.normalization import normalize_answer

__all__ = [
    "BaseOracle",
    "OracleEvaluation",
    "ExactMatchOracle",
    "RegexMatchOracle",
    "KeywordMatchOracle",
    "NumericToleranceOracle",
    "JsonSchemaOracle",
    "SemanticSimilarityOracle",
    "CompositeRuleOracle",
    "OracleFactory",
    "evaluate_with_oracle",
    "normalize_answer",
]
