"""Edge cases written by an agy agent run (2026-11-21) to break recent behaviour; two exposed bugs, now fixed."""

import json
import pytest
from fastapi.testclient import TestClient

from llm_reliability_analytics.main import app
from llm_reliability_analytics.models.domain import TestResult as Result
from llm_reliability_analytics.oracles.engine import ExactMatchOracle, NumericToleranceOracle
from llm_reliability_analytics.storage.db import get_connection
from llm_reliability_analytics.storage.duckdb_store import create_test_run, insert_batch_results


# ---------------------------------------------------------------------------
# Probe 1: POST /evaluation-jobs/{id}/duplicate edge cases
# ---------------------------------------------------------------------------

def test_evaluation_job_duplicate_rejects_empty_model_name_for_openai_compatible(monkeypatch, tmp_path) -> None:
    db_path = tmp_path / "duplicate_empty_model.duckdb"
    monkeypatch.setenv("LLM_RELIABILITY_DB_PATH", str(db_path))
    client = TestClient(app)

    create_res = client.post(
        "/evaluation-jobs",
        json={
            "input_path": "sample_test_cases.jsonl",
            "provider": "mock",
            "model_name": "mock-baseline",
            "limit": 2,
        },
    )
    assert create_res.status_code == 201
    job_id = create_res.json()["job_id"]

    dup_res = client.post(
        f"/evaluation-jobs/{job_id}/duplicate",
        json={"provider": "openai_compatible", "model_name": ""},
    )
    assert dup_res.status_code in {400, 422}


def test_evaluation_job_duplicate_rejects_invalid_model_names(monkeypatch, tmp_path) -> None:
    db_path = tmp_path / "duplicate_invalid_model.duckdb"
    monkeypatch.setenv("LLM_RELIABILITY_DB_PATH", str(db_path))
    client = TestClient(app)

    create_res = client.post(
        "/evaluation-jobs",
        json={
            "input_path": "sample_test_cases.jsonl",
            "provider": "mock",
            "model_name": "mock-baseline",
            "limit": 2,
        },
    )
    assert create_res.status_code == 201
    job_id = create_res.json()["job_id"]

    # Model name containing spaces
    dup_res_spaces = client.post(
        f"/evaluation-jobs/{job_id}/duplicate",
        json={"provider": "openai_compatible", "model_name": "gpt 4o mini"},
    )
    assert dup_res_spaces.status_code == 400
    assert "Invalid model identifier" in dup_res_spaces.json()["detail"]

    # Model name starting with '-'
    dup_res_dash = client.post(
        f"/evaluation-jobs/{job_id}/duplicate",
        json={"provider": "openai_compatible", "model_name": "-gpt-4o"},
    )
    assert dup_res_dash.status_code == 400
    assert "Invalid model identifier" in dup_res_dash.json()["detail"]


def test_evaluation_job_duplicate_with_provider_local(monkeypatch, tmp_path) -> None:
    db_path = tmp_path / "duplicate_local.duckdb"
    monkeypatch.setenv("LLM_RELIABILITY_DB_PATH", str(db_path))
    client = TestClient(app)

    create_res = client.post(
        "/evaluation-jobs",
        json={
            "input_path": "sample_test_cases.jsonl",
            "provider": "mock",
            "model_name": "mock-baseline",
            "limit": 2,
        },
    )
    assert create_res.status_code == 201
    source = create_res.json()

    dup_res = client.post(
        f"/evaluation-jobs/{source['job_id']}/duplicate",
        json={"provider": "local", "model_name": "llama3.2:1b"},
    )
    assert dup_res.status_code == 201
    duplicated = dup_res.json()
    assert duplicated["job_id"] != source["job_id"]
    assert duplicated["status"] == "draft"
    assert duplicated["provider"] == "local"
    assert duplicated["model_name"] == "llama3.2:1b"
    assert duplicated["source_job_id"] == source["job_id"]
    assert duplicated["dataset_sha256"] == source["dataset_sha256"]


def test_evaluation_job_duplicate_nonexistent_job_returns_404(monkeypatch, tmp_path) -> None:
    db_path = tmp_path / "duplicate_404.duckdb"
    monkeypatch.setenv("LLM_RELIABILITY_DB_PATH", str(db_path))
    client = TestClient(app)

    dup_res = client.post(
        "/evaluation-jobs/nonexistent-job-id/duplicate",
        json={"provider": "mock", "model_name": "mock-baseline"},
    )
    assert dup_res.status_code == 404
    assert "Evaluation job not found" in dup_res.json()["detail"]


