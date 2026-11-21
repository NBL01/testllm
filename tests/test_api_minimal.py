from fastapi.testclient import TestClient

from llm_reliability_analytics.main import app


def test_models_endpoint_returns_expected_shape() -> None:
    client = TestClient(app)
    response = client.get("/models")
    assert response.status_code == 200
    payload = response.json()
    assert "ollama_reachable" in payload
    assert isinstance(payload["installed_models"], list)
    assert isinstance(payload["available_models"], list)
