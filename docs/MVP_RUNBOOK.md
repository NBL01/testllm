# MVP Runbook

This is the supported trusted-local operating procedure. Release acceptance is
tracked separately in [release validation](MVP_RELEASE_VALIDATION.md) and the
[development plan](../DEVELOPMENT_PLAN.md).

## Supported topology

Run one FastAPI process with one worker per database. The Next.js client and the
queue CLI call that process over HTTP. Bind both servers to `127.0.0.1`.
There is no authentication; CORS does not provide access control.

The POSIX advisory ownership lock is acquired before schema initialization and
startup recovery. A second cooperating API fails with `another API owns this
database`. The `.duckdb.api.lock` file may remain after shutdown; its existence
alone does not mean an owner is running. Do not delete it while processes are
active. The lock does not protect against standalone scripts opening DuckDB.

Do not use multiple API workers or reload while evaluations are active. Stop the
API and queue polling before direct database maintenance, notebooks, batch/replay
scripts, or manipulation of backend-managed dataset and candidate files.

## Setup and startup

Run these commands from the repository root. They use explicit executables and
`env`, so no shell activation is required in bash or fish. Choose the Python
runtime for the intended environment; current CI targets Python 3.12, while the
recorded local operational check used Python 3.14.6. This is not a claim that all
supported dependency combinations were tested. Client runtime requirements are in
`client-app/package.json` and its lockfile.

```bash
python3 -m venv .venv
.venv/bin/python -m pip install -r requirements.lock
npm --prefix client-app ci
```

`requirements.lock` installs the exact tested dependency set used by CI;
`requirements.txt` keeps version ranges as the input for deliberate upgrades.

Start each server in a separate terminal at the repository root. The supported
stack consists of **two processes**:

```bash
env LLM_RELIABILITY_DB_PATH="$PWD/data/reliability.duckdb" .venv/bin/python -m uvicorn llm_reliability_analytics.main:app --app-dir src --host 127.0.0.1 --port 8000 --workers 1
```

```bash
env NEXT_PUBLIC_API_BASE_URL=http://127.0.0.1:8000 npm --prefix client-app run dev -- --hostname 127.0.0.1
```

