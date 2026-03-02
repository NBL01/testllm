from __future__ import annotations

from typing import Literal

from llm_reliability_analytics.runner.llm_client import (
    DEFAULT_LOCAL_MODEL,
    BaseLLMClient,
    resolve_execution_mode,
)
from llm_reliability_analytics.runner.mock_client import MockLLMClient
from llm_reliability_analytics.runner.ollama_client import OllamaLLMClient

MockMode = Literal["deterministic", "semi_random"]


def build_llm_client(
    provider: str,
    run_mode: str,
    model_name: str | None,
    temperature: float = 0.0,
    max_output_tokens: int = 128,
    timeout_seconds: float = 30.0,
    mock_mode: MockMode = "deterministic",
    seed: int = 42,
    failure_rate: float = 0.0,
) -> BaseLLMClient:
    execution_mode = resolve_execution_mode(provider=provider, mode=run_mode)

    if execution_mode == "real_local":
        resolved_model = (model_name or "").strip() or DEFAULT_LOCAL_MODEL
        return OllamaLLMClient(
            model_name=resolved_model,
            temperature=temperature,
            max_output_tokens=max_output_tokens,
            timeout_seconds=timeout_seconds,
        )

    return MockLLMClient(mode=mock_mode, seed=seed, failure_rate=failure_rate)