# ---------------------------------------------------------------------------
# Probe 2: GET /evaluation-jobs/{id}/failed-cases edge cases
# ---------------------------------------------------------------------------

def test_failed_cases_non_matching_filters_return_zero_total(monkeypatch, tmp_path) -> None:
    db_path = tmp_path / "failed_cases_filters.duckdb"
    monkeypatch.setenv("LLM_RELIABILITY_DB_PATH", str(db_path))
    client = TestClient(app)

    # Use mock-failing so there are guaranteed failures
    create_res = client.post(
        "/evaluation-jobs",
        json={
            "input_path": "sample_test_cases.jsonl",
            "provider": "mock",
            "model_name": "mock-failing",
            "limit": 3,
        },
    )
    assert create_res.status_code == 201
    job_id = create_res.json()["job_id"]

    run_res = client.post(f"/evaluation-jobs/{job_id}/run?wait=true")
    assert run_res.status_code == 200

    # Non-matching error_type returns total=0, items=[]
    res_err = client.get(f"/evaluation-jobs/{job_id}/failed-cases?error_type=nonexistent_error_type")
    assert res_err.status_code == 200
    payload_err = res_err.json()
    assert payload_err["total"] == 0
    assert payload_err["items"] == []

    # Non-matching category returns total=0, items=[]
    res_cat = client.get(f"/evaluation-jobs/{job_id}/failed-cases?category=nonexistent_category")
    assert res_cat.status_code == 200
    payload_cat = res_cat.json()
    assert payload_cat["total"] == 0
    assert payload_cat["items"] == []


def test_failed_cases_combined_filters(monkeypatch, tmp_path) -> None:
    db_path = tmp_path / "failed_cases_combined.duckdb"
    monkeypatch.setenv("LLM_RELIABILITY_DB_PATH", str(db_path))
    client = TestClient(app)

    create_res = client.post(
        "/evaluation-jobs",
        json={
            "input_path": "sample_test_cases.jsonl",
            "provider": "mock",
            "model_name": "mock-failing",
            "limit": 5,
        },
    )
    assert create_res.status_code == 201
    job_id = create_res.json()["job_id"]

    run_res = client.post(f"/evaluation-jobs/{job_id}/run?wait=true")
    assert run_res.status_code == 200

    all_failed_res = client.get(f"/evaluation-jobs/{job_id}/failed-cases?limit=100")
    assert all_failed_res.status_code == 200
    all_failed = all_failed_res.json()
    assert all_failed["total"] > 0
    first_item = all_failed["items"][0]
    matched_err = first_item["error_type"]
    matched_cat = first_item["category"]

    # Matching error_type with non-matching category
    res_mismatch = client.get(
        f"/evaluation-jobs/{job_id}/failed-cases?error_type={matched_err}&category=nonexistent_cat"
    )
    assert res_mismatch.status_code == 200
    assert res_mismatch.json()["total"] == 0
    assert res_mismatch.json()["items"] == []

    # Matching both error_type and category
    res_both = client.get(
        f"/evaluation-jobs/{job_id}/failed-cases?error_type={matched_err}&category={matched_cat}"
    )
    assert res_both.status_code == 200
    both_payload = res_both.json()
    assert both_payload["total"] >= 1
    for item in both_payload["items"]:
        assert item["error_type"] == matched_err
        assert item["category"] == matched_cat


def test_failed_cases_on_draft_job_returns_400(monkeypatch, tmp_path) -> None:
    db_path = tmp_path / "failed_cases_draft.duckdb"
    monkeypatch.setenv("LLM_RELIABILITY_DB_PATH", str(db_path))
    client = TestClient(app)

    create_res = client.post(
        "/evaluation-jobs",
        json={
            "input_path": "sample_test_cases.jsonl",
            "provider": "mock",
            "model_name": "mock-baseline",
            "limit": 2,
        },
    )
    assert create_res.status_code == 201
    job_id = create_res.json()["job_id"]

    failed_res = client.get(f"/evaluation-jobs/{job_id}/failed-cases")
    assert failed_res.status_code == 400
    assert "not completed yet" in failed_res.json()["detail"]


