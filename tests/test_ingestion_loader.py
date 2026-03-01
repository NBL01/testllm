import csv
import json

from llm_reliability_analytics.ingestion.loader import load_test_cases


def test_load_sample_jsonl_from_raw_directory() -> None:
    test_cases, summary = load_test_cases("sample_test_cases.jsonl")

    assert len(test_cases) == 20
    assert summary.total_rows == 20
    assert summary.valid_rows == 20
    assert summary.invalid_rows == 0


def test_skip_invalid_rows_and_keep_valid_rows(tmp_path) -> None:
    csv_path = tmp_path / "mixed.csv"
    with csv_path.open("w", encoding="utf-8", newline="") as file_handle:
        writer = csv.DictWriter(
            file_handle,
            fieldnames=[
                "id",
                "category",
                "difficulty",
                "prompt",
                "expected_answer",
                "oracle_type",
                "metadata",
            ],
        )
        writer.writeheader()
        writer.writerow(
            {
                "id": "row-1",
                "category": "math",
                "difficulty": "easy",
                "prompt": "What is 1+1?",
                "expected_answer": "2",
                "oracle_type": "exact_match",
                "metadata": "{\"source\":\"unit-test\"}",
            }
        )
        writer.writerow(
            {
                "id": "row-2",
                "category": "math",
                "difficulty": "impossible",
                "prompt": "What is 2+2?",
                "expected_answer": "4",
                "oracle_type": "exact_match",
                "metadata": "{\"source\":\"unit-test\"}",
            }
        )
        writer.writerow(
            {
                "id": "row-3",
                "category": "factual",
                "difficulty": "medium",
                "prompt": "Capital of Italy?",
                "expected_answer": "Rome",
                "oracle_type": "semantic_match",
                "metadata": "{\"source\":\"unit-test\"}",
            }
        )

    test_cases, summary = load_test_cases(csv_path)

    assert len(test_cases) == 2
    assert summary.total_rows == 3
    assert summary.valid_rows == 2
    assert summary.invalid_rows == 1
    assert test_cases[0].metadata == {"source": "unit-test"}


def test_jsonl_invalid_json_is_skipped(tmp_path) -> None:
    jsonl_path = tmp_path / "mixed.jsonl"
    valid_row = {
        "category": "factual",
        "difficulty": "easy",
        "prompt": "Capital of Germany?",
        "expected_answer": "Berlin",
        "oracle_type": "exact_match",
        "metadata": {"source": "unit-test"},
    }
    jsonl_path.write_text(
        "\n".join([json.dumps(valid_row), "{not-valid-json}", json.dumps(valid_row)]),
        encoding="utf-8",
    )

    test_cases, summary = load_test_cases(jsonl_path)
    assert len(test_cases) == 2
    assert summary.total_rows == 3
    assert summary.valid_rows == 2
    assert summary.invalid_rows == 1
