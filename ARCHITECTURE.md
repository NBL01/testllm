# Architecture Notes (Defense Demo)

## Goal

Provide a small, explainable backend that demonstrates reliability evaluation of LLM outputs.

## Core Components

- `ingestion/loader.py`
  - Loads `JSONL` or `CSV`
  - Validates each row with Pydantic `TestCase`
  - Tracks dataset quality summary (categories, oracle mix, dataset versions)
  - Skips invalid rows and reports summary

- `runner/mock_client.py` + `runner/test_runner.py`
  - Sends prompts to a deterministic/semi-random mock LLM
  - Records latency for each test case

- `oracles/engine.py`
  - Scores answers (`exact_match`, `regex_match`, `keyword_match`, `numeric_tolerance`, `json_schema`)

- `storage/duckdb_store.py`
  - Persists versioned test cases, repeated runs, and normalized results in DuckDB
  - Provides SQL summaries for run-level metrics

- `analytics/reliability.py`
  - Computes reliability report from `TestResult` list

- `workflow/service.py`
  - Orchestrates the end-to-end pipeline
  - Used by FastAPI routes

## Request Flow

1. `POST /load-test-cases`:
   - Validate + store test cases
2. `POST /run-batch`:
   - Load -> run mock LLM -> oracle score -> store -> aggregate report
3. `GET /report/{run_id}`:
   - Return persisted summary + computed analytics

## 5-7 Minute Presentation Script

1. Show project objective and stack (FastAPI + DuckDB + Pydantic).
2. Explain one pipeline: ingestion -> runner -> oracle -> storage -> analytics.
3. Trigger `POST /run-batch` on sample data.
4. Open `GET /report/{run_id}` and explain:
   - passed/failed
   - accuracy
   - latency
   - category-wise performance
   - error distribution + taxonomy
   - repeated-run metadata (`dataset_version`, `repetition_index`)
5. Mention that each module can be replaced later by real LLM clients and richer oracles.