# ---------------------------------------------------------------------------
# Probe 3: POST /internal/metrics/compare edge cases
# ---------------------------------------------------------------------------

def test_metrics_compare_rejects_invalid_run_ids_count(monkeypatch, tmp_path) -> None:
    db_path = tmp_path / "compare_count.duckdb"
    monkeypatch.setenv("LLM_RELIABILITY_DB_PATH", str(db_path))
    client = TestClient(app)

    # 1 run_id -> 422
    res_one = client.post("/internal/metrics/compare", json={"run_ids": ["run-1"]})
    assert res_one.status_code == 422
    assert "Exactly two run_ids are required" in res_one.json()["detail"]

    # 3 run_ids -> 422
    res_three = client.post("/internal/metrics/compare", json={"run_ids": ["run-1", "run-2", "run-3"]})
    assert res_three.status_code == 422
    assert "Exactly two run_ids are required" in res_three.json()["detail"]


def test_metrics_compare_with_canceled_or_partial_run_returns_409(monkeypatch, tmp_path) -> None:
    db_path = tmp_path / "compare_canceled.duckdb"
    monkeypatch.setenv("LLM_RELIABILITY_DB_PATH", str(db_path))
    client = TestClient(app)

    job1_res = client.post("/evaluation-jobs", json={"input_path": "sample_test_cases.jsonl", "model_name": "mock-baseline", "limit": 2})
    job2_res = client.post("/evaluation-jobs", json={"input_path": "sample_test_cases.jsonl", "model_name": "mock-failing", "limit": 2})
    job_id_1 = job1_res.json()["job_id"]
    job_id_2 = job2_res.json()["job_id"]

    run1 = client.post(f"/evaluation-jobs/{job_id_1}/run?wait=true").json()["job"]["linked_run_id"]
    run2 = client.post(f"/evaluation-jobs/{job_id_2}/run?wait=true").json()["job"]["linked_run_id"]

    # Mark run2 as canceled in the storage database
    conn = get_connection()
    try:
        conn.execute("UPDATE test_runs SET status = 'canceled' WHERE id = ?", [run2])
    finally:
        conn.close()

    compare_res = client.post("/internal/metrics/compare", json={"run_ids": [run1, run2]})
    assert compare_res.status_code == 409
    payload = compare_res.json()
    assert payload["detail"]["eligible"] is False
    assert "only completed runs can be compared" in payload["detail"]["issues"]


