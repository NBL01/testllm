from __future__ import annotations

import pytest
from fastapi.testclient import TestClient

from llm_reliability_analytics.ingestion.loader import load_test_cases, resolve_input_path
from llm_reliability_analytics.main import app
from llm_reliability_analytics.runner.client_factory import build_llm_client
from llm_reliability_analytics.runner.mock_client import MockLLMClient
from llm_reliability_analytics.runner.ollama_client import OllamaLLMClient
from llm_reliability_analytics.runner.test_runner import TestRunner as Runner
from llm_reliability_analytics.workflow import evaluation_job_options as catalog


def test_options_expose_three_mock_models() -> None:
    payload = TestClient(app).get("/evaluation-jobs/options").json()

    assert payload["models_by_provider"]["mock"] == [
        "mock-baseline", "mock-noisy", "mock-failing",
    ]


def test_options_expose_only_effective_oracle_profile(monkeypatch) -> None:
    monkeypatch.setenv("LLM_RELIABILITY_ORACLE_PROFILES", "strict,finance-risk")

    payload = TestClient(app).get("/evaluation-jobs/options").json()

    assert payload["oracle_profiles"] == ["default"]


def test_catalog_has_truthful_presets_and_retains_legacy_option_fields() -> None:
    payload = catalog.get_evaluation_job_options().model_dump()
    datasets = {entry["id"]: entry for entry in payload["datasets"]}

    assert set(datasets) == {"sample_test_cases.jsonl", "regression_v1", "adversarial_v1"}
    for entry in datasets.values():
        assert set(entry) == {"id", "label", "input_path", "dataset_version", "evaluation_mode"}
        assert entry["label"].strip()
        cases, summary = load_test_cases(entry["input_path"])
        assert cases
        assert summary.invalid_rows == 0
        assert summary.dataset_versions == [entry["dataset_version"]]
        assert set(summary.test_source_distribution) == {entry["evaluation_mode"]}

    sample = datasets["sample_test_cases.jsonl"]
    regression = datasets["regression_v1"]
    assert resolve_input_path(sample["input_path"]) == resolve_input_path(regression["input_path"])
    assert regression["dataset_version"] == "v1"
    assert "sample" in regression["label"].lower()
    assert "alias" in regression["label"].lower()
    assert datasets["adversarial_v1"]["input_path"] == "data/adversarial/mvp_adversarial_v1.jsonl"
    assert datasets["adversarial_v1"]["dataset_version"] == "adversarial_v1"
    assert "dataset_paths" in payload
    assert "v1" in payload["dataset_versions"]


def test_adversarial_fixture_is_valid_and_keeps_per_case_oracles() -> None:
    path = catalog.PROJECT_ROOT / "data/adversarial/mvp_adversarial_v1.jsonl"
    assert path.is_file()
    cases, summary = load_test_cases(path)

    assert len(cases) >= 5
    assert len({case.id for case in cases}) == len(cases)
    assert summary.invalid_rows == 0
    assert summary.dataset_versions == ["adversarial_v1"]
    assert summary.test_source_distribution == {"adversarial": len(cases)}
    assert {case.oracle_type.value for case in cases} >= {"keyword_match", "regex_match", "json_schema"}
    assert all(case.metadata.get("keywords") for case in cases if case.oracle_type.value == "keyword_match")


@pytest.mark.parametrize("invalid_row", [
    "null", "[]", '[{"dataset_version":"not-a-row"}]', '"text"', "42", "true",
    '{"dataset_version":', '{"dataset_version": []}', '{"dataset_version": {}}',
])
def test_discovery_skips_malformed_rows_and_continues(monkeypatch, tmp_path, invalid_row) -> None:
    directory = tmp_path / "data/raw"
    directory.mkdir(parents=True)
    (directory / "mixed.jsonl").write_text(
        invalid_row + '\n{"dataset_version":" discovered_v2 "}\n', encoding="utf-8",
    )
    monkeypatch.setattr(catalog, "PROJECT_ROOT", tmp_path)

    options = catalog.get_evaluation_job_options()

    assert options.dataset_paths == ["data/raw/mixed.jsonl"]
    assert "discovered_v2" in options.dataset_versions
    assert "not-a-row" not in options.dataset_versions


