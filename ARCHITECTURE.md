# Evaluation-First Architecture

This describes the local MVP implementation, not release acceptance.
The operational contract is in [MVP Runbook](docs/MVP_RUNBOOK.md);
remaining gates are in [Development Plan](DEVELOPMENT_PLAN.md).

## Product and Process Boundaries

The primary flow is **create evaluation job -> execute -> inspect evidence ->
compare -> export**. Candidate generation and model comparison support that flow rather than
replacing it with a recommendation-first product.

| Process | Owns | Must not do |
| --- | --- | --- |
| Next.js | Client forms, navigation (`/` redirects to `/jobs`; top bar links Jobs, Compare, New job), status, review, comparison (`/compare`), downloads | Execute models/oracles or open DuckDB |
| FastAPI, one worker | Job transitions, async queue scheduling, model calls, storage, comparison endpoints, exports | Share operational DB ownership with another process |
| Queue CLI | HTTP queue-processing and stats requests (passes `wait=true`) | Open DuckDB or execute evaluation code locally |
| Offline maintenance tools | Explicit standalone batch and candidate CLI modules (`llm_reliability_analytics.cli.generate_candidates`, `llm_reliability_analytics.cli.run_batch`) | Run against the live backend's database/files |

The API lifespan holds `api_database_owner` from
`src/llm_reliability_analytics/main.py` before migration and recovery. The POSIX
advisory lock is `<database>.api.lock`, held across individual DuckDB connections.
A second cooperating API process fails startup. It does **not** coordinate arbitrary
scripts/notebooks: offline-only maintenance remains an operator responsibility.
There is no distributed task broker, remote worker fleet, or multi-host storage mode.

No authentication, authorization, tenant isolation, or remote deployment hardening
is present. Bind all surfaces to loopback on a trusted machine. CORS is a browser
compatibility setting, not an access-control mechanism.

## Durable Evidence Model

| Entity | Meaning |
| --- | --- |
| `evaluation_jobs` | Requested configuration, state, dataset snapshot/hash, source-job linkage and execution timestamps |
| `test_runs` | Execution artifact, status, provider/model/settings and metadata |
| `test_results` | Attempt-level input/output, scoring, error and latency evidence |
| `evaluation_traces` | Review/replay evidence with original expected answer and oracle configuration |
| `test_cases` | Reusable current case inventory; not authoritative truth for historical attempts |
| `candidate_test_cases`, `candidate_review_events` | Human-curated candidate state and review history |

A new job validates its JSONL/CSV cases, rejects invalid rows and duplicate case IDs,
resolves the case limit and dataset version, then persists the normalized snapshot.
`dataset_sha256` is SHA-256 over canonical JSON of that effective snapshot.
It is not a hash of file bytes or a full environment/model-weight fingerprint.

On claim, the job is associated with its run transactionally, before execution.
Run metadata records the job configuration and frozen dataset evidence. New jobs
execute that snapshot even if their source file changes. Retry/duplicate preserve
the snapshot and hash in a new job with `source_job_id`; a legacy job without a
snapshot instead revalidates current inputs before creating one.

Original expected answers and oracle input configuration belong to stored evidence.
Replay refuses incomplete legacy traces requiring review; it does not turn a failed
model output into the expected answer. Setting `evaluation_mode=trace_replay`
on a supplied dataset is only a label, not an instruction to fetch a source run.

## Lifecycle and Queue

The job states are `draft`, `queued`, `running`, `completed`, `failed`,
and `canceled`.

1. Creating a job stores a draft; it does not run the model.
2. Execution is asynchronous: `POST /evaluation-jobs/{job_id}/run` returns HTTP 202
   immediately, marks the job as `queued` (or keeps it `queued`), and submits it to
   an in-process worker thread (`ThreadPoolExecutor(max_workers=1)`) that serializes
   executions for DuckDB's single writer. The client polls queued and running jobs.
   Passing `?wait=true` keeps the blocking behavior (used by tests and the queue CLI).
3. Queueing records `queued_at`; processing orders by enqueue time, with a stable
   job-ID tie-break, and isolates per-job failures. `POST /evaluation-jobs/process-queue`
   returns 202 and schedules up to `max_jobs` oldest queued jobs; `?wait=true`
   processes them synchronously. The queue CLI passes `wait=true` itself. A claim
   conflict from another processor is skipped without failure/counting; the initial
   queue snapshot is processed and remaining jobs are picked up on a later poll.
4. Draft/queued jobs can be canceled. Canceling a job that this API process is executing
   requests a stop: the run ends after its current attempt (an in-flight model call is not
   interrupted), the attempts already run are scored and stored, and the job becomes
   `canceled` with the reason and attempt count. While it runs, `GET /evaluation-jobs/{id}`
   and the job list report `progress_done`/`progress_total`.
5. An execution exception finalizes the run/job as failed while preserving available
   linkage and partial evidence. Failed attempts alone do not imply a failed job.
6. API startup marks interrupted running jobs/runs failed (`recover_interrupted_jobs`).
   It does not automatically resume them; retry creates a new job. Waiting jobs stay queued.

Run and queue-processing HTTP requests are asynchronous by default, returning 202
immediately while one in-process worker thread runs jobs one at a time for DuckDB's
single writer. One API worker means one process. Atomic job claims prevent duplicate
execution of the same job; they do not create a distributed task broker. HTTP timeouts do not
affect runs.

## Python Evaluation Pipeline

1. `ingestion/loader.py` parses validated case inputs. The job layer applies stricter
   creation checks and freezes the effective selection.
