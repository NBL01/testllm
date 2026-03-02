from __future__ import annotations

from dataclasses import dataclass

import httpx

from llm_reliability_analytics.runner.llm_client import (
    BaseLLMClient,
    LLMGeneration,
    LLMModelNotFoundError,
    LLMRequestError,
    LLMServiceUnavailableError,
)


@dataclass
class OllamaLLMClient(BaseLLMClient):
    """Minimal Ollama client for local model execution."""

    model_name: str
    temperature: float = 0.1
    max_output_tokens: int = 128
    timeout_seconds: float = 30.0
    base_url: str = "http://127.0.0.1:11434"

    def generate(self, prompt: str) -> str:
        return self.generate_with_metadata(prompt).text

    def generate_with_metadata(self, prompt: str) -> LLMGeneration:
        payload = {
            "model": self.model_name,
            "prompt": prompt,
            "stream": False,
            "options": {
                "temperature": float(self.temperature),
                "num_predict": int(self.max_output_tokens),
            },
        }

        try:
            with httpx.Client(base_url=self.base_url, timeout=self.timeout_seconds) as client:
                response = client.post("/api/generate", json=payload)
        except httpx.ConnectError as exc:
            raise LLMServiceUnavailableError(
                "Ollama is not reachable. Start Ollama and try again."
            ) from exc
        except httpx.TimeoutException as exc:
            raise LLMServiceUnavailableError(
                "Ollama request timed out. Check local load or increase timeout."
            ) from exc
        except httpx.HTTPError as exc:
            raise LLMRequestError(f"Ollama request failed: {exc}") from exc

        response_text = response.text
        if response.status_code >= 400:
            normalized = response_text.lower()
            if response.status_code == 404 or "not found" in normalized:
                raise LLMModelNotFoundError(
                    f"Ollama model '{self.model_name}' is not installed."
                )
            raise LLMRequestError(f"Ollama returned HTTP {response.status_code}: {response_text}")

        try:
            payload_json = response.json()
        except ValueError as exc:
            raise LLMRequestError("Ollama response was not valid JSON.") from exc

        error_message = str(payload_json.get("error", "")).strip()
        if error_message:
            if "not found" in error_message.lower():
                raise LLMModelNotFoundError(
                    f"Ollama model '{self.model_name}' is not installed."
                )
            raise LLMRequestError(f"Ollama error: {error_message}")

        generated_text = str(payload_json.get("response", "")).strip()
        if not generated_text:
            raise LLMRequestError("Ollama returned an empty response.")

        total_duration_ns = payload_json.get("total_duration")
        latency_ms = None
        if isinstance(total_duration_ns, (int, float)) and total_duration_ns >= 0:
            latency_ms = float(total_duration_ns) / 1_000_000.0

        return LLMGeneration(
            text=generated_text,
            latency_ms=latency_ms,
            metadata={
                "eval_count": payload_json.get("eval_count"),
                "prompt_eval_count": payload_json.get("prompt_eval_count"),
            },
        )

    def list_installed_models(self) -> list[str]:
        try:
            with httpx.Client(base_url=self.base_url, timeout=self.timeout_seconds) as client:
                response = client.get("/api/tags")
        except (httpx.ConnectError, httpx.TimeoutException) as exc:
            raise LLMServiceUnavailableError("Ollama is not reachable.") from exc
        except httpx.HTTPError as exc:
            raise LLMRequestError(f"Failed to list Ollama models: {exc}") from exc

        if response.status_code >= 400:
            raise LLMRequestError(
                f"Ollama returned HTTP {response.status_code} for /api/tags."
            )

        try:
            payload = response.json()
        except ValueError as exc:
            raise LLMRequestError("Ollama /api/tags response was not valid JSON.") from exc

        models = payload.get("models", [])
        if not isinstance(models, list):
            return []

        names: list[str] = []
        for model in models:
            if isinstance(model, dict):
                name = model.get("name")
                if isinstance(name, str) and name.strip():
                    names.append(name.strip())
        return sorted(set(names))
