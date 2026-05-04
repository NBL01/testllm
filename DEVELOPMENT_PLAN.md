# Development Plan: Client-Facing MVP for LLM Reliability Analytics

## 1. Current State

The project currently operates as a local-first Python evaluation platform with:

- `FastAPI` endpoints for loading test cases, running batches, generating candidates, and reading reports
- `Streamlit` as the main user interface for analytics, run launching, candidate review, and result inspection
- `DuckDB` as the primary storage layer
- Python services for:
  - ingestion
  - batch execution
  - oracle scoring
  - reliability metrics
  - trace capture
  - candidate generation and promotion

The system already has a strong internal analytics foundation, but the current product boundary is still shaped around internal tooling rather than a client-facing workflow.

Today, the main execution concepts are:

- `test_run`: one execution of a dataset against a selected model/provider configuration
- `test_results`: per-test scored outputs for a run
- `evaluation_traces`: detailed stored traces used for failure analysis and replay

The current frontend and backend are also still coupled around demo-oriented flows:

- the Streamlit app is both an admin board and the primary workflow surface
- the API exposes execution actions, but not yet a first-class product-level job model
- provider/model selection is still narrowly focused on `mock` and local `ollama`

## 2. Architecture Decision

The project will move to a split-surface architecture.

### Chosen Direction

- `FastAPI` becomes the only backend/product API boundary
- `Next.js` becomes the client-facing application
- `Streamlit` remains the internal admin and analytics dashboard
- Python services remain responsible for:
  - evaluation execution
  - oracle scoring
  - metrics
  - traces
  - storage
  - reporting

### Why This Direction

This separation keeps the product UX clean without discarding the existing internal analytics value.

- `Next.js` is better suited for a focused client workflow
- `Streamlit` remains useful for research, debugging, and showcase analytics
- `FastAPI` stays as the single source of truth for business logic
- evaluation logic is not duplicated in JavaScript

### Product Boundary Rule

`Next.js` must never reimplement:

- evaluation orchestration
- oracle behavior
- scoring logic
- trace generation
- model comparison logic

It should only call `FastAPI` endpoints and render workflow-specific UX.

## 3. Data Model

The key domain distinction for the MVP is:

- `evaluation_job` is the product-level request
- `test_run` is the execution artifact
- `test_results` are per-test scored outputs
- `evaluation_traces` store detailed oracle and explanation traces

### 3.1 Evaluation Job

Add a new persisted entity: `evaluation_job`.

Its purpose is to represent what a client-facing user asked the system to evaluate.

Suggested fields:

- `job_id`
- `status`
- `submitted_at`
- `started_at`
- `completed_at`
- `submitted_by` optional plain text
- `team_name` optional plain text
- `client_name` optional plain text
- `project_name` optional plain text
- `provider`
- `model_name`
- `dataset_id` or `dataset_path`
- `dataset_version`
- `oracle_profile`
- `evaluation_mode`
- `repeat_count`
- `temperature`
- `max_output_tokens`
- `timeout_seconds`
- `notes`
- `linked_run_id` nullable
- `failure_reason` nullable

### 3.2 Status Model

The MVP status model should stay simple:

- `draft`
- `queued`
- `running`
- `completed`
- `failed`

If execution remains synchronous in the first thin implementation, the backend may internally transition quickly from:

- `draft -> running -> completed`

The model should still store explicit status so asynchronous execution can be added later without redesigning the API.

### 3.3 Test Run Relationship

`evaluation_job` should reference exactly one primary `test_run` in the MVP.

That keeps the first implementation simple:

- one job
- one run configuration
- one main result set

Later, the model can expand to support:

- reruns
- alternative models for the same job
- scenario variants
- recommendation workflows

### 3.4 Oracle Profile

The MVP should introduce the notion of an `oracle_profile` as a named configuration choice in the job layer.

This should not require redesigning the oracle engine yet. In the first iteration, an oracle profile can be:

- a stored label
- a mapping to known backend defaults
- a configuration bundle used by the existing evaluation pipeline

The goal is to make oracle selection product-friendly before making it deeply dynamic.

## 4. API Plan

The backend should evolve from action-style endpoints into a job-oriented API while preserving existing internal routes during migration.

### 4.1 Keep Existing Endpoints Temporarily

Keep current routes working for Streamlit and internal development:

- `POST /load-test-cases`
- `POST /run-batch`
- `GET /report/{run_id}`
- candidate-related routes

These remain useful while the new job API is introduced.

### 4.2 Add Job-Oriented Endpoints

Introduce a new job API surface for the client app.

Suggested MVP endpoints:

- `POST /evaluation-jobs`
  - create a new job
- `GET /evaluation-jobs`
  - list recent jobs
- `GET /evaluation-jobs/{job_id}`
  - fetch job metadata and status
- `POST /evaluation-jobs/{job_id}/run`
  - trigger evaluation execution
- `GET /evaluation-jobs/{job_id}/summary`
  - fetch top-level metrics and summary
- `GET /evaluation-jobs/{job_id}/failed-cases`
  - fetch failed or low-score cases
- `GET /evaluation-jobs/{job_id}/traces`
  - fetch oracle traces for inspection
- `GET /evaluation-jobs/{job_id}/report`
  - fetch a simple exportable report payload

### 4.3 API Rules

- `FastAPI` is the only execution boundary
- the Next.js app never calls storage or evaluation code directly
- the API should return product-facing response models, not raw storage rows
- job endpoints should be stable even if the underlying run implementation changes later