2. `workflow/evaluation_jobs.py` manages product state, claims, recovery and read views.
3. `workflow/service.py` and `runner/test_runner.py` execute the prepared cases with
   a provider selected by `runner/client_factory.py`. Supported providers are `mock`,
   `ollama` / `local` (native Ollama API at `127.0.0.1:11434`), and `openai_compatible`
   (POST `{base}/chat/completions` on any OpenAI-compatible server such as vLLM, LM Studio,
   OpenAI, OpenRouter, or Ollama `/v1`).
4. `oracles/engine.py` scores exact, regex, keyword, numeric-tolerance and JSON-schema
   checks using dataset-defined settings.
5. Storage persists run/result/trace evidence; Python analytics and reporting derive
   review views without implementing scoring in JavaScript.

The only job oracle profile is `default`: it means dataset-defined scoring, not a
separate dynamic scoring override. Exact matching retains documented lenient legacy
defaults unless the case config requests stricter behavior.

Mock job IDs have distinct behavior: baseline deterministic rules/hash fallback,
noisy seeded perturbations, and failing simulated generation errors. Reproducibility
depends on the seed and ordered prompts/attempts. New job execution records and
passes use seed `42` explicitly; older/direct batch records may lack that field.
Mock latency must not be compared to real-provider performance as though measured
on the same basis.

For `openai_compatible`, the base URL is configured via `LLM_RELIABILITY_OPENAI_BASE_URL`
(default `http://127.0.0.1:11434/v1`), and an optional key is read from
`LLM_RELIABILITY_OPENAI_API_KEY` sent as a Bearer token. Both are read only from the API
server environment, never from requests or the browser; the key is not echoed in errors.
Paid endpoints are opt-in by setting these variables. Model names are free text in the create form.
and via `openai_compatible` through the async path.

## API Surfaces

The live OpenAPI schema at `/docs` is the exact route/parameter reference.

| Surface | Main routes |
| --- | --- |
| Discovery | `/health`, `/models`, `/evaluation-jobs/options` |
| Product lifecycle | `/evaluation-jobs`, `/{job_id}` and run/queue/cancel/retry/duplicate actions |
| Queue operations | `/evaluation-jobs/process-queue`, `/evaluation-jobs/queue/stats` |
| Job evidence | Summary, failed-cases, traces, report, client-report under `/evaluation-jobs/{job_id}` |
| Complete CSV | `/evaluation-jobs/{job_id}/failed-cases.csv` |
| Comparison | POST `/internal/metrics/eligibility`, POST `/internal/metrics/compare` |

Direct batch runs and candidate generation are not exposed over HTTP; they remain available
only as offline CLI modules (`llm_reliability_analytics.cli.run_batch`, `llm_reliability_analytics.cli.generate_candidates`).

## Metrics, Comparisons and Exports

Headline metrics are disaggregated:
- **Pass rate** (accuracy over all attempts)
- **pass^k** (share of unique cases where all k attempts pass)
- **pass@k** (share of unique cases with at least one passing attempt)
- **Schema-only pass rate** (pass rate on `json_schema` attempts only)
- **Latency p50 and p95**

`pass^k` and `pass@k` are N/A unless every case has the same k ≥ 2 attempts.
The legacy-v1 composite (`overall_reliability_score`) preserves historical numeric heuristic
behavior and is still computed and shown, labelled "Legacy composite", only for comparing
with older runs; it is not the main score. Reports distinguish attempt counts from unique
cases and expose repeat/schema eligibility and latency sources. Singleton repeatability and
all-attempt schema compliance must not be interpreted as empirical repeatability or schema-only
success rates.

Comparison lives in the Next.js client at `/compare` (also linked from completed jobs):
select baseline and candidate completed jobs to view metric deltas, pass rate by
category, and per-case regressions/improvements. Internal metrics run behind FastAPI,
reusing persisted results through `fetch_results_for_run` and shared analytics.
The backend refuses non-comparable runs with HTTP 409 (mismatches in dataset hash/version,
evaluation mode, per-case oracle configuration, temperature, max tokens, repeat count,
timeout, seed, or case coverage), and the page explains the reasons. Provider and mode
may differ only when both runs are real executions (`ollama` vs `openai_compatible`);
comparing mock against real is refused. Unknown configuration evidence is marked
`research_only` and excluded from comparisons. Per-model synthetic medians no longer exist.

Markdown includes run/job context and measurement caveats. JSON explicitly identifies
its failed-case sample and total. CSV reads every persisted failed result, without
a UI page limit or dependence on successful trace capture. All fields are quoted;
formula-like text is apostrophe-prefixed, with Unicode and CR/LF handled by the CSV
serializer. Exporting a running/failed run returns only the evidence persisted so far.
CSV is built in memory even though result fetching is batched.

## Storage and Recovery Contract

Connections use UTC and new timestamp columns use `TIMESTAMPTZ`. Each request opens
its own connection; a connect that races the last connection's close and checkpoint
is retried for up to five seconds instead of failing the request. Populated legacy
naive timestamps require explicit `LLM_RELIABILITY_LEGACY_TIMEZONE` identifying the
original writer timezone. Conversion checkpoints and creates a timestamped file
`.bak`, then converts transactionally. Missing columns use additive migrations;
there is no automatic `*_backup_<timestamp>` table scheme.

Back up/restore only with the API, polling and maintenance writers stopped.
Preserve datasets and candidate exports separately from the DB. Do not delete a
live ownership-lock file or swap the DB beneath a running process.
