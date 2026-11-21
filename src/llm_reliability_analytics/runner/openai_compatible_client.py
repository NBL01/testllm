from __future__ import annotations

from dataclasses import dataclass, field
import os

import httpx

from llm_reliability_analytics.runner.llm_client import (
    BaseLLMClient,
    LLMGeneration,
    LLMModelNotFoundError,
    LLMRequestError,
    LLMServiceUnavailableError,
)

BASE_URL_ENV = "LLM_RELIABILITY_OPENAI_BASE_URL"
API_KEY_ENV = "LLM_RELIABILITY_OPENAI_API_KEY"
# Local-first default: Ollama's OpenAI-compatible endpoint, never a paid service.
DEFAULT_BASE_URL = "http://127.0.0.1:11434/v1"


def configured_base_url() -> str:
    return os.getenv(BASE_URL_ENV, "").strip().rstrip("/") or DEFAULT_BASE_URL


@dataclass
class OpenAICompatibleClient(BaseLLMClient):
    """Client for OpenAI-compatible chat-completions endpoints."""

    model_name: str
    temperature: float = 0.0
    max_output_tokens: int = 128
    timeout_seconds: float = 30.0
    # The base URL and key come ONLY from server environment, never from request payloads (trust boundary: prevents the UI from redirecting a key or making the server call arbitrary hosts).
    base_url: str = field(default_factory=configured_base_url)
    api_key: str = field(default_factory=lambda: os.getenv(API_KEY_ENV, "").strip(), repr=False)

    def __post_init__(self) -> None:
        self.base_url = self.base_url.strip().rstrip("/")
        self.api_key = self.api_key.strip()

    def generate(self, prompt: str) -> str:
        return self.generate_with_metadata(prompt).text

    def generate_with_metadata(self, prompt: str) -> LLMGeneration:
        request_payload = {
            "model": self.model_name,
            "messages": [{"role": "user", "content": prompt}],
            "temperature": float(self.temperature),
            "max_tokens": int(self.max_output_tokens),
            "stream": False,
        }
        headers: dict[str, str] = {}
        if self.api_key:
            headers["Authorization"] = f"Bearer {self.api_key}"

        try:
            with httpx.Client(timeout=self.timeout_seconds) as client:
                response = client.post(
                    f"{self.base_url}/chat/completions",
                    json=request_payload,
                    headers=headers,
                )
        except httpx.ConnectError as exc:
            raise LLMServiceUnavailableError(
                f"OpenAI-compatible endpoint is not reachable at {self.base_url}."
            ) from exc
        except httpx.TimeoutException as exc:
            raise LLMServiceUnavailableError(
                "OpenAI-compatible request timed out. Check server load or increase timeout."
            ) from exc
        except httpx.HTTPError as exc:
            raise LLMRequestError(f"OpenAI-compatible request failed: {exc}") from exc

        if response.status_code in (401, 403):
            raise LLMRequestError(
                f"OpenAI-compatible endpoint rejected credentials (HTTP {response.status_code}); set {API_KEY_ENV}."
            )
        if response.status_code == 404:
            raise LLMModelNotFoundError(
                f"Model '{self.model_name}' was not found at {self.base_url}."
            )
        if response.status_code >= 400:
            raise LLMRequestError(
                f"OpenAI-compatible endpoint returned HTTP {response.status_code}: {response.text[:500]}"
            )

        try:
            payload = response.json()
        except ValueError as exc:
            raise LLMRequestError("OpenAI-compatible response was not valid JSON.") from exc

        if (
            not isinstance(payload, dict)
            or not isinstance(payload.get("choices"), list)
            or not payload["choices"]
            or not isinstance(payload["choices"][0], dict)
            or not isinstance(payload["choices"][0].get("message"), dict)
            or not isinstance(payload["choices"][0]["message"].get("content"), str)
        ):
            raise LLMRequestError(
                "OpenAI-compatible response must contain choices[0].message.content text."
            )

        first_choice = payload["choices"][0]
        text = first_choice["message"]["content"].strip()
        if not text:
            raise LLMRequestError("OpenAI-compatible endpoint returned an empty response.")

        # Ponytail: latency_ms is left None because the runner measures wall-clock latency itself; upgrade path is extracting server timing headers if provided.
        usage = payload.get("usage") if isinstance(payload.get("usage"), dict) else None
        return LLMGeneration(
            text=text,
            latency_ms=None,
            metadata={
                "usage": usage,
                "finish_reason": first_choice.get("finish_reason"),
            },
        )
