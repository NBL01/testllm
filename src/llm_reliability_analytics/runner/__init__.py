"""Evaluation runner module."""

from llm_reliability_analytics.runner.client_factory import build_llm_client
from llm_reliability_analytics.runner.llm_client import (
    DEFAULT_LOCAL_MODEL,
    OPTIONAL_OLLAMA_MODELS,
    RECOMMENDED_OLLAMA_MODELS,
    BaseLLMClient,
    LLMClientError,
    LLMGeneration,
    LLMModelNotFoundError,
    LLMRequestError,
    LLMServiceUnavailableError,
)
from llm_reliability_analytics.runner.mock_client import MockLLMClient
from llm_reliability_analytics.runner.ollama_client import OllamaLLMClient
from llm_reliability_analytics.runner.test_runner import TestRunner

__all__ = [
    "BaseLLMClient",
    "DEFAULT_LOCAL_MODEL",
    "LLMClientError",
    "LLMGeneration",
    "LLMModelNotFoundError",
    "LLMRequestError",
    "LLMServiceUnavailableError",
    "MockLLMClient",
    "OllamaLLMClient",
    "OPTIONAL_OLLAMA_MODELS",
    "RECOMMENDED_OLLAMA_MODELS",
    "TestRunner",
    "build_llm_client",
]
