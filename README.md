# LLM Reliability Analytics

Local-first, evaluation-first LLM testing: create a job, run a dataset against a
mock or local Ollama model, inspect attempt-level evidence, and export a report.

- **Next.js** is the client-facing job creation, status, and review surface.
- **Streamlit** is the internal analytics, comparison, and candidate-curation console.
- **FastAPI** owns execution, persistence, and backend exports. Both UIs and the
  queue CLI call it over HTTP.
- **DuckDB** stores jobs, frozen dataset inputs, runs, results, traces, and review history.

There is **no authentication or authorization**. Run on loopback for trusted local
users only. This is not a public or multi-tenant deployment. The repaired foundation
is not a claim that the MVP release gate has passed.

## Start Locally

Run from the repository root on a POSIX system. Python 3.12 is the current CI
target; the latest local verification used Python 3.14.10. Use the Node/npm
toolchain required by the checked-in client package and lockfile. Dependency
upgrades and release validation are tracked separately.

These commands work in **bash and fish**, without activating the virtual environment:

```bash
python3 -m venv .venv
.venv/bin/python -m pip install -r requirements.txt
npm --prefix client-app ci
```

Start each process in its own terminal, initially at the repository root.

**Terminal 1: one FastAPI worker**

```bash
env LLM_RELIABILITY_DB_PATH="$PWD/data/reliability.duckdb" .venv/bin/python -m uvicorn llm_reliability_analytics.main:app --app-dir src --host 127.0.0.1 --port 8000 --workers 1
```

