# Development Plan: Evaluation-First MVP

Status reviewed against source: 2026-09-20. This is a delivery and acceptance plan,
not a declaration that the MVP is complete. The earlier proposal to introduce jobs
and split the UIs has been implemented; release verification remains a separate gate.

## Product Direction

The primary user journey is job creation, explicit execution/queueing, status,
attempt-level evidence review, and export. Next.js owns that client workflow.
Streamlit remains the internal analytics, experiment and candidate-curation console.
FastAPI is the operational boundary and sole DB-owning process in the supported setup.

Keep model execution, oracle semantics, persisted state transitions and authoritative
reports in Python. Keep JavaScript focused on workflow UX and HTTP contracts.
Preserve useful admin operations without bypassing FastAPI. Pure read-only Python
display analytics in Streamlit are acceptable.

No auth or public deployment is in scope: loopback and trusted-local use are explicit
constraints, not security features awaiting a hidden default.

## Implemented Foundation

These are source-level capabilities, not blanket acceptance claims.

| Area | Current implementation |
| --- | --- |
| Job foundation | Draft/queue/run/cancel/retry/duplicate APIs; one primary linked execution artifact |
| Reproducibility | Validated effective dataset snapshots, canonical SHA-256, persisted job/run configuration; new job executions record/pass seed `42`, while older/direct batch records may lack it |
| Execution integrity | Conditional claims, early run linkage, failure finalization, startup interruption recovery |
| Queue | Enqueue timestamps, stable ordering, per-job outcomes, contention skips without failure/counting, HTTP-only CLI |
| Catalog and validation | Backend-listed datasets/mock modes; only dataset-defined default oracle profile |
| Evidence | Original expected/actual answer and oracle configuration; replay review requirement for incomplete legacy data |
| Metrics | FastAPI-owned metrics reusing persisted results/analytics; eligibility checks settings, dataset hash, and case/attempt oracle configuration; unknown configuration is `research_only`; per-model synthetic medians disclose tie-as-pass behavior |
| Exports | Markdown context, labeled JSON samples, full quoted/formula-neutralized failed-attempt CSV |
| Internal boundary | Streamlit HTTP adapters, backend candidate/export actions, explicit outages and comparison guards |
| Ownership and migration | Single-API advisory lock before recovery; UTC timestamps and explicit legacy timezone/file backup |

The supported operations are described in [MVP Runbook](docs/MVP_RUNBOOK.md);
[Architecture](ARCHITECTURE.md) records boundaries and limitations.
The [implementation review](docs/MVP_IMPLEMENTATION_REVIEW.md) retains original
findings and B1-B7 acceptance criteria; historical finding text is not current behavior.

## Remaining Release Gate

B7 validation is in progress. Do not infer completion from a successful mock happy
path or from documentation updates. The 2026-11-21 run in
[release validation](docs/MVP_RELEASE_VALIDATION.md) records evidence for items 1-4
and the startup part of item 5; fresh-clone fixtures, backup/restore and timezone
recovery on the final code, goal-by-goal evidence (item 6) and reconciliation
(item 7) remain open.

1. Run the full Python regression suite with an explicit temporary DB and isolated
   export paths, including claims/cancel races, failure injection, startup recovery,
   timestamp migration, frozen-input retry, trace replay and complete CSV behavior.
2. Run client unit/integration checks and production build using the current checked-in
   package manifest/lockfile. Record runtime inventory and dependency advisories;
   do not publish an unverified Next.js version or declare audit findings resolved.
3. Exercise a real API-backed client browser journey: create, run/queue, inspect
   failure evidence, export and retry. Check delayed/stale responses, dismissed
   cancellation, offline/reconnected API, missing models and structured errors.
4. Demonstrate simultaneous client job execution and Streamlit analytics against one
   isolated DB, with the API ownership guard enabled and queue processing over HTTP.
5. Validate fresh-checkout fixtures, bash/fish startup without activation, trusted-local
   binding, backup/restore, and legacy timezone recovery on copies only.
6. Record desktop/mobile/keyboard smoke checks and explicit evidence for each MVP goal.
   Separate optional live Ollama checks from deterministic mock CI.
7. Reconcile remaining findings and approved limitations before a release decision.
   No commit, merge or release is implied by this plan.

## Acceptance Questions

| Question | Required evidence |
| --- | --- |
| Does a job execute exactly its visible input? | Snapshot/hash inspection; source-file edit does not change an existing job; retry preserves its snapshot |
| Are state and evidence coherent on failure? | Injected failures and restart produce terminal status, linked artifacts and inspectable partial evidence |
| Can both UIs coexist safely? | Separate UI processes use HTTP while one API owns an isolated DuckDB; second API fails before recovery |
| Can reviewers explain results? | Expected/actual, effective oracle/config, attempt identity, score and explanation visible through the client |
| Are reports honest and complete? | Eligibility/provenance caveats; total versus sample labels; CSV beyond 5,000 rows with safe serialization |
| Can operators recover safely? | Stopped-copy backup/restore and explicit-zone migration rehearsed without touching operational data |
| Are comparisons defensible? | Known configuration/coverage mismatches rejected; missing legacy evidence disclosed; no synthetic-median recommendation claim |

## Known Limits to Carry Forward

- Run requests are synchronous; the queue is in-process API orchestration, not a
  distributed worker platform. Transport timeout does not cancel a job.
- The POSIX API lock protects cooperating API processes, not arbitrary direct DB
  scripts. Offline maintenance must be operationally separated.
- Direct admin batch runs and older records may not have full frozen job metadata.
  Internal comparison adapters do not prove equality of every execution parameter.
- Dashboard snapshots load full tables, and CSV assembles output in memory. Scaling
  requires deliberate pagination/streaming work, not an untested deployment claim.
- Legacy heuristic scores preserve earlier numeric semantics. Eligibility warnings
  do not make them calibrated confidence estimates or model recommendations.
- Backend-visible dataset paths, candidate exports and unauthenticated actions are
  intended only for trusted local operators.
- Older V2 documents describe historical ambitions; their timelines and numerical
  success targets are not evidence of delivered or accepted functionality.

## Post-MVP Work

After the evaluation-first release gate, prioritize richer provider integrations,
explicit versioned oracle profiles, stronger comparison/configuration provenance,
and scalable reads/exports according to measured demand. Build recommendations
only on validated evaluation evidence.

Auth, tenant isolation, remote deployment, asynchronous worker architecture and
distributed infrastructure require separate designs. Candidate generation already
exists as an internal support workflow; making it the primary product is not the
current plan.