def test_metrics_compare_swapped_runs_swaps_case_changes(monkeypatch, tmp_path) -> None:
    db_path = tmp_path / "compare_swapped.duckdb"
    monkeypatch.setenv("LLM_RELIABILITY_DB_PATH", str(db_path))
    client = TestClient(app)

    # Persist two comparable runs directly with matching metadata and test cases
    metadata = {
        "dataset_sha256": "f" * 64,
        "configuration": {"oracle_profile": "default", "timeout_seconds": 30, "seed": 42},
    }
    create_test_run(name="run_a", run_id="run_a", model_name="model_a", metadata=metadata,
                    provider="mock", mode="mock", repeat_count=1)
    create_test_run(name="run_b", run_id="run_b", model_name="model_b", metadata=metadata,
                    provider="mock", mode="mock", repeat_count=1)

    # In run_a: case_1 passes, case_2 fails
    # In run_b: case_1 fails, case_2 passes
    results_a = [
        Result(
            run_id="run_a", test_case_id="case_1", attempt_index=1, category="math",
            test_source="regression", oracle_type="exact_match", prompt="2 + 2?",
            expected_answer="4", actual_answer="4", is_correct=True, score=1.0,
            latency_ms=10.0, latency_source="mock_simulated", error_type=None,
            oracle_details_json=json.dumps({"input_config": {}}),
        ),
        Result(
            run_id="run_a", test_case_id="case_2", attempt_index=1, category="math",
            test_source="regression", oracle_type="exact_match", prompt="3 + 3?",
            expected_answer="6", actual_answer="7", is_correct=False, score=0.0,
            latency_ms=10.0, latency_source="mock_simulated", error_type="wrong_answer",
            oracle_details_json=json.dumps({"input_config": {}}),
        ),
    ]
    results_b = [
        Result(
            run_id="run_b", test_case_id="case_1", attempt_index=1, category="math",
            test_source="regression", oracle_type="exact_match", prompt="2 + 2?",
            expected_answer="4", actual_answer="5", is_correct=False, score=0.0,
            latency_ms=10.0, latency_source="mock_simulated", error_type="wrong_answer",
            oracle_details_json=json.dumps({"input_config": {}}),
        ),
        Result(
            run_id="run_b", test_case_id="case_2", attempt_index=1, category="math",
            test_source="regression", oracle_type="exact_match", prompt="3 + 3?",
            expected_answer="6", actual_answer="6", is_correct=True, score=1.0,
            latency_ms=10.0, latency_source="mock_simulated", error_type=None,
            oracle_details_json=json.dumps({"input_config": {}}),
        ),
    ]
    insert_batch_results(results_a)
    insert_batch_results(results_b)

    comp_a_b = client.post("/internal/metrics/compare", json={"run_ids": ["run_a", "run_b"]}).json()
    comp_b_a = client.post("/internal/metrics/compare", json={"run_ids": ["run_b", "run_a"]}).json()

    changes_a_b = comp_a_b["case_changes"]
    changes_b_a = comp_b_a["case_changes"]

    # Regressions in [A, B] must equal improvements in [B, A]
    assert len(changes_a_b["regressions"]) == len(changes_b_a["improvements"]) == 1
    assert len(changes_a_b["improvements"]) == len(changes_b_a["regressions"]) == 1

    # Specifically case_1 regressed from A to B and improved from B to A
    assert changes_a_b["regressions"][0]["test_case_id"] == "case_1"
    assert changes_a_b["regressions"][0]["baseline_passed"] == 1
    assert changes_a_b["regressions"][0]["candidate_passed"] == 0

    assert changes_b_a["improvements"][0]["test_case_id"] == "case_1"
    assert changes_b_a["improvements"][0]["baseline_passed"] == 0
    assert changes_b_a["improvements"][0]["candidate_passed"] == 1

    # Specifically case_2 improved from A to B and regressed from B to A
    assert changes_a_b["improvements"][0]["test_case_id"] == "case_2"
    assert changes_a_b["improvements"][0]["baseline_passed"] == 0
    assert changes_a_b["improvements"][0]["candidate_passed"] == 1

    assert changes_b_a["regressions"][0]["test_case_id"] == "case_2"
    assert changes_b_a["regressions"][0]["baseline_passed"] == 1
    assert changes_b_a["regressions"][0]["candidate_passed"] == 0


# ---------------------------------------------------------------------------
# Probe 4: Oracles with strict_output edge cases
# ---------------------------------------------------------------------------

def test_numeric_tolerance_oracle_strict_output_edge_cases(monkeypatch, tmp_path) -> None:
    oracle = NumericToleranceOracle()
    strict = {"tolerance": 0.0, "strict_output": True}

    # Expected "11", actual "-11" -> wrong answer
    res_neg = oracle.evaluate(expected_answer="11", actual_answer="-11", metadata=strict)
    assert res_neg.is_correct is False
    assert res_neg.error_type == "wrong_answer"

    # Expected "-11", actual "-11" -> correct
    res_neg_match = oracle.evaluate(expected_answer="-11", actual_answer="-11", metadata=strict)
    assert res_neg_match.is_correct is True
    assert res_neg_match.error_type is None

    # Expected "11", actual "+11" -> correct
    res_plus = oracle.evaluate(expected_answer="11", actual_answer="+11", metadata=strict)
    assert res_plus.is_correct is True
    assert res_plus.error_type is None

    # Expected "11", actual "11.0" -> correct
    res_float = oracle.evaluate(expected_answer="11", actual_answer="11.0", metadata=strict)
    assert res_float.is_correct is True
    assert res_float.error_type is None

    # Expected "10", actual "1e1" -> correct
    res_sci = oracle.evaluate(expected_answer="10", actual_answer="1e1", metadata=strict)
    assert res_sci.is_correct is True
    assert res_sci.error_type is None

    # Expected "11", actual " 11\n" -> correct (whitespace stripped)
    res_ws = oracle.evaluate(expected_answer="11", actual_answer=" 11\n", metadata=strict)
    assert res_ws.is_correct is True
    assert res_ws.error_type is None

    # Expected "11", actual "11!" -> format_violation (extra non-numeric text)
    res_excl = oracle.evaluate(expected_answer="11", actual_answer="11!", metadata=strict)
    assert res_excl.is_correct is False
    assert res_excl.error_type == "format_violation"

    # Unicode digits: Arabic-Indic digits "١١" evaluate to 11.0 in Python float() -> correct
    res_unicode = oracle.evaluate(expected_answer="11", actual_answer="١١", metadata=strict)
    assert res_unicode.is_correct is True
    assert res_unicode.error_type is None

    # Non-matching Unicode digits: Arabic-Indic digits "٢٢" evaluate to 22.0 != 11.0 -> wrong_answer
    res_unicode_diff = oracle.evaluate(expected_answer="11", actual_answer="٢٢", metadata=strict)
    assert res_unicode_diff.is_correct is False
    assert res_unicode_diff.error_type == "wrong_answer"

    # Non-decimal Unicode characters (e.g. Roman numerals "XI") -> numeric_parse_error
    res_roman = oracle.evaluate(expected_answer="11", actual_answer="XI", metadata=strict)
    assert res_roman.is_correct is False
    assert res_roman.error_type == "numeric_parse_error"

    # Empty string -> numeric_parse_error
    res_empty = oracle.evaluate(expected_answer="11", actual_answer="", metadata=strict)
    assert res_empty.is_correct is False
    assert res_empty.error_type == "numeric_parse_error"

    # None -> numeric_parse_error
    res_none = oracle.evaluate(expected_answer="11", actual_answer=None, metadata=strict)
    assert res_none.is_correct is False
    assert res_none.error_type == "numeric_parse_error"