Open the [client](http://127.0.0.1:3000/jobs) (or `/` which redirects to `/jobs`) and
[API documentation](http://127.0.0.1:8000/docs).
Navigation in the client top bar links Jobs, Compare, and New job.
`GET /health` confirms HTTP availability.

## Environment and CORS

| Variable | Consumer | Default / meaning |
| --- | --- | --- |
| `LLM_RELIABILITY_DB_PATH` | API and offline Python tools | Repository `data/reliability.duckdb`; set an absolute path explicitly. |
| `LLM_RELIABILITY_LEGACY_TIMEZONE` | Schema migration | No default for populated legacy timestamps; original writer's IANA timezone is required. |
| `LLM_RELIABILITY_CORS_ORIGINS` | API | Comma-separated origins; defaults to `http://localhost:3000,http://127.0.0.1:3000`. |
| `LLM_RELIABILITY_OPENAI_BASE_URL` | API | Base URL for `openai_compatible` provider; defaults to `http://127.0.0.1:11434/v1` (local Ollama). |
| `LLM_RELIABILITY_OPENAI_API_KEY` | API | Optional Bearer token for `openai_compatible` provider; default empty. Read only by the backend server, never from requests or the browser; not echoed in errors. Paid endpoints are opt-in. |
| `NEXT_PUBLIC_API_BASE_URL` | Next.js browser client | `http://localhost:8000`; configure before starting development or building production assets. |
| `LLM_RELIABILITY_API_BASE_URL` | Queue CLI only | `http://127.0.0.1:8000`. |
| `LLM_RELIABILITY_API_ACTION_TIMEOUT_SECONDS` | Queue CLI only | `3600`; transport timeout for synchronous queue processing (`?wait=true`). |

An origin includes scheme, host and port. If the client runs on a different port,
set its exact origin in `LLM_RELIABILITY_CORS_ORIGINS` before starting FastAPI.
`localhost` and `127.0.0.1` are different browser origins. Backend Python processes
read their process environment; these commands do not assume `.env` loading.

## Jobs and queue processing

Create a draft using a backend-listed dataset and model (`mock-baseline`, local Ollama,
or an OpenAI-compatible endpoint), then explicitly run or queue it. The three demo presets
use two tracked files: `data/raw/sample_test_cases.jsonl` and
`data/adversarial/mvp_adversarial_v1.jsonl`. Regression v1 is a labeled alias of the
sample data. Dataset paths refer to the backend filesystem.

Supported providers:
- `mock-baseline`: Deterministic rule/hash-based answers; not guaranteed correct.
- `mock-noisy`: Seeded answer perturbations; some normalize to the same scored answer.
- `mock-failing`: Simulated per-attempt generation errors, useful for evidence/export checks.
- `ollama` / `local`: Native Ollama API at `127.0.0.1:11434`; the chosen model must be installed and reachable.
- `openai_compatible`: POST `{base}/chat/completions` on any OpenAI-compatible server (vLLM, LM Studio, OpenAI, OpenRouter, Ollama `/v1`). Base URL from `LLM_RELIABILITY_OPENAI_BASE_URL` (default `http://127.0.0.1:11434/v1`), optional key from `LLM_RELIABILITY_OPENAI_API_KEY` sent as a Bearer token. Both read only from the API server environment, never from requests or the browser; the key is not echoed in errors. Paid endpoints are opt-in. Model names are free text in the create form. Live check on 2026-11-21: `qwen2.5:0.5b` on local Ollama completed 10/10 attempts both natively and via `openai_compatible` through the async path.

Job creation saves the effective normalized case snapshot and SHA-256. The hash
describes the snapshot after limit and version resolution, not source-file bytes.
Retry and duplicate preserve an existing snapshot and hash in the new linked draft.
Legacy jobs without a snapshot validate current source inputs before creating a new
snapshot, so they cannot promise frozen retry until that succeeds.

Execution is asynchronous: `POST /evaluation-jobs/{job_id}/run` returns HTTP 202 immediately;
a draft becomes queued and one in-process worker thread runs jobs one at a time for DuckDB's
single writer. The client polls queued and running jobs. Appending `?wait=true` keeps the
blocking behavior (used by tests and the queue CLI). `POST /evaluation-jobs/process-queue`
returns 202 and schedules up to `max_jobs` oldest queued jobs; `?wait=true` processes them
synchronously. Requests return 202 immediately, so HTTP timeouts do not affect runs.

Run this HTTP-only queue client alongside the API:

```bash
env PYTHONPATH=src LLM_RELIABILITY_API_BASE_URL=http://127.0.0.1:8000 .venv/bin/python -m llm_reliability_analytics.cli.process_queue --max-jobs 5 --poll-interval-seconds 3 --iterations 20
```

The queue CLI command is unchanged and passes `wait=true` itself. For one processing pass,
omit the polling options. `--max-jobs` is bounded at 500; `--api-base-url` and
`--request-timeout-seconds` override the corresponding defaults. This processes the global
queue in enqueue order. Per-job failures are recorded without abandoning later eligible jobs.
Each pass processes its initial queue snapshot; claim conflicts from another processor are
skipped without failure or counting and remain eligible for a later poll. Inspect the queue
and individual job state for failure details. The CLI summary is not a per-job success report.

Candidate generation and direct batch runs remain only as CLI modules
(`llm_reliability_analytics.cli.generate_candidates`, `llm_reliability_analytics.cli.run_batch`);
do not document their flags. Standalone batch and generation scripts and notebooks are
offline maintenance tools only: stop the backend and queue polling before using them against its DB
or managed files.

Draft and queued jobs can be canceled outright. A running job shows live progress
(attempts done of total) and a **Stop Run** action: the run stops after its current
attempt, keeps and scores the attempts already made, and ends `canceled` with the reason.
Partial runs are not comparable and report pass^k/pass@k as N/A. A job marked running by
another process cannot be stopped here (409). Completion describes finished execution, so
a completed job may contain incorrect answers or simulated per-attempt generation failures.

## Shutdown and interruption recovery

1. Stop queue polling and avoid new UI mutations.
2. Stop FastAPI gracefully (Ctrl+C once) and wait for it to exit. A running evaluation
   stops after its current attempt and is saved as `canceled` with its partial
   evidence; jobs waiting in the worker stay `queued` for the next start. Stop the
   Next.js client before maintenance so no one mistakes it for an available service.
3. If the backend was killed during execution, restart one API with the same DB path.
   Startup recovery marks persisted running jobs and runs failed, preserving linked
   artifacts and any evidence already written. Waiting jobs remain queued.
4. Review the failed job and partial evidence, then create a new retry. Do not edit
   status columns manually to claim success or rerun the original job in place.

If startup reports an ownership conflict, find and stop the existing owner before
continuing. If it requests a legacy timezone, follow the next procedure. An HTTP
outage does not itself prove a job failed; inspect state after reconnection.

## Backup and restore

Perform backups with the API and every direct DB process stopped. Use unique paths
and preserve the original until restoration is checked. The examples below contain
placeholder paths; replace them deliberately before running.

1. After a clean shutdown, checkpoint the selected DB offline so the database file
   contains its committed state. If a previous crash left a WAL, preserve the DB and
   WAL together before attempting recovery; do not delete the WAL.

   ```bash
   .venv/bin/python -c 'import duckdb; c=duckdb.connect("/absolute/path/evaluation.duckdb"); c.execute("CHECKPOINT"); c.close()'
   ```

2. Copy the stopped DB to a unique backup path. Back up custom datasets, promoted
   datasets and candidate files separately if those artifacts are needed; a DuckDB
   backup does not include files under `data/`.

   ```bash
   cp -p /absolute/path/evaluation.duckdb /absolute/path/backups/evaluation-YYYYMMDD-HHMMSS.duckdb
   ```

3. Restore to a new file, then start the API against that file. This preserves the
   existing database while checking restored job counts, linked runs and reports.

   ```bash
   cp -p /absolute/path/backups/evaluation-YYYYMMDD-HHMMSS.duckdb /absolute/path/restored.duckdb
   env LLM_RELIABILITY_DB_PATH=/absolute/path/restored.duckdb .venv/bin/python -m uvicorn llm_reliability_analytics.main:app --app-dir src --host 127.0.0.1 --port 8000 --workers 1
   ```

The ownership lock file is not evaluation data and does not need to be restored.
Keep backups outside paths that routine cleanup or dataset export may overwrite.

## Legacy timezone migration

Naive legacy `TIMESTAMP` values do not identify their original timezone. Populated
legacy tables therefore fail startup without an explicit original-writer zone.
Do not infer that zone from the current machine's location. If it is unknown, retain
the original and resolve its provenance before conversion.

1. Stop every process accessing the DB. Make a stopped-file backup using the
   preceding procedure, then make a separate working copy for migration.
2. Initialize that copy with the known original timezone. The example zone below
   is illustrative, not a recommendation for existing records.

   ```bash
   env PYTHONPATH=src LLM_RELIABILITY_DB_PATH=/absolute/path/migration-copy.duckdb LLM_RELIABILITY_LEGACY_TIMEZONE=America/New_York .venv/bin/python -c 'from llm_reliability_analytics.storage.db import initialize_schema; initialize_schema()'
   ```

3. Check representative timestamps and record counts against known events. The
   migration changes naive timestamps into timezone-aware values, with database
   connections using UTC. It creates an additional timestamped `.bak` beside a
   populated legacy DB before conversion; retain the independent backup as well.
4. Start one API against the verified copy without the migration variable. Startup
   may also reconcile interrupted execution state. Switch the configured DB path
   only after checking expected jobs and evidence through the API.

The migration discovers naive timestamp columns across `main` tables. Confirm the
selected zone is appropriate for the legacy data as a whole; mixed historical
writer timezones require separate recovery work. A timezone setting cannot recover
information that was never recorded.

## Reports and evidence

Inspect expected and actual answers, oracle configuration, attempt identity, score,
explanation, and latency source. Use oracle profile `default`, which applies the
dataset's per-case oracle rather than a separate user-configured scoring policy.

- Markdown adds job configuration and dataset context to the run report.
- JSON identifies `failed_case_total` separately from `failed_cases_sample`.
- `GET /evaluation-jobs/{job_id}/failed-cases.csv` exports all stored failed
  attempts, with quoted fields and spreadsheet-formula neutralization. It is not
  capped at the JSON sample size or 5,000 rows.
- During execution, exports can contain only the evidence persisted so far.

Headline metrics are disaggregated:
- **Pass rate** (accuracy over all attempts)
- **pass^k** (share of unique cases where all k attempts pass)
- **pass@k** (share of unique cases with at least one passing attempt)
- **Schema-only pass rate** (pass rate on `json_schema` attempts only)
- **Latency p50 and p95**

`pass^k` and `pass@k` are N/A unless every case has the same k ≥ 2 attempts.
The legacy-v1 composite (`overall_reliability_score`) preserves historical score
semantics and is still computed and shown, labelled "Legacy composite", only for
comparing with older runs; it is not the main score.

Comparison lives in the Next.js client at `/compare` (also linked from completed jobs):
select baseline and candidate completed jobs to view metric deltas, pass rate by
category, and per-case regressions/improvements. Internal metrics run behind FastAPI,
reusing persisted results through `fetch_results_for_run` and shared analytics.
The backend refuses non-comparable runs with HTTP 409 (mismatches in dataset hash/version,
evaluation mode, per-case oracle configuration, temperature, max tokens, repeat count,
timeout, seed, or case coverage), and the page explains the reasons. Provider and mode
may differ only when both runs are real executions (`ollama` vs `openai_compatible`);
comparing mock against real is refused. Unknown configuration evidence is marked
`research_only` and excluded from comparisons. Read measurement notes and coverage counts
alongside headline values: singleton repeatability is not measured repeated behavior, the
historical schema heuristic is not a schema-only pass rate, and mock latency is not a real
provider benchmark. Per-model synthetic medians no longer exist.

## Isolated verification

Verification is a separate step; the latest recorded run is in
[the validation document](MVP_RELEASE_VALIDATION.md). Create a unique temporary
directory and set `LLM_RELIABILITY_DB_PATH` explicitly before invoking any test or
API process. Never point verification at the operational database.

```bash
env LLM_RELIABILITY_DB_PATH=/tmp/reliability-check/test.duckdb MPLBACKEND=Agg .venv/bin/python -m pytest -q
npm --prefix client-app audit --audit-level=moderate
npm --prefix client-app test
npm --prefix client-app run test:e2e
```

The browser suite builds a clean production copy of the client and starts its own
Next.js and FastAPI on ports 13000 and 18000 with a fresh temporary database, so
it never reads `client-app/.env.local` or the operational DB.

Candidate generation and direct batch runs are CLI modules
(`llm_reliability_analytics.cli.generate_candidates`, `llm_reliability_analytics.cli.run_batch`);
any filesystem artifacts they create are relative to their configured paths.
A temporary DB alone does not isolate external filesystem effects.

Run the Python regression suite, client tests/build and API-backed browser checks
from the development plan. Exercise bash and fish startup, client UI and queue CLI
execution, backup/restore and migration only on temporary copies.
Record commands, versions, results and remaining limits in the validation document.
Live Ollama is optional and separate from deterministic mock checks; do not pull
models or invoke paid providers as part of the default release gate.