If an existing DB requires a legacy timezone, stop here and follow the
[migration procedure](docs/MVP_RUNBOOK.md#legacy-timezone-migration). Do not guess it.

**Terminal 2: client UI**

```bash
env NEXT_PUBLIC_API_BASE_URL=http://127.0.0.1:8000 npm --prefix client-app run dev -- --hostname 127.0.0.1
```

**Terminal 3: internal admin UI**

```bash
env LLM_RELIABILITY_API_BASE_URL=http://127.0.0.1:8000 .venv/bin/python -m streamlit run frontend/streamlit_app.py --server.address 127.0.0.1 --server.port 8501
```

Open [client jobs](http://127.0.0.1:3000/jobs),
[admin](http://127.0.0.1:8501), and [API docs](http://127.0.0.1:8000/docs).
Do not run multiple API workers or use reload during evaluations. The API holds
a per-database ownership lock before schema initialization and restart recovery.

See the [runbook](docs/MVP_RUNBOOK.md) for environment variables, CORS,
queue processing, backup/restore, failure recovery, and isolated verification.

## First Evaluation

1. Open the client UI and create a job with a backend-listed dataset and `mock-baseline`.
2. Keep oracle profile `default`: each dataset case supplies its oracle and configuration.
3. Create the draft, then explicitly run it or queue it for processing.
4. Inspect status, attempts versus unique cases, expected/actual answers, oracle
   configuration, explanations, and latency provenance.
5. Download Markdown, sampled JSON, or the complete failed-attempt CSV.

Job creation validates and freezes the effective case inputs and records
`dataset_sha256`. It hashes the normalized case snapshot after limits/version
resolution, not the original file bytes. Later file edits do not change that job.
Retry and duplicate preserve a saved snapshot and hash; legacy jobs without one
are revalidated against current source inputs before a new snapshot is created.

## Providers and Datasets

The API catalog is authoritative; do not maintain separate hard-coded presets.

| Option | Meaning |
| --- | --- |
| `mock-baseline` | Deterministic rule/hash-based answers; not guaranteed correct. |
| `mock-noisy` | Seeded answer perturbations; some normalize to the same scored answer. |
| `mock-failing` | Simulated per-attempt generation errors, useful for evidence/export checks. |
| `ollama` / `local` | Local Ollama execution; the chosen model must be installed and reachable. |

Mock outputs are reproducible for the same seed and ordered inputs; mock latency is
not a real model/network benchmark. Failed attempts can still belong to a
`completed` job: completion describes execution, not accuracy.

The catalog includes the sample dataset, an explicitly labeled regression alias of
that sample, and the tracked `data/adversarial/mvp_adversarial_v1.jsonl` fixture.
Custom JSONL/CSV paths refer to the **backend filesystem**, not the browser.
Unknown mock IDs and unsupported oracle profiles are rejected by job creation.

For optional Ollama use, start the local service, install a model available to your
machine, and verify it with `ollama list`. `GET /models` reports discovery status.
There is no automatic switch to mock when a real provider fails.

## Admin and Queue Operations

Streamlit preserves run analytics, model comparisons, result inspection, candidate
generation/review, promotion, and trace marking. Data and actions use FastAPI;
pure Python display analytics remain local. Candidate files are exported on the
backend, not written by the Streamlit app process. Unavailable API access is an
error, not substitute analytics.

The queue CLI is an HTTP client, safe alongside both UIs:

```bash
env PYTHONPATH=src LLM_RELIABILITY_API_BASE_URL=http://127.0.0.1:8000 .venv/bin/python -m llm_reliability_analytics.cli.process_queue --max-jobs 5 --poll-interval-seconds 3 --iterations 20
```

Queue processing is global, uses enqueue order, and reports per-job failures
without abandoning later eligible jobs. Each pass processes its initial queue
snapshot; claim conflicts from another processor are skipped without failure or
counting. Jobs still queued are picked up on a later poll. It is not a separate DB-owning worker.
An HTTP timeout does not cancel backend execution; refresh job state before retrying.

Standalone batch/replay/generation scripts and notebooks are **offline maintenance
tools only**. Stop the backend and queue polling before using them against its DB
or managed files. They do not inherit the job API's full lifecycle/snapshot contract.

## Interpret Reports Carefully

`metric_version=legacy-v1` preserves the historical composite formula. Internal
metrics are computed behind FastAPI from persisted results and backend analytics;
Streamlit consumes them over HTTP. Comparison eligibility checks persisted
settings, dataset hash, and case/attempt-keyed oracle configuration. Unknown
configuration evidence is `research_only` and excluded from comparisons.
Read `measurement_notes`, `repeated_case_count`, `schema_case_count`,
`schema_attempt_count`, and `latency_sources` with the headline score.
A singleton's legacy repeatability score is not measured repeatability; the legacy
schema heuristic is not a schema-only pass rate. Per-model median summaries are
synthetic, ties count as passes and are disclosed, and they are not deployment
recommendations. Missing legacy configuration evidence limits comparability even
when dataset labels match.

CSV exports all stored failed attempts, with quoted fields and spreadsheet-formula
neutralization; it has no 5,000-row sample cap. JSON explicitly supplies
`failed_case_total` and `failed_cases_sample`. Exports during a run include only
evidence persisted so far. See [report semantics](docs/MVP_RUNBOOK.md#reports-and-evidence).

## Repository Map

| Path | Responsibility |
| --- | --- |
| `client-app/` | Client evaluation workflow and HTTP adapters |
| `frontend/` | Streamlit internal console and HTTP adapters |
| `src/llm_reliability_analytics/api/` | Product and internal FastAPI routes |
| `src/llm_reliability_analytics/workflow/` | Job state machine and evaluation orchestration |
| `src/llm_reliability_analytics/storage/` | DuckDB persistence and migrations |
| `src/llm_reliability_analytics/runner/`, `oracles/` | Provider calls and correctness checks |
| `src/llm_reliability_analytics/analytics/`, `reporting/` | Python metrics and exports |
| `tests/` | Python regression coverage; use isolated databases |
| `data/` | Fixtures and local operational data |

[Architecture](ARCHITECTURE.md) describes the current boundaries.
[Development plan](DEVELOPMENT_PLAN.md) separates delivered foundations from
remaining acceptance work. Older [V2 scope](docs/PRODUCT_SCOPE_V2.md) and
[V2 roadmap](docs/ROADMAP_V2.md) are historical planning context, not the current
startup or release checklist.
