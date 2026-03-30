from fastapi.testclient import TestClient

from llm_reliability_analytics.main import app


def test_candidate_endpoints_flow(monkeypatch, tmp_path) -> None:
    db_path = tmp_path / "api_candidates.duckdb"
    monkeypatch.setenv("LLM_RELIABILITY_DB_PATH", str(db_path))
    client = TestClient(app)

    generate_response = client.post(
        "/candidates/generate",
        json={
            "categories": ["factual_qa", "classification"],
            "per_category": 2,
            "provider": "none",
        },
    )
    assert generate_response.status_code == 200
    generated_payload = generate_response.json()
    assert generated_payload["generated_count"] == 4
    assert generated_payload["stored_count"] == 4
    assert len(generated_payload["candidates"]) == 4

    list_response = client.get("/candidates")
    assert list_response.status_code == 200
    list_payload = list_response.json()
    assert list_payload["total"] == 4
    first_candidate_id = list_payload["items"][0]["candidate_id"]

    update_response = client.post(
        f"/candidates/{first_candidate_id}/status",
        json={
            "new_status": "approved",
            "reviewer": "api-reviewer",
            "note": "Promote to regression backlog",
        },
    )
    assert update_response.status_code == 200
    update_payload = update_response.json()
    assert update_payload["candidate"]["status"] == "approved"

    events_response = client.get(f"/candidates/{first_candidate_id}/events")
    assert events_response.status_code == 200
    events_payload = events_response.json()
    assert events_payload["total"] == 1
    assert events_payload["events"][0]["new_status"] == "approved"
    assert events_payload["events"][0]["reviewer"] == "api-reviewer"
