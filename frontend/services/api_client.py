"""HTTP-only access to the DB-owning FastAPI process. Never retry mutations."""

from __future__ import annotations

import os
from typing import Any

import httpx


class BackendAPIError(RuntimeError):
    def __init__(self, message: str, status_code: int | None = None) -> None:
        super().__init__(message)
        self.status_code = status_code


class APIClient:
    def __init__(self, base_url: str | None = None) -> None:
        self.base_url = (base_url or os.getenv("LLM_RELIABILITY_API_BASE_URL", "http://127.0.0.1:8000")).rstrip("/")

    def request(self, method: str, path: str, *, json: Any = None,
                params: dict[str, Any] | None = None, timeout: float | None = None) -> Any:
        seconds = timeout if timeout is not None else (30.0 if method == "GET" else float(os.getenv("LLM_RELIABILITY_API_ACTION_TIMEOUT_SECONDS", "3600")))
        try:
            response = httpx.request(
                method, self.base_url + path, json=json,
                params={key: value for key, value in (params or {}).items() if value is not None},
                timeout=httpx.Timeout(seconds, connect=5.0),
            )
        except httpx.RequestError as exc:
            note = " The action may still be running; refresh persisted state before retrying." if method != "GET" else ""
            raise BackendAPIError(
                f"FastAPI unavailable at {self.base_url}. Start the backend and check LLM_RELIABILITY_API_BASE_URL.{note}"
            ) from exc
        try:
            payload = response.json()
        except ValueError as exc:
            raise BackendAPIError(
                f"FastAPI returned HTTP {response.status_code}: {response.text[:500] or 'Invalid JSON response'}",
                response.status_code,
            ) from exc
        if not response.is_success:
            detail = payload.get("detail", payload) if isinstance(payload, dict) else payload
            if isinstance(detail, list):
                detail = "; ".join(
                    f"{'.'.join(map(str, item.get('loc', [])))}: {item.get('msg', item)}"
                    if isinstance(item, dict) else str(item) for item in detail
                )
            raise BackendAPIError(f"FastAPI HTTP {response.status_code}: {detail}", response.status_code)
        return payload
