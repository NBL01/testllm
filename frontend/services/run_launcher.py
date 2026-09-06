"""Launch evaluation runs from Streamlit without mixing business logic into UI code."""

from __future__ import annotations

from dataclasses import asdict, dataclass
from pathlib import Path

from frontend.services.api_client import APIClient, BackendAPIError
from llm_reliability_analytics.analytics.reliability import ReliabilityReport


@dataclass
class LaunchResult:
    run_id: str
    loaded_test_cases: int
    executed_test_cases: int
    report: ReliabilityReport
    storage_summary: dict


@dataclass
class LaunchRequest:
    dataset_path: str
    run_name: str
    run_label: str | None
    provider: str
    model_name: str
    dataset_version: str | None
    evaluation_mode: str
    temperature: float
    repeat_count: int
    max_output_tokens: int
    timeout_seconds: float
    mock_mode: str
    notes: str
    limit: int | None = None


class RunLauncher:
    """HTTP adapter preserving the admin batch and discovery controls."""

    def __init__(self, project_root: Path | None = None, api: APIClient | None = None) -> None:
        self.api = api or APIClient()

    def list_datasets(self) -> list[str]:
        return self.api.request("GET", "/internal/datasets")["datasets"]

    def recommended_ollama_models(self) -> list[str]:
        return self.api.request("GET", "/evaluation-jobs/options")["models_by_provider"]["ollama"]

    def mock_models(self) -> list[str]:
        return self.api.request("GET", "/evaluation-jobs/options")["models_by_provider"]["mock"]

    def list_installed_ollama_models(self, timeout_seconds: float = 3.0) -> list[str]:
        payload = self.api.request("GET", "/models", timeout=max(10.0, timeout_seconds))
        if not payload["ollama_reachable"]:
            raise BackendAPIError(payload.get("error") or "Ollama is not reachable from FastAPI.")
        return payload["installed_models"]

    def start_run(self, request: LaunchRequest) -> LaunchResult:
        payload = asdict(request)
        payload["input_path"] = payload.pop("dataset_path")
        payload["repeats_per_case"] = payload.pop("repeat_count")
        payload["run_mode"] = "real_local" if request.provider == "ollama" else "mock"
        payload["seed"] = 42
        result = self.api.request("POST", "/run-batch", json=payload)
        return LaunchResult(**{**result, "report": ReliabilityReport.model_validate(result["report"])})

    @staticmethod
    def friendly_error_message(exc: Exception) -> str:
        return str(exc)