def test_exact_match_oracle_strict_output_edge_cases(monkeypatch, tmp_path) -> None:
    oracle = ExactMatchOracle()
    strict = {"strict_output": True}

    # Expected "11", actual "+11" -> correct
    res_plus = oracle.evaluate(expected_answer="11", actual_answer="+11", metadata=strict)
    assert res_plus.is_correct is True
    assert res_plus.error_type is None

    # Expected "-11", actual "-11" -> correct
    res_neg_match = oracle.evaluate(expected_answer="-11", actual_answer="-11", metadata=strict)
    assert res_neg_match.is_correct is True
    assert res_neg_match.error_type is None

    # Expected "11", actual " 11\n" -> correct
    res_ws = oracle.evaluate(expected_answer="11", actual_answer=" 11\n", metadata=strict)
    assert res_ws.is_correct is True
    assert res_ws.error_type is None

    # Expected "11", actual "11!" -> correct (normalization strips punctuation)
    res_excl = oracle.evaluate(expected_answer="11", actual_answer="11!", metadata=strict)
    assert res_excl.is_correct is True
    assert res_excl.error_type is None

    # Expected "10", actual "1e1" -> correct via numeric equivalent fallback
    res_sci = oracle.evaluate(expected_answer="10", actual_answer="1e1", metadata=strict)
    assert res_sci.is_correct is True
    assert res_sci.error_type is None

    # Expected "11", actual "11.0" -> plain numbers compare numerically (as "1e1" vs "10" below and the
    # strict numeric oracle do), so the same value passes even under strict_output.
    res_float = oracle.evaluate(expected_answer="11", actual_answer="11.0", metadata=strict)
    assert res_float.is_correct is True
    assert res_float.error_type is None

    # Unicode digits: Arabic-Indic "١١" -> parsed as 11.0 in numeric fallback -> correct
    res_unicode = oracle.evaluate(expected_answer="11", actual_answer="١١", metadata=strict)
    assert res_unicode.is_correct is True
    assert res_unicode.error_type is None

    # Non-matching Unicode digits: Arabic-Indic "٢٢" -> wrong_answer
    res_unicode_diff = oracle.evaluate(expected_answer="11", actual_answer="٢٢", metadata=strict)
    assert res_unicode_diff.is_correct is False
    assert res_unicode_diff.error_type == "wrong_answer"

    # Non-decimal Unicode characters (Roman numeral "XI") -> wrong_answer
    res_roman = oracle.evaluate(expected_answer="11", actual_answer="XI", metadata=strict)
    assert res_roman.is_correct is False
    assert res_roman.error_type == "wrong_answer"

    # Empty string -> wrong_answer
    res_empty = oracle.evaluate(expected_answer="11", actual_answer="", metadata=strict)
    assert res_empty.is_correct is False
    assert res_empty.error_type == "wrong_answer"

    # None -> wrong_answer
    res_none = oracle.evaluate(expected_answer="11", actual_answer=None, metadata=strict)
    assert res_none.is_correct is False
    assert res_none.error_type == "wrong_answer"


