"""HTTP-only queue CLI tests. Every database is temporary."""

from pathlib import Path

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient


ROOT = Path(__file__).resolve().parents[1]


@pytest.fixture(autouse=True)
def isolated_database(monkeypatch, tmp_path):
    monkeypatch.setenv("LLM_RELIABILITY_DB_PATH", str(tmp_path / "isolated.duckdb"))


@pytest.fixture
def client(monkeypatch, tmp_path):
    monkeypatch.setenv("LLM_RELIABILITY_DB_PATH", str(tmp_path / "queue.duckdb"))
    from llm_reliability_analytics.api.routes import router
    from llm_reliability_analytics.storage.duckdb_store import initialize_storage_schema

    initialize_storage_schema()
    app = FastAPI()
    app.include_router(router)
    with TestClient(app) as test_client:
        yield test_client


def test_queue_cli_is_http_only(monkeypatch, capsys):
    import httpx
    from llm_reliability_analytics.cli import process_queue

    calls = []

    def request(method, url, **kwargs):
        calls.append((method, url, kwargs))
        payload = {"processed_count": 2, "requested_max_jobs": 4} if method == "POST" else {"total": 5, "by_status": {"queued": 3}}
        return httpx.Response(200, json=payload)

    monkeypatch.setattr(httpx, "request", request)
    monkeypatch.setattr("sys.argv", ["process_queue", "--max-jobs", "4", "--poll-interval-seconds", "0.01", "--iterations", "2"])
    process_queue.main()
    assert [call[0] for call in calls] == ["POST", "GET", "POST", "GET"]
    assert calls[0][1].endswith("/evaluation-jobs/process-queue")
    assert calls[0][2]["params"] == {"max_jobs": 4, "wait": True}
    assert "iteration=2/2 processed_count=2 queue_total=5 queued=3" in capsys.readouterr().out


@pytest.fixture
def live_backend(client):
    import socket
    import threading
    import time
    import uvicorn

    sock = socket.socket()
    sock.bind(("127.0.0.1", 0))
    server = uvicorn.Server(uvicorn.Config(client.app, log_level="error", lifespan="off"))
    thread = threading.Thread(target=server.run, kwargs={"sockets": [sock]}, daemon=True)
    thread.start()
    try:
        deadline = time.monotonic() + 10
        while not server.started and thread.is_alive() and time.monotonic() < deadline:
            time.sleep(0.01)
        assert server.started
        yield f"http://127.0.0.1:{sock.getsockname()[1]}"
    finally:
        server.should_exit = True
        thread.join(timeout=10)
        sock.close()


def test_queue_cli_live_backend(client, live_backend, tmp_path):
    import os
    import subprocess
    import sys
    from llm_reliability_analytics.storage.db import get_connection

    job = client.post("/evaluation-jobs", json={"input_path": str(ROOT / "data/raw/sample_test_cases.jsonl"),
                      "model_name": "mock-baseline", "limit": 1})
    assert job.status_code == 201, job.text
    job_id = job.json()["job_id"]
    assert client.post(f"/evaluation-jobs/{job_id}/queue").status_code == 200
    connection = get_connection()
    try:
        completed = subprocess.run([sys.executable, "-m", "llm_reliability_analytics.cli.process_queue", "--max-jobs", "1"],
            cwd=tmp_path, env={**os.environ, "LLM_RELIABILITY_API_BASE_URL": live_backend,
                              "PYTHONPATH": str(ROOT / "src"), "PYTHONDONTWRITEBYTECODE": "1"},
            capture_output=True, text=True, timeout=30)
        assert completed.returncode == 0, completed.stdout + completed.stderr
        assert "processed_count=1 requested_max_jobs=1 queue_total=1" in completed.stdout
        assert client.get(f"/evaluation-jobs/{job_id}").json()["status"] == "completed"
    finally:
        connection.close()
