import httpx
import json as jsonlib
import pytest

from llm_reliability_analytics.runner.client_factory import build_llm_client
from llm_reliability_analytics.runner.llm_client import (
    LLMModelNotFoundError,
    LLMRequestError,
    LLMServiceUnavailableError,
    resolve_execution_mode,
)
from llm_reliability_analytics.runner.mock_client import MockLLMClient
from llm_reliability_analytics.runner.ollama_client import OllamaLLMClient
from llm_reliability_analytics.runner.openai_compatible_client import OpenAICompatibleClient


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


@pytest.mark.parametrize("payload", [[], None, "bad", {"models": "bad"}, {"models": ["bad"]}])
def test_malformed_ollama_discovery_is_a_typed_error(monkeypatch, payload):
    class StubClient:
        def __init__(self, **kwargs):
            pass
        def __enter__(self):
            return self
        def __exit__(self, *args):
            pass
        def get(self, path):
            return httpx.Response(200, content=jsonlib.dumps(payload))
    monkeypatch.setattr("llm_reliability_analytics.runner.ollama_client.httpx.Client", StubClient)
    with pytest.raises(LLMRequestError, match="models|object"):
        OllamaLLMClient(model_name="demo").list_installed_models()


@pytest.mark.parametrize("payload", [[], None, {"response": {"not": "text"}}])
def test_malformed_ollama_generation_is_a_typed_error(monkeypatch, payload):
    class StubClient:
        def __init__(self, **kwargs):
            pass
        def __enter__(self):
            return self
        def __exit__(self, *args):
            pass
        def post(self, path, json):
            return httpx.Response(200, content=jsonlib.dumps(payload))
    monkeypatch.setattr("llm_reliability_analytics.runner.ollama_client.httpx.Client", StubClient)
    with pytest.raises(LLMRequestError):
        OllamaLLMClient(model_name="demo").generate("Hello")