### 4.4 Migration Strategy

Do not rewrite the existing backend in one pass.

Instead:

1. add a thin `evaluation_job` storage and service layer
2. map job execution onto the existing `run_batch_workflow`
3. derive summary, failed cases, traces, and report views from existing stored run data
4. progressively separate older action endpoints from newer product endpoints

## 5. Frontend Responsibilities: Next.js

The first client-facing app should be intentionally narrow.

### MVP Flow

1. create an evaluation job
2. choose provider, model, dataset, and oracle profile
3. view job status
4. review summary metrics
5. inspect failed cases
6. export or copy a simple report

### What Next.js Owns

- workflow UX
- forms
- job list and detail pages
- status polling or refresh interactions
- result presentation for client-facing review
- simple report export or copy flow

### What Next.js Does Not Own

- evaluation orchestration logic
- oracle logic
- result scoring
- trace generation
- report computation rules

### MVP Pages

Suggested first pages:

- `Jobs`
  - list recent evaluation jobs
- `New Job`
  - create a new evaluation job
- `Job Detail`
  - status, metadata, summary metrics
- `Failed Cases`
  - failed or low-score cases for the job
- `Trace Inspector`
  - oracle explanation and trace details

The UI should stay thin and practical. It does not need auth, multi-tenant layout, or recommendation UX yet.

## 6. Streamlit Responsibilities

`Streamlit` remains the internal admin and research surface.

It should continue to own:

- experiment analytics
- model comparison
- dataset studio and candidate review
- trace replay workflows
- deep failure analysis
- oracle debugging
- internal inspection of runs across datasets and models

Streamlit should not be treated as the client-facing product surface going forward.

Instead, it becomes:

- internal admin board
- analytics showcase
- research and debugging console

This allows the existing investment in Streamlit to remain useful without forcing product UX into it.

## 7. Phased Implementation Plan

### Phase 1: Backend Job Foundation

Goals:

- introduce `evaluation_job` storage and service layer
- keep the old run system intact
- map jobs onto existing run execution

Deliverables:

- new job model and persistence
- job status lifecycle
- linkage from job to run
- basic job CRUD and run trigger endpoints

Exit criteria:

- a job can be created, stored, executed, and linked to a completed run

### Phase 2: Product-Facing Read APIs

Goals:

- expose review-ready job data without requiring Streamlit

Deliverables:

- summary endpoint
- failed case endpoint
- trace endpoint
- simple report/export endpoint

Exit criteria:

- all client-facing review screens can be powered entirely by FastAPI

### Phase 3: Next.js MVP App

Goals:

- deliver the first client-facing workflow

Deliverables:

- Next.js app scaffold
- job creation flow
- job detail/status page
- summary metrics page/section
- failed case inspection
- trace inspection
- simple report copy/export

Exit criteria:

- a user can complete the full MVP flow without using Streamlit

### Phase 4: Streamlit Repositioning

Goals:

- simplify Streamlit’s role and reduce overlap with the client app

Deliverables:

- navigation updates and copy changes
- clearer internal/admin framing
- reduced duplication of client-facing workflow screens where appropriate

Exit criteria:

- Streamlit is clearly internal/admin-focused

### Phase 5: Hardening and Testing

Goals:

- stabilize the new split architecture

Deliverables:

- API contract tests for job flows
- service tests for job orchestration
- frontend integration coverage for core Next.js flows
- better local setup docs for dual UI development

Exit criteria:

- the MVP flow is reliable enough to support future modules

### Phase 6: Later Modules on Top of Jobs

Only after the evaluation job system is stable:

- candidate test generation module
- recommendation module based on measured evaluation data
- richer oracle profile management
- ownership and auth
- asynchronous execution and queueing

## 8. Risks and Controls

### Risk: API drift between Streamlit and Next.js

Control:

- preserve existing internal endpoints during migration
- build the new job API as an additive layer first

### Risk: frontend logic duplication

Control:

- keep all business logic in FastAPI
- expose product-facing response models from Python services

### Risk: overengineering too early

Control:

- keep the MVP to one job, one primary run, one review flow
- no auth
- no queueing platform
- no recommendation engine yet

### Risk: unclear job vs run semantics

Control:

- document and enforce the distinction in API models and storage naming
- treat `evaluation_job` as the request layer and `test_run` as the execution layer

### Risk: weak provider abstraction blocks future API providers

Control:

- use the backend refactor to formalize provider/model selection contracts
- avoid binding new job APIs too tightly to `ollama`

### Risk: Streamlit and Next.js overlap too much

Control:

- define clear surface ownership early
- keep Streamlit for admin/research
- keep Next.js for the product workflow

## 9. Non-Goals

The first MVP will not include:

- authentication
- authorization
- RBAC
- sessions
- JWT or OAuth
- multi-tenant access control
- recommendation-first UX
- test generation as the primary flow
- fully dynamic oracle authoring
- distributed execution infrastructure
- production queueing/orchestration
- cloud-native deployment redesign

These can be added later after the evaluation workflow is stable and useful.

## 10. Practical Guidance for Future Development

When implementing follow-up tasks:

- prefer additive backend refactors over full rewrites
- preserve working Streamlit analytics flows while introducing the job layer
- make FastAPI response models explicit and product-facing
- keep the first Next.js app thin and focused
- avoid moving domain logic into frontend code
- build later recommendation and candidate-generation modules on top of measured evaluation job data

This document should be treated as the working development direction for the next phase of the project.
