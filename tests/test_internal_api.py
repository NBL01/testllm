"""Internal/admin boundary tests. Every database and export is temporary."""

import ast
import importlib.util
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
    monkeypatch.setenv("LLM_RELIABILITY_DB_PATH", str(tmp_path / "internal.duckdb"))
    from llm_reliability_analytics.api import internal
    from llm_reliability_analytics.api.routes import router
    from llm_reliability_analytics.storage.duckdb_store import initialize_storage_schema

    monkeypatch.setattr(internal, "PROJECT_ROOT", tmp_path)
    initialize_storage_schema()
    app = FastAPI()
    app.include_router(router)
    app.include_router(internal.router)
    with TestClient(app) as test_client:
        yield test_client


def test_internal_router_exists():
    assert importlib.util.find_spec("llm_reliability_analytics.api.internal") is not None


def test_frontend_has_no_operational_backend_imports_or_file_writes():
    forbidden = ("duckdb", "llm_reliability_analytics.storage",
                 "llm_reliability_analytics.workflow", "llm_reliability_analytics.datasets",
                 "llm_reliability_analytics.runner")
    for path in (ROOT / "frontend").rglob("*.py"):
        tree = ast.parse(path.read_text())
        for node in ast.walk(tree):
            if isinstance(node, ast.ImportFrom):
                assert not (node.module or "").startswith(forbidden), (path, node.lineno)
            if isinstance(node, ast.Import):
                assert not any(alias.name.startswith(forbidden) for alias in node.names), path
            if isinstance(node, ast.Call) and isinstance(node.func, ast.Attribute):
                assert node.func.attr not in {"execute", "executemany", "mkdir", "write_text", "write_bytes"}, (path, node.lineno)
                if node.func.attr == "open":
                    assert not any(isinstance(arg, ast.Constant) and isinstance(arg.value, str)
                                   and arg.value in {"a", "w", "wb", "ab"} for arg in node.args), path


def test_dashboard_empty_then_completed_run(client):
    empty = client.get("/internal/dashboard")
    assert empty.status_code == 200
    assert empty.json()["results"]["data"] == []
    run = client.post("/run-batch", json={"input_path": str(ROOT / "data/raw/sample_test_cases.jsonl"),
                                        "limit": 2, "repeats_per_case": 2})
    assert run.status_code == 200, run.text
    response = client.get("/internal/dashboard")
    assert response.status_code == 200, response.text
    data = response.json()
    assert data["source"] == "api"
    rows = [dict(zip(data["results"]["columns"], row)) for row in data["results"]["data"]]
    assert len(rows) == 4
    assert {row["run_id"] for row in rows} == {run.json()["run_id"]}
    assert all(row["prompt"] and row["expected_answer"] for row in rows)
    assert all(isinstance(row["is_correct"], bool) for row in rows)


def test_candidate_curation_and_backend_exports(client, tmp_path):
    generated = client.post("/candidates/generate", json={"categories": ["factual_qa"], "per_category": 2})
    assert generated.status_code == 200
    ids = [item["candidate_id"] for item in generated.json()["candidates"]]
    approved = client.post(f"/candidates/{ids[0]}/status", json={"new_status": "approved", "reviewer": "admin"})
    assert approved.status_code == 200
    assert client.get(f"/candidates/{ids[0]}/events").json()["total"] == 1
    promoted = client.post("/internal/candidates/promote", json={"candidate_ids": ids + ["missing"],
                           "dataset_version": "internal-v1", "target_source": "regression", "export_to_jsonl": True})
    assert promoted.status_code == 200, promoted.text
    assert promoted.json()["promoted"] == 1
    assert promoted.json()["skipped_not_approved"] == 1
    assert promoted.json()["skipped_not_found"] == 1
    assert Path(promoted.json()["export_path"]).is_relative_to(tmp_path)
    assert Path(promoted.json()["export_path"]).exists()
    assert client.get("/internal/datasets").json()["datasets"] == ["internal-v1_regression_promoted.jsonl"]


@pytest.mark.parametrize("version", ["../escape", "/tmp/escape", "a/b", "a\\b", " "])
def test_promotion_rejects_unsafe_export_names(client, version):
    response = client.post("/internal/candidates/promote", json={"candidate_ids": [],
                           "dataset_version": version, "target_source": "regression"})
    assert response.status_code == 422