def test_exact_match_oracle_strict_output_rejects_negative_answer_for_positive_expected(monkeypatch, tmp_path) -> None:
    oracle = ExactMatchOracle()
    strict = {"strict_output": True}
    # "-11" is not 11; ExactMatchOracle should not match negative numbers to positive numbers
    res = oracle.evaluate(expected_answer="11", actual_answer="-11", metadata=strict)
    assert res.is_correct is False
    assert res.error_type in {"wrong_answer", "format_violation"}


def test_exact_match_oracle_strict_output_multi_word_expected(monkeypatch, tmp_path) -> None:
    oracle = ExactMatchOracle()
    strict = {"strict_output": True}

    # Exact multi-word match
    res_exact = oracle.evaluate(expected_answer="San Francisco", actual_answer="San Francisco", metadata=strict)
    assert res_exact.is_correct is True
    assert res_exact.error_type is None
    assert res_exact.details["comparison_result"] == "exact_match"

    # Multi-word with punctuation and whitespace normalization
    res_norm = oracle.evaluate(expected_answer="San Francisco", actual_answer="  san, francisco! ", metadata=strict)
    assert res_norm.is_correct is True
    assert res_norm.error_type is None
    assert res_norm.details["comparison_result"] == "exact_match"

    # Embedded in a sentence -> rejected as format_violation
    res_sentence = oracle.evaluate(
        expected_answer="San Francisco",
        actual_answer="I traveled to San Francisco yesterday.",
        metadata=strict,
    )
    assert res_sentence.is_correct is False
    assert res_sentence.error_type == "format_violation"
    assert res_sentence.details["comparison_result"] == "contains_match_rejected_by_strict_output"

    # Partial prefix only -> wrong answer
    res_partial = oracle.evaluate(expected_answer="San Francisco", actual_answer="San", metadata=strict)
    assert res_partial.is_correct is False
    assert res_partial.error_type == "wrong_answer"

    # Completely different multi-word -> wrong answer
    res_diff = oracle.evaluate(expected_answer="San Francisco", actual_answer="New York", metadata=strict)
    assert res_diff.is_correct is False
    assert res_diff.error_type == "wrong_answer"

    # Multi-candidate valid answers (with ||)
    res_multi_cand = oracle.evaluate(
        expected_answer="San Francisco || New York City",
        actual_answer="New York City",
        metadata=strict,
    )
    assert res_multi_cand.is_correct is True
    assert res_multi_cand.details["comparison_result"] == "exact_match"


# ---------------------------------------------------------------------------
# Probe 5: POST /evaluation-jobs/{id}/cancel lifecycle edge cases
# ---------------------------------------------------------------------------

def test_job_cancel_lifecycle_edge_cases(monkeypatch, tmp_path) -> None:
    db_path = tmp_path / "cancel_lifecycle.duckdb"
    monkeypatch.setenv("LLM_RELIABILITY_DB_PATH", str(db_path))
    client = TestClient(app)

    # 1. Cancel twice on a draft
    draft_res = client.post(
        "/evaluation-jobs",
        json={"input_path": "sample_test_cases.jsonl", "model_name": "mock-baseline", "limit": 2},
    )
    assert draft_res.status_code == 201
    draft_id = draft_res.json()["job_id"]

    cancel1 = client.post(f"/evaluation-jobs/{draft_id}/cancel", json={"reason": "first cancel"})
    assert cancel1.status_code == 200
    assert cancel1.json()["status"] == "canceled"

    # Second cancel is idempotent
    cancel2 = client.post(f"/evaluation-jobs/{draft_id}/cancel", json={"reason": "second cancel"})
    assert cancel2.status_code == 200
    assert cancel2.json()["status"] == "canceled"

    # 2. Run on canceled job -> 409
    run_on_canceled = client.post(f"/evaluation-jobs/{draft_id}/run?wait=true")
    assert run_on_canceled.status_code == 409
    assert "cannot run from status=canceled" in run_on_canceled.json()["detail"]

    # 3. Cancel on completed job -> 409
    job2_res = client.post(
        "/evaluation-jobs",
        json={"input_path": "sample_test_cases.jsonl", "model_name": "mock-baseline", "limit": 2},
    )
    assert job2_res.status_code == 201
    job2_id = job2_res.json()["job_id"]

    run_res = client.post(f"/evaluation-jobs/{job2_id}/run?wait=true")
    assert run_res.status_code == 200
    assert run_res.json()["job"]["status"] == "completed"

    cancel_completed = client.post(f"/evaluation-jobs/{job2_id}/cancel", json={"reason": "too late"})
    assert cancel_completed.status_code == 409
    assert "cannot be canceled from status=completed" in cancel_completed.json()["detail"]


