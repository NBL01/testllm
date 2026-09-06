"""Dashboard snapshots from FastAPI, never a local database or file fallback."""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

import pandas as pd

from frontend.services.api_client import APIClient, BackendAPIError


@dataclass
class LoadedData:
    runs: pd.DataFrame
    cases: pd.DataFrame
    results: pd.DataFrame
    source: str
    note: str = ""


class DataProvider:
    def __init__(self, project_root: Path | None = None, api: APIClient | None = None) -> None:
        # Keep project_root for existing callers; FastAPI resolves all paths.
        self.api = api or APIClient()

    def load(self) -> LoadedData:
        payload = self.api.request("GET", "/internal/dashboard")
        try:
            frames = {key: pd.DataFrame(**payload[key]) for key in ("runs", "cases", "results")}
            for frame, column in [(frames["runs"], "created_at"), (frames["results"], "timestamp")]:
                frame[column] = pd.to_datetime(frame[column], errors="coerce")
            return LoadedData(**frames, source=payload["source"], note=payload["note"])
        except (KeyError, TypeError, ValueError) as exc:
            raise BackendAPIError("FastAPI returned an invalid dashboard snapshot; check backend version.") from exc
