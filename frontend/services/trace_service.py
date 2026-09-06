"""Trace curation through FastAPI; export paths belong to the backend."""

from pathlib import Path
from typing import Any

from frontend.services.api_client import APIClient


def mark_trace_candidate(trace_payload: dict[str, Any], target_source: str,
                         project_root: Path | None = None) -> Path:
    payload = APIClient().request("POST", "/internal/trace-candidates", json={
        "result_id": trace_payload["result_id"], "target_source": target_source,
    })
    return Path(payload["path"])
