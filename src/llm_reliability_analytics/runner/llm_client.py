from __future__ import annotations

from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from typing import Any, Literal


RECOMMENDED_OLLAMA_MODELS: list[str] = [
    "llama3.2:1b",
    "qwen2.5:0.5b",
    "qwen2.5:1.5b",
    "gemma2:2b",
]

OPTIONAL_OLLAMA_MODELS: list[str] = [
    "llama3.2:3b",
    "phi3",
]

DEFAULT_LOCAL_MODEL = RECOMMENDED_OLLAMA_MODELS[0]


class LLMClientError(RuntimeError):
    """Base error for model client failures."""


class LLMServiceUnavailableError(LLMClientError):
    """Raised when the local model service is unavailable."""


class LLMModelNotFoundError(LLMClientError):
    """Raised when the selected model is not available."""


class LLMRequestError(LLMClientError):
    """Raised for request/response failures that are not connectivity issues."""


@dataclass(slots=True)
class LLMGeneration:
    text: str
    latency_ms: float | None = None
    metadata: dict[str, Any] = field(default_factory=dict)


class BaseLLMClient(ABC):
    """Simple client interface used by the batch runner."""

    @abstractmethod
    def generate(self, prompt: str) -> str:
        """Generate one text output for a prompt."""

    def generate_with_metadata(self, prompt: str) -> LLMGeneration:
        """Default metadata wrapper for clients that only return text."""
        return LLMGeneration(text=self.generate(prompt), latency_ms=None)


def resolve_execution_mode(provider: str, mode: str) -> Literal["mock", "real_local"]:
    normalized_provider = provider.strip().lower()
    normalized_mode = mode.strip().lower()

    if normalized_provider in {"ollama", "local"}:
        return "real_local"

    if normalized_mode in {"real_local", "real"}:
        return "real_local"
    if normalized_mode == "mock":
        return "mock"
    return "mock"
