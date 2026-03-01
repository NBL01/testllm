import json

import duckdb

from llm_reliability_analytics.datasets.generator import (
    DatasetGenerationConfig,
    DEFAULT_CATEGORIES,
    generate_dataset_records,
    save_dataset_files,
)


def test_generate_dataset_records_count_and_balance() -> None:
    config = DatasetGenerationConfig(total_cases=300, dataset_version="v2.0-demo")
    records = generate_dataset_records(config)

    assert len(records) == 300
    category_counts: dict[str, int] = {}
    for record in records:
        category_counts[record.category] = category_counts.get(record.category, 0) + 1
        assert record.dataset_version == "v2.0-demo"
        assert record.id
        assert record.prompt
        assert record.expected_answer is not None
        assert record.oracle_type.value
        assert isinstance(record.metadata, dict)

    assert set(category_counts.keys()) == set(DEFAULT_CATEGORIES)
    counts = list(category_counts.values())
    assert max(counts) - min(counts) <= 1


def test_save_dataset_files_jsonl_and_parquet(tmp_path) -> None:
    config = DatasetGenerationConfig(
        total_cases=30,
        dataset_version="v2.1-test",
        output_jsonl=tmp_path / "dataset.jsonl",
        output_parquet=tmp_path / "dataset.parquet",
    )
    records = generate_dataset_records(config)
    save_dataset_files(records, config.output_jsonl, config.output_parquet)

    assert config.output_jsonl.exists()
    assert config.output_parquet.exists()

    with config.output_jsonl.open("r", encoding="utf-8") as fh:
        lines = [line.strip() for line in fh if line.strip()]
    assert len(lines) == 30
    first_row = json.loads(lines[0])
    required_fields = {
        "id",
        "category",
        "difficulty",
        "prompt",
        "expected_answer",
        "oracle_type",
        "metadata",
        "dataset_version",
    }
    assert required_fields.issubset(set(first_row.keys()))

    conn = duckdb.connect()
    count = conn.execute("SELECT COUNT(*) FROM read_parquet(?)", [str(config.output_parquet)]).fetchone()[0]
    conn.close()
    assert count == 30
