import httpx
import pytest

from llm_reliability_analytics.runner.client_factory import build_llm_client
from llm_reliability_analytics.runner.llm_client import (
    LLMModelNotFoundError,
    LLMServiceUnavailableError,
    resolve_execution_mode,
)
from llm_reliability_analytics.runner.mock_client import MockLLMClient
from llm_reliability_analytics.runner.ollama_client import OllamaLLMClient


def test_resolve_execution_mode_prefers_real_local_when_provider_is_ollama() -> None:
    assert resolve_execution_mode(provider="ollama", mode="mock") == "real_local"
    assert resolve_execution_mode(provider="local", mode="mock") == "real_local"
    assert resolve_execution_mode(provider="mock", mode="real_local") == "real_local"
    assert resolve_execution_mode(provider="mock", mode="mock") == "mock"


def test_build_llm_client_returns_expected_client_type() -> None:
    mock_client = build_llm_client(provider="mock", run_mode="mock", model_name="mock-baseline")
    ollama_client = build_llm_client(provider="ollama", run_mode="real_local", model_name="llama3.2:1b")

    assert isinstance(mock_client, MockLLMClient)
    assert isinstance(ollama_client, OllamaLLMClient)


def test_ollama_client_raises_service_unavailable_on_connect_error(monkeypatch: pytest.MonkeyPatch) -> None:
    class BrokenClient:
        def __init__(self, *_args, **_kwargs) -> None:
            pass

        def __enter__(self) -> "BrokenClient":
            return self

        def __exit__(self, *_args: object) -> None:
            return None

        def post(self, *_args: object, **_kwargs: object) -> None:
            raise httpx.ConnectError("connection refused")

    monkeypatch.setattr("llm_reliability_analytics.runner.ollama_client.httpx.Client", BrokenClient)

    client = OllamaLLMClient(model_name="llama3.2:1b")
    with pytest.raises(LLMServiceUnavailableError):
        client.generate("Hello")


def test_ollama_client_raises_model_not_found_for_missing_model(monkeypatch: pytest.MonkeyPatch) -> None:
    class MissingModelClient:
        def __init__(self, *_args, **_kwargs) -> None:
            pass

        def __enter__(self) -> "MissingModelClient":
            return self

        def __exit__(self, *_args: object) -> None:
            return None

        def post(self, *_args: object, **_kwargs: object) -> httpx.Response:
            return httpx.Response(status_code=404, text="model not found")

    monkeypatch.setattr("llm_reliability_analytics.runner.ollama_client.httpx.Client", MissingModelClient)

    client = OllamaLLMClient(model_name="missing-model")
    with pytest.raises(LLMModelNotFoundError):
        client.generate("Hello")
