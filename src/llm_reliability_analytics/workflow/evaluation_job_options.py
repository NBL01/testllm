"""Option discovery for evaluation-job creation UIs."""

from __future__ import annotations

import json
from pathlib import Path

from pydantic import BaseModel

from llm_reliability_analytics.models.domain import EvaluationMode, OracleType
from llm_reliability_analytics.runner.llm_client import OPTIONAL_OLLAMA_MODELS, RECOMMENDED_OLLAMA_MODELS

PROJECT_ROOT = Path(__file__).resolve().parents[3]


class DatasetOption(BaseModel):
    id: str
    label: str
    input_path: str
    dataset_version: str
    evaluation_mode: str


class EvaluationJobOptionsResponse(BaseModel):
    providers: list[str]
    models_by_provider: dict[str, list[str]]
    datasets: list[DatasetOption]
    dataset_paths: list[str]
    dataset_versions: list[str]
    oracle_profiles: list[str]
    oracle_types: list[str]
    evaluation_modes: list[str]


def get_evaluation_job_options() -> EvaluationJobOptionsResponse:
    providers = ["mock", "ollama", "local"]
    ollama_models = _dedupe_ordered([*RECOMMENDED_OLLAMA_MODELS, *OPTIONAL_OLLAMA_MODELS])
    models_by_provider = {
        "mock": ["mock-baseline", "mock-noisy", "mock-failing"],
        "ollama": ollama_models,
        "local": ollama_models,
    }
    dataset_paths = _discover_dataset_paths()
    dataset_versions = _discover_dataset_versions(dataset_paths)
    oracle_profiles = _discover_oracle_profiles()
    oracle_types = [oracle.value for oracle in OracleType]
    evaluation_modes = [mode.value for mode in EvaluationMode]
    return EvaluationJobOptionsResponse(
        providers=providers,
        models_by_provider=models_by_provider,
        datasets=[
            DatasetOption(
                id="sample_test_cases.jsonl",
                label="Sample test cases (v1)",
                input_path="data/raw/sample_test_cases.jsonl",
                dataset_version="v1",
                evaluation_mode="regression",
            ),
            DatasetOption(
                id="regression_v1",
                label="Regression v1 (sample alias; dataset v1)",
                input_path="data/raw/sample_test_cases.jsonl",
                dataset_version="v1",
                evaluation_mode="regression",
            ),
            DatasetOption(
                id="adversarial_v1",
                label="MVP adversarial v1",
                input_path="data/adversarial/mvp_adversarial_v1.jsonl",
                dataset_version="adversarial_v1",
                evaluation_mode="adversarial",
            ),
        ],
        dataset_paths=dataset_paths,
        dataset_versions=dataset_versions,
        oracle_profiles=oracle_profiles,
        oracle_types=oracle_types,
        evaluation_modes=evaluation_modes,
    )


def _discover_oracle_profiles() -> list[str]:
    # Oracle selection and configuration belong to each dataset row, not a profile.
    return ["default"]


def _discover_dataset_paths() -> list[str]:
    discovered: list[str] = []
    for directory in (PROJECT_ROOT / "data" / "raw", PROJECT_ROOT / "data" / "adversarial"):
        if not directory.exists():
            continue
        for path in sorted(directory.glob("*.jsonl")):
            discovered.append(path.relative_to(PROJECT_ROOT).as_posix())
    if not discovered:
        discovered = ["sample_test_cases.jsonl"]
    return _dedupe_ordered(discovered)


def _discover_dataset_versions(dataset_paths: list[str]) -> list[str]:
    versions: list[str] = ["v1", "trace_replay_v1"]
    for relative_path in dataset_paths:
        path = PROJECT_ROOT / relative_path
        if not path.exists():
            continue
        try:
            with path.open(encoding="utf-8") as handle:
                for index, line in enumerate(handle):
                    if index >= 200:
                        break
                    raw = line.strip()
                    if not raw:
                        continue
                    try:
                        payload = json.loads(raw)
                    except json.JSONDecodeError:
                        continue
                    if not isinstance(payload, dict):
                        continue
                    dataset_version = payload.get("dataset_version")
                    if isinstance(dataset_version, str) and dataset_version.strip():
                        versions.append(dataset_version.strip())
        except OSError:
            continue
    return sorted({item.strip() for item in versions if item.strip()})


def _dedupe_ordered(items: list[str]) -> list[str]:
    seen: set[str] = set()
    result: list[str] = []
    for item in items:
        normalized = item.strip()
        if not normalized or normalized in seen:
            continue
        seen.add(normalized)
        result.append(normalized)
    return result
