# LLM Reliability Analytics

Local-first, evaluation-first LLM testing: create a job, run a dataset against a
mock, local Ollama model, or OpenAI-compatible server, inspect attempt-level
evidence, compare runs, and export a report.

- **Next.js** is the client UI for job creation, status tracking, evidence review,
  run comparison, and exports (`/` redirects to `/jobs`; top bar links Jobs, Compare, New job).
- **FastAPI** owns asynchronous execution, persistence, comparison endpoints, and backend exports. The client UI and
  the queue CLI call it over HTTP.
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
.venv/bin/python -m pip install -r requirements.lock
npm --prefix client-app ci
```

`requirements.lock` installs the exact tested dependency set used by CI;
`requirements.txt` keeps version ranges as the input for deliberate upgrades.

Start each process in its own terminal, initially at the repository root. The
supported stack consists of **two processes**:

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

Open [client jobs](http://127.0.0.1:3000/jobs) (or `/` which redirects to `/jobs`) and [API docs](http://127.0.0.1:8000/docs).
Navigation in the client top bar links Jobs, Compare, and New job.
Do not run multiple API workers or use reload during evaluations. The API holds
a per-database ownership lock before schema initialization and restart recovery.
Evaluation execution is asynchronous: running a job queues it immediately and returns HTTP 202;
an in-process worker thread runs jobs one at a time for DuckDB's single writer while the client polls for updates.

See the [runbook](docs/MVP_RUNBOOK.md) for environment variables, CORS,
queue processing, backup/restore, failure recovery, and isolated verification.

## First Evaluation

1. Open the client UI and create a job with a backend-listed dataset and a mock, local Ollama, or OpenAI-compatible model.
2. Keep oracle profile `default`: each dataset case supplies its oracle and configuration.
3. Create the draft, then explicitly run it (returns 202 and runs asynchronously) or queue it for processing.
4. Inspect status, attempts versus unique cases, expected/actual answers, oracle
   configuration, explanations, and latency provenance.
5. Download Markdown, sampled JSON, or the complete failed-attempt CSV. After completing runs, compare them at `/compare`.

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
| `ollama` / `local` | Native Ollama API at `127.0.0.1:11434`; the chosen model must be installed and reachable. |
| `openai_compatible` | POST `{base}/chat/completions` on any OpenAI-compatible server (vLLM, LM Studio, OpenAI, OpenRouter, Ollama `/v1`). |

For `openai_compatible`, the base URL is read from `LLM_RELIABILITY_OPENAI_BASE_URL` (default `http://127.0.0.1:11434/v1`, local Ollama), and an optional key is read from `LLM_RELIABILITY_OPENAI_API_KEY` sent as a Bearer token. Both are read only from the API server environment, never from requests or the browser; the key is not echoed in errors. Paid endpoints are opt-in by setting these variables. Model names are free text in the create form.

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

## Comparison, Queue and CLI Operations

Comparison lives in the Next.js client at `/compare` (and is linked from completed jobs):
select baseline and candidate completed jobs to view metric deltas, pass rate by
category, and per-case regressions/improvements. The backend refuses non-comparable runs (HTTP 409) —
mismatches in dataset hash/version, evaluation mode, per-case oracle configuration,
temperature, max tokens, repeat count, timeout, seed, or case coverage — and the page
explains the reasons. Provider and mode may differ only when both runs are real executions
(`ollama` vs `openai_compatible`); comparing mock against real is refused.

Execution is asynchronous: `POST /evaluation-jobs/{job_id}/run` returns HTTP 202 immediately;
a draft becomes queued and one in-process worker thread runs jobs one at a time for DuckDB's single writer.
The client polls queued and running jobs. Appending `?wait=true` keeps the blocking behavior
(used by tests and the queue CLI). `POST /evaluation-jobs/process-queue` returns 202 and schedules up
to `max_jobs` oldest queued jobs; `?wait=true` processes them synchronously. HTTP timeouts do not
affect runs. A graceful API shutdown stops the in-flight run after its current attempt (saved as `canceled`
with partial evidence) and leaves waiting jobs queued; after a hard kill, startup marks the run failed.

The queue CLI is an HTTP client, passing `wait=true` itself:

```bash
env PYTHONPATH=src LLM_RELIABILITY_API_BASE_URL=http://127.0.0.1:8000 .venv/bin/python -m llm_reliability_analytics.cli.process_queue --max-jobs 5 --poll-interval-seconds 3 --iterations 20
```

Queue processing is global, uses enqueue order, and reports per-job failures
without abandoning later eligible jobs. Each pass processes its initial queue
snapshot; claim conflicts from another processor are skipped without failure or
counting. Jobs still queued are picked up on a later poll. It is not a separate DB-owning worker.

Candidate generation and direct batch runs remain only as CLI modules
(`llm_reliability_analytics.cli.generate_candidates`, `llm_reliability_analytics.cli.run_batch`);
they are not exposed over HTTP. Standalone batch and generation scripts and notebooks are
**offline maintenance tools only**. Stop the backend and queue polling before using them against its DB
or managed files. They do not inherit the job API's full lifecycle/snapshot contract.

## Interpret Reports Carefully

Headline metrics are disaggregated:
- **Pass rate** (accuracy over all attempts)
- **pass^k** (share of unique cases where all k attempts pass)
- **pass@k** (share of unique cases with at least one passing attempt)
- **Schema-only pass rate** (pass rate on `json_schema` attempts only)
- **Latency p50 and p95**

`pass^k` and `pass@k` are N/A unless every case has the same k ≥ 2 attempts.
The legacy-v1 composite ("overall reliability score") is still computed and shown, labelled
"Legacy composite", only for comparing with older runs; it is not the main score.

Cases marked `strict_output` (as throughout the v2 benchmark) demand only the answer.
`numeric_tolerance` fails anything but a bare number, and `exact_match` fails an answer
that merely contains the expected text, both as `format_violation`: `24 - 13 = 11` or
`Portugal's capital is Lisbon.` are format failures, not wrong answers. An explicit
`allow_substring_match` still wins. Runs scored before this rule ignored
`strict_output`; their recorded oracle configuration differs, so comparisons with them
are refused rather than shown as regressions.

Comparison eligibility checks persisted settings, dataset hash, and case/attempt-keyed oracle configuration.
Unknown configuration evidence is `research_only` and excluded from comparisons.
Read `measurement_notes`, `repeated_case_count`, `schema_case_count`,
`schema_attempt_count`, and `latency_sources` with the headline metrics.
A singleton's legacy repeatability score is not measured repeatability; the legacy
schema heuristic is not a schema-only pass rate. Per-model synthetic medians no longer exist.
Missing legacy configuration evidence limits comparability even when dataset labels match.

CSV exports all stored failed attempts, with quoted fields and spreadsheet-formula
neutralization; it has no 5,000-row sample cap. JSON explicitly supplies
`failed_case_total` and `failed_cases_sample`. Exports during a run include only
evidence persisted so far. See [report semantics](docs/MVP_RUNBOOK.md#reports-and-evidence).

## Repository Map

| Path | Responsibility |
| --- | --- |
| `client-app/` | Client evaluation workflow, comparison UI, and HTTP adapters |
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