def test_named_noisy_mock_changes_outputs_reproducibly() -> None:
    prompts = ["What is the capital of Japan?"] * 40
    baseline = build_llm_client("mock", "mock", "mock-baseline", seed=42)
    noisy = build_llm_client("mock", "mock", "mock-noisy", seed=42)
    replay = build_llm_client("mock", "mock", "mock-noisy", seed=42)
    other_seed = build_llm_client("mock", "mock", "mock-noisy", seed=43)

    baseline_outputs = [baseline.generate(prompt) for prompt in prompts]
    noisy_outputs = [noisy.generate(prompt) for prompt in prompts]

    assert noisy_outputs != baseline_outputs
    assert noisy_outputs == [replay.generate(prompt) for prompt in prompts]
    assert noisy_outputs != [other_seed.generate(prompt) for prompt in prompts]
    assert noisy.mode == "semi_random"
    assert noisy.failure_rate == 0.0


def test_named_failing_mock_always_raises_reproducibly() -> None:
    for seed in (42, 43):
        client = build_llm_client("mock", "mock", "mock-failing", seed=seed)
        for prompt in ("What is 2 + 2?", "unrecognized prompt", ""):
            with pytest.raises(RuntimeError, match="mock_generation_error"):
                client.generate(prompt)
        assert client.mode == "semi_random"
        assert client.failure_rate == 1.0


@pytest.mark.parametrize("model_name", [None, "legacy-mock-label", "mock-baseline"])
@pytest.mark.parametrize("mode,failure_rate", [("deterministic", 0.0), ("semi_random", 0.0), ("semi_random", 1.0)])
def test_legacy_direct_mock_configuration_is_preserved(model_name, mode, failure_rate) -> None:
    client = build_llm_client(
        "mock", "mock", model_name, mock_mode=mode, seed=17, failure_rate=failure_rate,
    )
    legacy = MockLLMClient(mode=mode, seed=17, failure_rate=failure_rate)

    assert client.mode == legacy.mode
    assert client.seed == legacy.seed
    assert client.failure_rate == legacy.failure_rate
    for _ in range(20):
        if failure_rate == 1.0:
            with pytest.raises(RuntimeError, match="mock_generation_error"):
                client.generate("What is the capital of Japan?")
        else:
            assert client.generate("What is the capital of Japan?") == legacy.generate("What is the capital of Japan?")


@pytest.mark.parametrize("provider,run_mode", [("ollama", "mock"), ("local", "mock"), ("mock", "real_local")])
def test_mock_presets_do_not_override_real_local_routing(provider, run_mode) -> None:
    assert isinstance(build_llm_client(provider, run_mode, "mock-failing"), OllamaLLMClient)


@pytest.mark.parametrize("dataset_id", ["sample_test_cases.jsonl", "regression_v1", "adversarial_v1"])
@pytest.mark.parametrize("model_name", ["mock-baseline", "mock-noisy", "mock-failing"])
def test_every_catalog_preset_runs_with_each_mock_model(dataset_id, model_name) -> None:
    payload = catalog.get_evaluation_job_options().model_dump()
    dataset = next(entry for entry in payload["datasets"] if entry["id"] == dataset_id)
    cases, _ = load_test_cases(dataset["input_path"])
    runner = Runner(build_llm_client("mock", "mock", model_name, seed=42))

    results = runner.run(cases)

    assert len(results) == len(cases)
    assert {result.dataset_version for result in results} == {dataset["dataset_version"]}
    if model_name == "mock-failing":
        assert all(result.error_type == "RuntimeError" and result.raw_output is None for result in results)
    else:
        assert all(result.error_type is None and result.raw_output is not None for result in results)