def test_trace_marking_uses_persisted_evidence(client, tmp_path):
    run = client.post("/run-batch", json={"input_path": str(ROOT / "data/raw/sample_test_cases.jsonl"), "limit": 1})
    assert run.status_code == 200
    snapshot = client.get("/internal/dashboard").json()["results"]
    row = dict(zip(snapshot["columns"], snapshot["data"][0]))
    result = client.post("/internal/trace-candidates", json={"result_id": row["result_id"], "target_source": "regression"})
    assert result.status_code == 200, result.text
    import json
    evidence = json.loads(Path(result.json()["path"]).read_text())
    assert evidence["test_case"]["expected_answer"] == row["expected_answer"]
    assert evidence["model_output"]["raw_output"] == row["raw_output"]
    assert client.post("/internal/trace-candidates", json={"result_id": "missing", "target_source": "regression"}).status_code == 404
    assert client.post("/internal/trace-candidates", json={"result_id": row["result_id"], "target_source": "../escape"}).status_code == 422


def test_missing_database_is_not_empty_analytics(client, monkeypatch, tmp_path):
    monkeypatch.setenv("LLM_RELIABILITY_DB_PATH", str(tmp_path / "missing.duckdb"))
    response = client.get("/internal/dashboard")
    assert response.status_code == 503
    assert not (tmp_path / "missing.duckdb").exists()


@pytest.mark.parametrize("field,value", [("provider", "ollama"), ("dataset_version", "v2"),
    ("temperature", 0.9), ("max_output_tokens", 256), ("repeat_count", 3), ("evaluation_mode", "adversarial")])
def test_comparisons_reject_incompatible_settings(field, value):
    import pandas as pd
    from frontend.services.metrics_adapter import MetricsAdapter

    base = {"run_id": "a", "model_name": "same", "provider": "mock", "dataset_version": "v1",
            "temperature": 0.0, "max_output_tokens": 128, "repeat_count": 1, "evaluation_mode": "regression",
            "mode": "mock", "model_version": "n/a", "status": "completed", "created_at": "2026-01-01"}
    runs = pd.DataFrame([base, {**base, "run_id": "b", field: value}])
    results = pd.DataFrame([{"run_id": rid, "test_case_id": "case", "is_correct": True,
                             "score": 1.0, "latency_ms": 1.0, "error_type": ""} for rid in ["a", "b"]])
    adapter = MetricsAdapter()
    with pytest.raises(ValueError, match=field):
        adapter.compare_runs(results, runs, "a", "b")
    with pytest.raises(ValueError, match=field):
        adapter.build_multi_run_model_reports(results, runs)


def test_comparisons_reject_different_case_evidence():
    import pandas as pd
    from frontend.services.metrics_adapter import MetricsAdapter

    runs = pd.DataFrame([{"run_id": rid, "provider": "mock", "dataset_version": "v1"} for rid in ["a", "b"]])
    results = pd.DataFrame([{"run_id": "a", "test_case_id": "case", "expected_answer": "4"},
                            {"run_id": "b", "test_case_id": "case", "expected_answer": "5"}])
    with pytest.raises(ValueError, match="evidence"):
        MetricsAdapter().compare_runs(results, runs, "a", "b")


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
    assert calls[0][2]["params"] == {"max_jobs": 4}
    assert "iteration=2/2 processed_count=2 queue_total=5 queued=3" in capsys.readouterr().out


@pytest.mark.parametrize("status,body,expected", [(422, {"detail": [{"loc": ["body", "limit"], "msg": "Too large"}]}, "body.limit: Too large"),
    (503, "Backend unavailable", "Backend unavailable"), (200, "not-json", "not-json")])
def test_http_adapter_preserves_errors(monkeypatch, status, body, expected):
    import httpx
    from frontend.services.api_client import APIClient, BackendAPIError

    response = httpx.Response(status, json=body) if isinstance(body, dict) else httpx.Response(status, text=body)
    monkeypatch.setattr(httpx, "request", lambda *args, **kwargs: response)
    with pytest.raises(BackendAPIError, match=expected):
        APIClient().request("GET", "/internal/dashboard")


