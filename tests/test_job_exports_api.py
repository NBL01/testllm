import csv
from io import StringIO

import pytest
from fastapi.testclient import TestClient

from llm_reliability_analytics.main import app


@pytest.fixture
def client(monkeypatch, tmp_path):
    monkeypatch.setenv("LLM_RELIABILITY_DB_PATH", str(tmp_path / "exports.duckdb"))
    with TestClient(app) as client:
        yield client


def test_csv_endpoint_and_reports_share_complete_job_evidence(client):
    job = client.post("/evaluation-jobs", json={"model_name": "mock-failing", "limit": 3,
                     "repeat_count": 2, "submitted_by": "Analyst", "project_name": "Demo"}).json()
    job_id = job["job_id"]
    assert client.get(f"/evaluation-jobs/{job_id}/failed-cases.csv").status_code == 400
    run = client.post(f"/evaluation-jobs/{job_id}/run")
    assert run.status_code == 200, run.text
    export = client.get(f"/evaluation-jobs/{job_id}/failed-cases.csv")
    assert export.status_code == 200, export.text
    assert export.headers["content-type"].startswith("text/csv")
    assert "attachment" in export.headers["content-disposition"]
    rows = list(csv.DictReader(StringIO(export.text)))
    summary = client.get(f"/evaluation-jobs/{job_id}/summary").json()
    assert len(rows) == summary["report"]["failed"] == 6
    for endpoint in ["report", "client-report"]:
        response = client.get(f"/evaluation-jobs/{job_id}/{endpoint}").json()
        assert "## Job Context" in response["markdown_report"]
        for value in [job_id, job["dataset_sha256"], "Analyst", "Demo"]:
            assert value in response["markdown_report"]
    assert client.get("/evaluation-jobs/missing/failed-cases.csv").status_code == 404
