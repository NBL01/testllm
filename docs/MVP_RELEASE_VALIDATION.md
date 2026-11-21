# MVP Release Validation

Status: **release acceptance pending**. Automated gates passed on 2026-11-21
against code commit `a7b25c0`; manual goal-by-goal acceptance, recovery rehearsal
on the final code and a release decision are still open. Nothing here approves a merge, release or deployment.

## 2026-11-21 verification run

All checks used temporary databases; `data/reliability.duckdb` kept its
modification time and size throughout. Only mock providers were exercised.

| Check | Command / method | Result |
| --- | --- | --- |
| Python regressions | `env LLM_RELIABILITY_DB_PATH=<tmp> MPLBACKEND=Agg .venv/bin/python -m pytest -q` | 232 passed |
| Client unit + infra | `npm --prefix client-app test` | 20 + 3 passed |
| Type check | `npx tsc --noEmit` in `client-app` | clean |
| Dependency audit | `npm audit --audit-level=moderate` | 0 vulnerabilities after patching (below) |
| Browser journeys | `npm --prefix client-app run test:e2e` (production build, isolated API/DB) | 22 passed on desktop and Pixel 7 Chromium; 0 server tracebacks or HTTP 500s |
| UI coexistence | Isolated API; job running while Streamlit `AppTest` rendered over HTTP | 0 exceptions; status `running` during render; Streamlit never opened a DB file; both jobs completed; mock models eligible and ranked |
| Single API owner | Second API on the same temp DB | exit 3 with the ownership error |
| Fresh clone | `git clone` of `e7bb06d`, new venv + `npm ci`, then all gates above | 232 pytest, audit 0, 20 + 3 client, 22 browser passed; 0 tracebacks |
| Backup and restore | Runbook steps on a stopped temp DB: offline `CHECKPOINT`, `cp -p`, restore to a new file, start API on it | no WAL left; original, backup and restore SHA-256 equal; 3 jobs, statuses, linked runs, summary metrics and failed-attempt CSV bytes identical after restore |
| Legacy timezone | `test_legacy_timezone_requires_explicit_conversion_and_backup` (synthetic DB) | refuses without a zone; `America/New_York` 15:00 becomes 19:00 UTC; `.bak` written |
| Startup, bash and fish | README's three Terminal commands run verbatim via `bash -c` / `fish -c`, DB path pointed at a temp file | API `/health`, client `/jobs`, Streamlit `/_stcore/health` all ready in both shells |

Defects found and fixed during the run:

- **Concurrent evidence reads returned 500** (`Unique file handle conflict`) when a
  run's last connection closed and checkpointed while the job page fetched summary,
  failed cases, traces and report. `get_connection` now retries only that error
  for up to five seconds; a barrier-based regression test fails without the fix.
- **Production build needed the network**: `next/font/google` downloaded fonts at
  build time and failed intermittently. The client now uses the CSS system stacks
  it already declared; an infra test guards against reintroducing remote fonts.
- **Audit failures**: `next` 15.5.25 (critical), `sharp` 0.35.4 and `source-map-js`
  1.2.1 (high). Patched to `next` 15.5.29, `sharp` 0.35.5 via Next, and an override
  pinning `source-map-js` 1.2.2.
- **Browser suite could not pass**: exact label locators never matched selects
  inside wrapping labels, and export checks compared against a nonexistent
  `summary.run_id`. Selects are now located by role and exports are checked
  against the job's `linked_run_id`.
- Streamlit deprecation warnings for `use_container_width` removed; the
  requirement floor is the tested Streamlit 1.54.

Runtime: Python 3.14.10, Node 26.13.1 (CI: Python 3.12, Node 22), FastAPI 0.135.0,
Uvicorn 0.41.0, DuckDB 1.4.4, Streamlit 1.54.0, pandas 2.3.3, HTTPX 0.28.1,
Pydantic 2.12.5, Next.js 15.5.29, Playwright 1.63.0. The fresh clone resolved newer
in-range Python packages (FastAPI 0.165.0, Uvicorn 0.54.0, DuckDB 1.5.6, Streamlit
1.67.0, Pydantic 2.14.4) and passed the same gates; with that Starlette, its test
client warns that `httpx` support is deprecated in favor of `httpx2`.