def test_openai_compatible_client_sends_chat_request_and_bearer_key(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("LLM_RELIABILITY_OPENAI_BASE_URL", "http://example.invalid/v1/")
    monkeypatch.setenv("LLM_RELIABILITY_OPENAI_API_KEY", "sk-test")

    recorded: dict[str, object] = {}

    class StubResponse:
        status_code = 200
        text = '{"choices":[{"message":{"content":"  Paris "},"finish_reason":"stop"}],"usage":{"total_tokens":3}}'

        def json(self) -> object:
            return {
                "choices": [{"message": {"content": "  Paris "}, "finish_reason": "stop"}],
                "usage": {"total_tokens": 3},
            }

    class StubClient:
        def __init__(self, *args: object, **kwargs: object) -> None:
            pass

        def __enter__(self) -> "StubClient":
            return self

        def __exit__(self, *args: object) -> None:
            pass

        def post(
            self,
            url: str,
            json: dict[str, object] | None = None,
            headers: dict[str, str] | None = None,
            **kwargs: object,
        ) -> StubResponse:
            recorded["url"] = url
            recorded["json"] = json
            recorded["headers"] = headers
            return StubResponse()

    monkeypatch.setattr(
        "llm_reliability_analytics.runner.openai_compatible_client.httpx.Client",
        StubClient,
    )

    client = OpenAICompatibleClient(model_name="test-model", max_output_tokens=64)
    text = client.generate("Q")

    assert text == "Paris"
    assert recorded["url"] == "http://example.invalid/v1/chat/completions"
    assert recorded["json"]["messages"] == [{"role": "user", "content": "Q"}]
    assert recorded["json"]["max_tokens"] == 64
    assert recorded["headers"]["Authorization"] == "Bearer sk-test"
    assert "sk-test" not in repr(client)


def test_openai_compatible_client_omits_auth_without_key(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.delenv("LLM_RELIABILITY_OPENAI_API_KEY", raising=False)
    monkeypatch.delenv("LLM_RELIABILITY_OPENAI_BASE_URL", raising=False)

    recorded: dict[str, object] = {}

    class StubResponse:
        status_code = 200
        text = '{"choices":[{"message":{"content":"ok"}}]}'

        def json(self) -> object:
            return {"choices": [{"message": {"content": "ok"}}]}

    class StubClient:
        def __init__(self, *args: object, **kwargs: object) -> None:
            pass

        def __enter__(self) -> "StubClient":
            return self

        def __exit__(self, *args: object) -> None:
            pass

        def post(
            self,
            url: str,
            json: dict[str, object] | None = None,
            headers: dict[str, str] | None = None,
            **kwargs: object,
        ) -> StubResponse:
            recorded["url"] = url
            recorded["headers"] = headers
            return StubResponse()

    monkeypatch.setattr(
        "llm_reliability_analytics.runner.openai_compatible_client.httpx.Client",
        StubClient,
    )

    client = OpenAICompatibleClient(model_name="demo")
    assert client.base_url == "http://127.0.0.1:11434/v1"

    client.generate("hello")
    recorded_headers = recorded.get("headers") or {}
    assert "Authorization" not in recorded_headers


@pytest.mark.parametrize(
    "payload",
    [
        {},
        {"choices": []},
        {"choices": [{"message": {"content": 5}}]},
        [1],
    ],
)
def test_openai_compatible_client_malformed_payloads_raise_request_error(
    monkeypatch: pytest.MonkeyPatch, payload: object
) -> None:
    class StubResponse:
        status_code = 200
        text = jsonlib.dumps(payload)

        def json(self) -> object:
            return payload

    class StubClient:
        def __init__(self, *args: object, **kwargs: object) -> None:
            pass

        def __enter__(self) -> "StubClient":
            return self

        def __exit__(self, *args: object) -> None:
            pass

        def post(self, *args: object, **kwargs: object) -> StubResponse:
            return StubResponse()

    monkeypatch.setattr(
        "llm_reliability_analytics.runner.openai_compatible_client.httpx.Client",
        StubClient,
    )

    client = OpenAICompatibleClient(model_name="demo")
    with pytest.raises(LLMRequestError):
        client.generate("Hello")


def test_openai_compatible_client_credential_and_missing_model_errors(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("LLM_RELIABILITY_OPENAI_API_KEY", "sk-secret")

    status_holder = {"code": 401}

    class StubResponse:
        @property
        def status_code(self) -> int:
            return status_holder["code"]

        @property
        def text(self) -> str:
            return "Unauthorized" if self.status_code == 401 else "Not Found"

        def json(self) -> object:
            return {"error": self.text}

    class StubClient:
        def __init__(self, *args: object, **kwargs: object) -> None:
            pass

        def __enter__(self) -> "StubClient":
            return self

        def __exit__(self, *args: object) -> None:
            pass

        def post(self, *args: object, **kwargs: object) -> StubResponse:
            return StubResponse()

    monkeypatch.setattr(
        "llm_reliability_analytics.runner.openai_compatible_client.httpx.Client",
        StubClient,
    )

    client = OpenAICompatibleClient(model_name="demo")

    with pytest.raises(LLMRequestError) as exc_info:
        client.generate("Hello")
    error_message = str(exc_info.value)
    assert "LLM_RELIABILITY_OPENAI_API_KEY" in error_message
    assert "sk-secret" not in error_message

    status_holder["code"] = 404
    with pytest.raises(LLMModelNotFoundError):
        client.generate("Hello")


def test_resolve_execution_mode_and_client_factory_for_openai_compatible() -> None:
    assert resolve_execution_mode("openai_compatible", "mock") == "real_api"

    client = build_llm_client(provider="openai_compatible", run_mode="real_api", model_name="m")
    assert isinstance(client, OpenAICompatibleClient)
    assert client.model_name == "m"

    with pytest.raises(ValueError, match="An OpenAI-compatible model name is required."):
        build_llm_client(provider="openai_compatible", run_mode="real_api", model_name="  ")



def test_blank_model_output_is_an_empty_answer_not_an_error(monkeypatch: pytest.MonkeyPatch) -> None:
    import httpx
    from llm_reliability_analytics.runner.openai_compatible_client import OpenAICompatibleClient

    class Stub:
        def __init__(self, *args: object, **kwargs: object) -> None: ...
        def __enter__(self) -> "Stub": return self
        def __exit__(self, *args: object) -> None: ...
        def post(self, *args: object, **kwargs: object) -> httpx.Response:
            return httpx.Response(200, json={"choices": [{"message": {"content": "   "}, "finish_reason": "stop"}]})

    monkeypatch.setattr("llm_reliability_analytics.runner.openai_compatible_client.httpx.Client", Stub)
    assert OpenAICompatibleClient(model_name="m", base_url="http://x/v1").generate("q") == ""
