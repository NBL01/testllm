"""Launch evaluation runs from Streamlit without mixing business logic into UI code."""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

from llm_reliability_analytics.runner import (
    DEFAULT_LOCAL_MODEL,
    OPTIONAL_OLLAMA_MODELS,
    RECOMMENDED_OLLAMA_MODELS,
    LLMModelNotFoundError,
    LLMRequestError,
    LLMServiceUnavailableError,
    OllamaLLMClient,
)
from llm_reliability_analytics.workflow.service import RunBatchWorkflowResult, run_batch_workflow


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
    """Thin adapter around workflow entrypoints for Streamlit actions."""

    def __init__(self, project_root: Path) -> None:
        self.project_root = project_root
        self.raw_data_dir = project_root / "data" / "raw"
        self.adversarial_data_dir = project_root / "data" / "adversarial"
        self.default_datasets = ["sample_test_cases.jsonl", "llm_eval_dataset_v2_300.jsonl"]

    def list_datasets(self) -> list[str]:
        datasets: list[str] = []
        if self.raw_data_dir.exists():
            for path in sorted(self.raw_data_dir.iterdir()):
                if path.suffix.lower() in {".jsonl", ".csv"} and path.is_file():
                    datasets.append(path.name)
        if self.adversarial_data_dir.exists():
            for path in sorted(self.adversarial_data_dir.iterdir()):
                if path.suffix.lower() in {".jsonl", ".csv"} and path.is_file():
                    datasets.append(f"adversarial/{path.name}")

        if datasets:
            return datasets

        return self.default_datasets

    def recommended_ollama_models(self) -> list[str]:
        return RECOMMENDED_OLLAMA_MODELS + OPTIONAL_OLLAMA_MODELS

    def list_installed_ollama_models(self, timeout_seconds: float = 3.0) -> list[str]:
        client = OllamaLLMClient(
            model_name=DEFAULT_LOCAL_MODEL,
            timeout_seconds=timeout_seconds,
        )
        return client.list_installed_models()

    def start_run(self, request: LaunchRequest) -> RunBatchWorkflowResult:
        run_mode = "real_local" if request.provider == "ollama" else "mock"
        return run_batch_workflow(
            input_path=request.dataset_path,
            run_name=request.run_name,
            run_label=request.run_label,
            model_name=request.model_name,
            provider=request.provider,
            dataset_version=request.dataset_version,
            evaluation_mode=request.evaluation_mode,
            temperature=request.temperature,
            max_output_tokens=request.max_output_tokens,
            timeout_seconds=request.timeout_seconds,
            run_mode=run_mode,
            notes=request.notes,
            mock_mode=request.mock_mode,  # kept explicit so demo can show deterministic vs semi-random
            seed=42,
            limit=request.limit,
            repeats_per_case=request.repeat_count,
        )

    @staticmethod
    def friendly_error_message(exc: Exception) -> str:
        if isinstance(exc, LLMServiceUnavailableError):
            return (
                "Ollama is not reachable. Start Ollama locally and retry, "
                "or switch provider to Mock for the demo."
            )
        if isinstance(exc, LLMModelNotFoundError):
            return (
                f"{exc} Pull the model first, for example: `ollama pull {DEFAULT_LOCAL_MODEL}`."
            )
        if isinstance(exc, LLMRequestError):
            return f"Local model request failed: {exc}"
        return str(exc)
