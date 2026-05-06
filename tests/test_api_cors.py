from fastapi.testclient import TestClient

from llm_reliability_analytics.main import app


def test_preflight_options_for_evaluation_jobs_is_allowed() -> None:
    client = TestClient(app)
    response = client.options(
        "/evaluation-jobs",
        headers={
            "Origin": "http://localhost:3000",
            "Access-Control-Request-Method": "POST",
        },
    )

    assert response.status_code == 200
    assert response.headers.get("access-control-allow-origin") == "http://localhost:3000"