# ---------------------------------------------------------------------------
# Probe 6: GET /evaluation-jobs list progress and attempts null semantics
# ---------------------------------------------------------------------------

def test_job_list_progress_and_attempts_null_semantics(monkeypatch, tmp_path) -> None:
    db_path = tmp_path / "list_null_semantics.duckdb"
    monkeypatch.setenv("LLM_RELIABILITY_DB_PATH", str(db_path))
    client = TestClient(app)

    # Create draft job (non-running, unexecuted)
    draft_res = client.post(
        "/evaluation-jobs",
        json={"input_path": "sample_test_cases.jsonl", "model_name": "mock-baseline", "limit": 2},
    )
    assert draft_res.status_code == 201
    draft_id = draft_res.json()["job_id"]

    # Create completed job (non-running, executed)
    completed_res = client.post(
        "/evaluation-jobs",
        json={"input_path": "sample_test_cases.jsonl", "model_name": "mock-baseline", "limit": 2},
    )
    assert completed_res.status_code == 201
    completed_id = completed_res.json()["job_id"]
    client.post(f"/evaluation-jobs/{completed_id}/run?wait=true")

    # Fetch list
    list_res = client.get("/evaluation-jobs")
    assert list_res.status_code == 200
    items = {item["job_id"]: item for item in list_res.json()["items"]}

    draft_item = items[draft_id]
    completed_item = items[completed_id]

    # For non-running jobs: progress_done and progress_total must be null
    assert draft_item["progress_done"] is None
    assert draft_item["progress_total"] is None
    assert completed_item["progress_done"] is None
    assert completed_item["progress_total"] is None

    # For draft jobs: attempts and passed_attempts must be null
    assert draft_item["attempts"] is None
    assert draft_item["passed_attempts"] is None

    # For completed jobs: attempts and passed_attempts are recorded integers
    assert isinstance(completed_item["attempts"], int)
    assert isinstance(completed_item["passed_attempts"], int)
    assert completed_item["attempts"] == 2
    assert completed_item["passed_attempts"] >= 0


# ---------------------------------------------------------------------------
# Probe 7: Job create with openai_compatible and options payload
# ---------------------------------------------------------------------------

def test_job_create_rejects_empty_openai_compatible_model(monkeypatch, tmp_path) -> None:
    db_path = tmp_path / "create_openai_compat.duckdb"
    monkeypatch.setenv("LLM_RELIABILITY_DB_PATH", str(db_path))
    client = TestClient(app)

    # Empty string model_name -> 422 (or 400)
    res_empty = client.post(
        "/evaluation-jobs",
        json={
            "input_path": "sample_test_cases.jsonl",
            "provider": "openai_compatible",
            "model_name": "",
        },
    )
    assert res_empty.status_code in {400, 422}

    # Whitespace model_name -> 422 (or 400)
    res_ws = client.post(
        "/evaluation-jobs",
        json={
            "input_path": "sample_test_cases.jsonl",
            "provider": "openai_compatible",
            "model_name": "   ",
        },
    )
    assert res_ws.status_code in {400, 422}


def test_job_options_includes_openai_compatible_and_base_url(monkeypatch, tmp_path) -> None:
    db_path = tmp_path / "options_openai_compat.duckdb"
    monkeypatch.setenv("LLM_RELIABILITY_DB_PATH", str(db_path))
    client = TestClient(app)

    options_res = client.get("/evaluation-jobs/options")
    assert options_res.status_code == 200
    payload = options_res.json()

    assert "openai_compatible" in payload["providers"]
    assert "openai_compatible" in payload["models_by_provider"]
    assert "openai_compatible_base_url" in payload
    assert isinstance(payload["openai_compatible_base_url"], str)
    assert len(payload["openai_compatible_base_url"]) > 0
    assert payload["openai_compatible_base_url"].startswith("http")