## Earlier operational observations (2026-09-13)

One standalone operational harness completed on 2026-09-13 with exit status 0.
It ran the current worktree versions of tracked files copied into a temporary
directory, using existing virtual-environment dependencies. Ignored operational
data and local exports were excluded. It did not read or write the user's
`data/reliability.duckdb` and used mock or `provider=none` operations only.

Local evidence artifacts, retained for this session:

- Harness: `/tmp/reliability-operations-review/verify.py`.
- Structured results: `/tmp/reliability-operational-z5iokt0n/evidence.json`.
- API log: `/tmp/reliability-operational-z5iokt0n/api.log`.
- Invocation: `.venv/bin/python /tmp/reliability-operations-review/verify.py`.

These `/tmp` paths are local evidence, not portable repository fixtures. The
initial sandboxed invocation could not bind the loopback port. The approved local
server invocation completed; its API process was terminated by the harness.

| Check | Observation | Limit |
| --- | --- | --- |
| Tracked demo inputs | Sample and regression alias completed 20 cases each; adversarial completed 6. | A tracked-file copy using current file contents, not a fresh dependency installation or clean commit checkout. |
| Single API owner | API used `--workers 1`; a second API on another port with the same temporary DB failed with the ownership error. | Cooperating API guard only; arbitrary DuckDB scripts are outside that lock. |
| Concurrent internal read | A separate process used the Streamlit `DataProvider` over HTTP and saw 4 runs and 46 results while the active job remained `running` before and after the read. | Proves concurrent adapter read; does not prove simultaneous Next.js and Streamlit browser operation. |
| Streamlit application | `AppTest` rendered `LLM Reliability Internal Admin Console` with zero exceptions or visible errors. | AppTest executes the application; no actual Streamlit browser/WebSocket session was exercised. |
| HTTP queue CLI | Output: `processed_count=1 requested_max_jobs=1 queue_total=5`; queued mock-failing job completed. | Per-attempt generation failure is distinct from an orchestration failure. Queue failure isolation remains covered by separate regression work. |
| Candidate workflow | Generated one candidate without a model provider, approved it, read its review event, promoted and exported one case under the temporary backend copy. | Confirms adapter/action availability; does not establish semantic quality of generated candidates. |
| Stopped backup and restore | Original, backup and restored copy matched SHA-256; restored DB retained 5 jobs. | Checked offline row persistence; did not launch the complete UI stack against the restored DB. |
| Legacy conversion | Populated naive timestamps without a zone were refused. `2026-09-06 15:00:00` in `America/New_York` became `2026-09-06 19:00:00+00:00`; one automatic backup retained the original naive value. | Synthetic temporary legacy DB with known timezone, not migration of operational history. |
| Outage display | After stopping the API, Streamlit AppTest displayed `FastAPI unavailable` with no uncaught exception. | Browser reconnection and retained client form state are separate checks. |

Snapshot hashes observed:

- Sample and regression alias:
  `a5a0e9b2c365919e1bb01955d8fe815e19e59a554600836dbda289a56360898b`.
- Adversarial:
  `3d4e6ac97f24cc2d5923d1b1474d6991e8de5ac4681caf9caeabdeb6610ae839`.
- Backup file:
  `d3a3f9710b6f68085a941a0a27532ccd5008697e87861cc614dd4b8c28850c5b`.

Local operational runtime: Python 3.14.6, FastAPI 0.135.0, Uvicorn 0.41.0,
DuckDB 1.4.4, Streamlit 1.54.0, pandas 2.3.3, HTTPX 0.28.1. This inventory is not
a dependency advisory review or a supported-version matrix.

## Remaining release checks

1. Manual keyboard and screen-reader smoke of the client beyond the automated
   keyboard-order check, and a real browser (not `AppTest`) Streamlit session.
2. Goal-by-goal G01-G17 evidence and reconciliation of remaining defects/limitations.
3. Optional live Ollama run, kept separate from the deterministic mock gate.
4. Release decision, including whether to pin Python dependency upper bounds now
   that a fresh install resolves newer minor versions than the recorded runtime.

Use [the runbook](MVP_RUNBOOK.md) for supported local operation while release
acceptance remains pending.
