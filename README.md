# llm-reliability-analytics

LLM reliability evaluation platform with:
- structured test datasets
- pluggable correctness oracles
- repeatable batch runs
- DuckDB-backed analytics
- Streamlit dashboard

## Stack

- Python 3.11
- FastAPI
- Pydantic
- DuckDB
- Pandas
- Streamlit
- Pytest

## Architecture

Pipeline:
1. Ingestion: load/validate test cases (`JSONL`/`CSV`)
2. Runner: execute prompts with selected provider (`mock` or local `ollama`)
3. Oracle engine: score outputs
4. Storage: persist runs/results in DuckDB
5. Analytics: compute reliability metrics
6. Reporting/UI: API + Streamlit dashboard

Hybrid evaluation sources:
- `regression`: curated static benchmarks
- `trace_replay`: replay cases promoted from real failed traces
- `adversarial`: targeted edge/safety/prompt-override checks
- `synthetic`: generated broad-coverage cases

## Project Layout

```text
llm-reliability-analytics/
  src/llm_reliability_analytics/
    api/
    analytics/
    cli/
    ingestion/
    models/
    oracles/
    reporting/
    runner/
    storage/
    workflow/
  frontend/
    streamlit_app.py
    components/
    services/
    utils/
  scripts/
    run_batch.py
  data/
```

## Local Installation

### 1) Create and activate virtual environment

For `bash/zsh`:
```bash
python -m venv .venv
source .venv/bin/activate
```

For `fish`:
```fish
python -m venv .venv
source .venv/bin/activate.fish
```

### 2) Install dependencies

```bash
python -m pip install --upgrade pip
pip install -r requirements.txt
```

## Ollama Setup (Local Models)

### 1) Install and start Ollama

```bash
ollama serve
```

### 2) Pull a lightweight model (recommended for laptop hardware)

```bash
ollama pull llama3.2:1b
```

Other recommended lightweight options:
```bash
ollama pull qwen2.5:0.5b
ollama pull qwen2.5:1.5b
ollama pull gemma2:2b
```

Optional (heavier):
```bash
ollama pull llama3.2:3b
ollama pull phi3
```

### 3) Verify installed models

```bash
ollama list
```

## Running the Backend API

```bash
uvicorn llm_reliability_analytics.main:app --app-dir src --reload
```

Open docs:
- http://127.0.0.1:8000/docs

## Running Streamlit Dashboard

```bash
streamlit run frontend/streamlit_app.py
```

## Running Evaluations with a Selected Local Model

### Frontend flow
1. Open Streamlit.
2. Use **Run New Evaluation**.
3. Select provider:
   - `Mock`
   - `Ollama (local)`
4. Select model (`llama3.2:1b`, `qwen2.5:1.5b`, etc.).
5. Set `temperature`, `repeat_count`, `max_output_tokens`.
6. Click **Start Evaluation Run**.
7. After completion, choose the run in sidebar and verify:
   - run label
   - provider
   - model name
   - mode

### CLI flow

Mock:
```bash
python scripts/run_batch.py --provider mock --model mock-baseline
```

Ollama local:
```bash
python scripts/run_batch.py --provider ollama --model llama3.2:1b
python scripts/run_batch.py --provider ollama --model qwen2.5:1.5b --repeat-count 2
```

Common options:
- `--dataset sample_test_cases.jsonl`
- `--temperature 0.1`
- `--max-output-tokens 128`
- `--run-name local-ollama-baseline`
- `--evaluation-mode regression|exploratory|adversarial|trace_replay`

## Hybrid Evaluation Workflow

1. Run a normal regression/adversarial batch.
2. System stores full traces in DuckDB (`evaluation_traces` table).
3. Inspect failed/low-score cases in Streamlit Result Inspector.
4. Mark failed traces as candidates for regression/adversarial sets.
5. Replay traces in a future run.

Trace replay CLI example:
```bash
python scripts/run_batch.py \
  --provider ollama \
  --model qwen2.5:0.5b \
  --trace-replay-run-id <source_run_id> \
  --trace-replay-only-failed \
  --run-name trace-replay-check
```

Adversarial dataset example:
```bash
python scripts/run_batch.py \
  --provider ollama \
  --model llama3.2:1b \
  --dataset adversarial/sample_adversarial_test_cases.jsonl \
  --evaluation-mode adversarial \
  --run-name adversarial-smoke
```

## API Endpoints

- `GET /health`
- `POST /load-test-cases`
- `POST /run-batch`
- `GET /report/{run_id}`
- `POST /candidates/generate`
- `GET /candidates`
- `POST /candidates/{candidate_id}/status`
- `GET /candidates/{candidate_id}/events`

## V2 Scope and Roadmap

- Product scope: `docs/PRODUCT_SCOPE_V2.md`
- Delivery roadmap: `docs/ROADMAP_V2.md`

## Candidate Test Authoring (V2 Starter)

Generate review candidates with seeded logic:

```bash
python scripts/generate_candidates.py --categories factual_qa,classification --per-category 5
```

Optional model-assisted prompt rewrite:

```bash
python scripts/generate_candidates.py \
  --provider ollama \
  --model qwen2.5:0.5b \
  --categories numeric_reasoning,format_constrained_json \
  --per-category 4
```

Default output:
- `data/candidates/generated_candidate_test_cases.jsonl`

## Notes

- DuckDB file path: `data/reliability.duckdb`
- If schema changes, legacy tables are backed up as `*_backup_<timestamp>`
- If Ollama is unavailable or model is not installed, use `mock` provider as fallback
- Candidate trace promotions are written under `data/candidates/`
