# llm-reliability-analytics

Minimal demo backend for evaluating LLM reliability over batches of test cases.

## Stack

- Python 3.11
- FastAPI
- Pydantic
- DuckDB
- Pandas
- Pytest

## MVP Structure

```text
llm-reliability-analytics/
  src/llm_reliability_analytics/
    api/
    analytics/
    ingestion/
    models/
    oracles/
    runner/
    storage/
    workflow/
    main.py
  tests/
  notebooks/
  requirements.txt
  pytest.ini
```

## Architecture (5-7 min defense)

One clear pipeline:

1. **Ingestion**: load and validate test cases (`JSONL`/`CSV`) with Pydantic.
2. **Runner**: send prompts to a mock LLM and measure latency.
3. **Oracles**: score correctness using pluggable oracle types and normalized answers.
4. **Storage**: persist runs and results in DuckDB.
5. **Analytics**: compute reliability metrics and return a report.

Domain enhancements for iterative experiments:

- `dataset_version` on test cases and runs
- repeated-run tracking (`run_group_id`, `repetition_index`)
- normalized expected/actual answers in `test_results`
- error taxonomy (`runtime`, `oracle`, `timeout`, etc.)
- category-level and run-level report objects

Main orchestration is in:

- `src/llm_reliability_analytics/workflow/service.py`
- Full short architecture notes: `ARCHITECTURE.md`

## Quick Start

1. Create and activate a Python 3.11 virtualenv.
2. Install dependencies:

```bash
pip install -r requirements.txt
```

3. Run the API (Uvicorn):

```bash
uvicorn llm_reliability_analytics.main:app --app-dir src --reload
```

4. Open docs at `http://127.0.0.1:8000/docs`.

## API Endpoints

- `GET /health` - quick liveness check
- `POST /load-test-cases` - validate + store test cases from file
- `POST /run-batch` - execute one batch end-to-end
- `GET /report/{run_id}` - fetch analytics report for a run

Example:

```bash
curl http://127.0.0.1:8000/health
```

```bash
curl -X POST http://127.0.0.1:8000/load-test-cases \
  -H "Content-Type: application/json" \
  -d '{"input_path":"sample_test_cases.jsonl"}'
```

```bash
curl -X POST http://127.0.0.1:8000/run-batch \
  -H "Content-Type: application/json" \
  -d '{"input_path":"sample_test_cases.jsonl","dataset_version":"v1","run_group_id":"baseline","mode":"deterministic","seed":42,"limit":10,"run_name":"demo-run","model_name":"mock-llm"}'
```

```bash
curl http://127.0.0.1:8000/report/<run_id>
```

## Ingestion Loader (JSONL / CSV)

The project includes a file-based ingestion module that validates rows as `TestCase` objects:

```python
from llm_reliability_analytics.ingestion.loader import load_test_cases

test_cases, summary = load_test_cases("sample_test_cases.jsonl")
```

- Supports `.jsonl` and `.csv`
- Relative filenames are resolved from `data/raw/`
- Invalid rows are skipped and logged
- Returns:
  - `list[TestCase]`
  - `IngestionSummary(total_rows, valid_rows, invalid_rows)`

Example dataset:

- `data/raw/sample_test_cases.jsonl` (20 sample cases, mixed oracle types)

## Minimal Runner CLI

Run a batch with the mock LLM client:

```bash
python -m llm_reliability_analytics.cli.run_batch --input sample_test_cases.jsonl --mode deterministic
```

Options:

- `--input`: JSONL or CSV path (relative names resolve from `data/raw/`)
- `--mode`: `deterministic` or `semi_random`
- `--seed`: random seed for reproducibility
- `--limit`: run only the first N test cases
- `--run-name`: logical run label
- `--model-name`: model label
- `--output`: write full results to a JSON file

## Dataset Generator (300-case E2E benchmark)

Generate a structured dataset with balanced categories and save as JSONL + Parquet:

```bash
PYTHONPATH=src python -m llm_reliability_analytics.cli.generate_dataset \
  --total-cases 300 \
  --dataset-version v2.0-demo \
  --jsonl-path data/raw/llm_eval_dataset_v2_300.jsonl \
  --parquet-path data/raw/llm_eval_dataset_v2_300.parquet
```

Categories:

- `factual_qa`
- `classification`
- `information_extraction`
- `numeric_reasoning`
- `format_constrained_json`
- `instruction_following`
- `consistency_check`

## Notes

- This is intentionally MVP-level and focused on clarity over feature breadth.
- DuckDB file is created at `data/reliability.duckdb`.
- On startup, the app checks DuckDB table schemas; legacy tables are backed up
  as `*_backup_<timestamp>` and recreated to match the MVP schema.
- Notebook can read a custom DB path via `LLM_RELIABILITY_DB_PATH`.