def test_http_outage_has_no_fallback_or_mutation_retry(monkeypatch, tmp_path):
    import httpx
    from frontend.services.api_client import APIClient, BackendAPIError
    from frontend.services.data_provider import DataProvider

    calls = []

    def unavailable(*args, **kwargs):
        calls.append(args)
        raise httpx.ConnectError("offline")

    monkeypatch.setattr(httpx, "request", unavailable)
    with pytest.raises(BackendAPIError, match="FastAPI unavailable"):
        DataProvider(project_root=tmp_path / "ui").load()
    with pytest.raises(BackendAPIError, match="may still be running"):
        APIClient().request("POST", "/run-batch", json={})
    assert len(calls) == 2
    assert not (tmp_path / "ui").exists()


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


def test_separate_admin_process_with_backend_db_owner(client, live_backend, tmp_path):
    import os
    import subprocess
    import sys
    from llm_reliability_analytics.storage.db import get_connection

    # Holding a writable connection makes accidental child-process DB access fail.
    connection = get_connection()
    script = '''
import os
from pathlib import Path
from frontend.services.api_client import APIClient
from frontend.services.data_provider import DataProvider
from frontend.services.run_launcher import LaunchRequest, RunLauncher
from frontend.services.candidate_service import generate_candidates_and_store, list_candidates_frame, set_candidate_status, candidate_events_frame, promote_candidates
from frontend.services.trace_service import mark_trace_candidate
from frontend.services.result_inspector import fetch_result_trace
from frontend.services.metrics_adapter import MetricsAdapter
from llm_reliability_analytics.test_authoring.models import CandidateStatus
root = Path(os.environ["TEST_ROOT"])
ui_root = Path(os.environ["UI_ROOT"])
launcher = RunLauncher(ui_root)
result = launcher.start_run(LaunchRequest(str(root / "data/raw/sample_test_cases.jsonl"), "admin", None,
    "mock", "mock-baseline", None, "regression", 0.0, 1, 128, 30.0, "deterministic", "", 2))
data = DataProvider(ui_root).load()
assert len(data.results) == 2
assert MetricsAdapter().build_report_for_run(data.results, result.run_id, data.runs).total_test_cases == 2
trace = fetch_result_trace(data.results, data.runs, data.results.iloc[0]["result_id"])
assert mark_trace_candidate(trace, "regression", ui_root)
generated = generate_candidates_and_store(["factual_qa"], 2)
assert len(list_candidates_frame()) == 2
assert set_candidate_status(generated[0].candidate_id, CandidateStatus.APPROVED).status == CandidateStatus.APPROVED
assert len(candidate_events_frame(generated[0].candidate_id)) == 1
assert promote_candidates([generated[0].candidate_id], "live-v1", "regression", project_root=ui_root).promoted == 1
assert launcher.list_datasets() == ["live-v1_regression_promoted.jsonl"]
assert not ui_root.exists()
from streamlit.testing.v1 import AppTest
at = AppTest.from_file(str(root / "frontend/streamlit_app.py"), default_timeout=20).run()
assert not at.exception, at.exception
assert not any("FastAPI" in error.value for error in at.error), [error.value for error in at.error]
at.sidebar.radio[0].set_value("Admin Model Comparison").run()
assert not at.exception, at.exception
at.sidebar.radio[0].set_value("Dataset Studio (V2 Preview)").run()
assert not at.exception, at.exception
at.sidebar.radio[0].set_value("Admin Run New Evaluation").run()
assert not at.exception, at.exception
print("ADMIN_HTTP_ONLY_OK")
'''
    env = {**os.environ, "LLM_RELIABILITY_API_BASE_URL": live_backend,
           "PYTHONPATH": os.pathsep.join([str(ROOT), str(ROOT / "src")]), "PYTHONDONTWRITEBYTECODE": "1",
           "TEST_ROOT": str(ROOT), "UI_ROOT": str(tmp_path / "ui-must-not-write")}
    try:
        completed = subprocess.run([sys.executable, "-c", script], cwd=tmp_path, env=env, capture_output=True, text=True, timeout=90)
        assert completed.returncode == 0, completed.stdout + completed.stderr
        assert "ADMIN_HTTP_ONLY_OK" in completed.stdout
    finally:
        connection.close()


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
