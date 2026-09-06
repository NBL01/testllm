import json

import pytest

from llm_reliability_analytics.datasets.trace_loader import load_trace_replay_test_cases
from llm_reliability_analytics.models.domain import TestCase as Case, TestResult as Result
from llm_reliability_analytics.oracles.engine import evaluate_with_oracle
from llm_reliability_analytics.storage.duckdb_store import insert_batch_results, upsert_test_cases
from llm_reliability_analytics.storage.trace_repository import capture_traces_for_run, fetch_traces_page


@pytest.fixture(autouse=True)
def isolated_db(monkeypatch, tmp_path):
    monkeypatch.setenv("LLM_RELIABILITY_DB_PATH", str(tmp_path / "evidence.duckdb"))


def result(**updates):
    values = dict(
        run_id="run", test_case_id="case", prompt="What is 2 + 2?",
        expected_answer="4", raw_output="This requires more context.",
        actual_answer="This requires more context.", oracle_type="exact_match",
        is_correct=False, score=0, latency_ms=0, category="math",
        oracle_details_json=json.dumps({"input_config": {}, "comparison_result": "no_match"}),
    )
    return Result(**(values | updates))


def persist(results):
    insert_batch_results(results)
    capture_traces_for_run(results)


@pytest.mark.parametrize("oracle,expected,config,wrong,correct", [
    ("exact_match", "4", {}, "This requires more context.", "4"),
    ("exact_match", "Paris", {"strict_exact": True}, "Paris is wrong; London is correct", "Paris"),
    ("regex_match", "unused", {"valid_patterns": ["^YES$"], "ignore_case": False}, "yes", "YES"),
    ("numeric_tolerance", "4", {"tolerance": 0.2}, "5", "4.1"),
    ("json_schema", "", {"schema": {"type": "object", "required": ["ok"],
      "properties": {"ok": {"type": "boolean"}}, "additionalProperties": False}}, '{}', '{"ok": true}'),
])
def test_replay_preserves_original_truth_and_config(oracle, expected, config, wrong, correct):
    persist([result(oracle_type=oracle, expected_answer=expected, raw_output=wrong,
                    oracle_details_json=json.dumps({"input_config": config}))])
    case = load_trace_replay_test_cases("run", "replay-v1")[0]
    assert case.expected_answer == expected
    for key, value in config.items():
        assert case.metadata[key] == value
    assert not evaluate_with_oracle(oracle, case.expected_answer, wrong, case.metadata).is_correct
    assert evaluate_with_oracle(oracle, case.expected_answer, correct, case.metadata).is_correct


def test_trace_evidence_uses_attempt_snapshot_not_mutable_case():
    persist([result(), result(attempt_index=2, expected_answer="5",
                             oracle_details_json='{"input_config":{"strict_exact":true}}')])
    upsert_test_cases([Case(id="case", expected_answer="POISON", category="math",
                           difficulty="easy", prompt="changed", oracle_type="exact_match")])
    total, traces = fetch_traces_page(run_id="run", category="math", test_case_id="case")
    assert total == 2
    assert [trace["expected_answer"] for trace in traces] == ["4", "5"]
    assert traces[0]["oracle_details"]["comparison_result"] == "no_match"
    assert traces[0]["oracle_config"] == {}
    assert traces[1]["oracle_config"] == {"strict_exact": True}


@pytest.mark.parametrize("details", [None, "{}", "broken-json", "[]", '{"input_config":null}', '{"input_config":[]}'])
def test_legacy_replay_requires_review_when_config_missing(details):
    persist([result(oracle_details_json=details)])
    _, traces = fetch_traces_page(run_id="run")
    assert traces[0]["oracle_config"] is None
    with pytest.raises(ValueError, match="(?i)review.*config"):
        load_trace_replay_test_cases("run", "v2")


@pytest.mark.parametrize("updates", [{"expected_answer": None}, {"oracle_type": "invented"},
                                    {"oracle_type": None}, {"prompt": " "}])
def test_incomplete_evidence_never_silently_falls_back(updates):
    persist([result(**updates)])
    with pytest.raises(ValueError, match="(?i)review"):
        load_trace_replay_test_cases("run", "v2")


def test_trace_without_result_snapshot_is_visible_but_not_replayable():
    capture_traces_for_run([result()])
    _, traces = fetch_traces_page(run_id="run")
    assert traces[0]["expected_answer"] is None
    assert traces[0]["oracle_details"] == {}
    with pytest.raises(ValueError, match="(?i)review"):
        load_trace_replay_test_cases("run", "v2")


def test_tied_timestamps_have_stable_attempt_order_and_pages():
    persist([result(test_case_id=case, attempt_index=attempt)
             for case in ["z", "a"] for attempt in [2, 1]])
    _, traces = fetch_traces_page(run_id="run", max_rows=10)
    assert [(t["test_case_id"], t["attempt_index"]) for t in traces] == [
        ("a", 1), ("a", 2), ("z", 1), ("z", 2)]
    pages = [fetch_traces_page(run_id="run", max_rows=1, offset=i)[1][0] for i in range(4)]
    assert [t["trace_id"] for t in pages] == [t["trace_id"] for t in traces]


@pytest.mark.parametrize("actual", ["The answer is Paris", "Paris is wrong; London is correct"])
@pytest.mark.parametrize("metadata,passes", [({}, True), ({"strict_exact": True}, False),
    ({"strict_exact": True, "allow_substring_match": True}, True)])
def test_exact_match_strict_metadata_versus_legacy_lenient(metadata, passes, actual):
    evaluation = evaluate_with_oracle("exact_match", "Paris", actual, metadata)
    assert evaluation.is_correct is passes


def test_replay_does_not_normalize_original_prompt_or_answer():
    persist([result(prompt="  exact prompt\n", expected_answer="  original answer\n")])
    replay = load_trace_replay_test_cases("run", "v2")[0]
    assert replay.prompt == "  exact prompt\n"
    assert replay.expected_answer == "  original answer\n"


def test_trace_join_and_failure_filter_are_run_and_attempt_scoped():
    persist([result(), result(run_id="other", expected_answer="other truth"),
             result(attempt_index=2, is_correct=True, expected_answer="passing truth")])
    total, traces = fetch_traces_page(run_id="run", only_failed=True)
    assert total == 1
    assert traces[0]["expected_answer"] == "4"
    total, _ = fetch_traces_page(run_id="run", only_failed=False)
    assert total == 2


@pytest.mark.parametrize("oracle", ["exact_match", "semantic_match", "custom"])
def test_workflow_scoring_snapshot_replays_with_original_oracle_alias(oracle):
    from llm_reliability_analytics.workflow.service import score_results_with_oracles

    original = Case(id="case", category="math", difficulty="easy", prompt="2 + 2?",
                    expected_answer="4", oracle_type=oracle, metadata={"strict_exact": True})
    failed = result()
    score_results_with_oracles([original], [failed])
    persist([failed])
    replay = load_trace_replay_test_cases("run", "v2")[0]
    assert replay.oracle_type.value == oracle
    saved_config = json.loads(failed.oracle_details_json)["input_config"]
    for key, value in saved_config.items():
        assert replay.metadata[key] == value
    wrong = result(test_case_id=replay.id)
    corrected = result(test_case_id=replay.id, actual_answer="4")
    score_results_with_oracles([replay], [wrong, corrected])
    assert not wrong.is_correct
    assert corrected.is_correct
