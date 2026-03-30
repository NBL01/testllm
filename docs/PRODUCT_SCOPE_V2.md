# Product Scope V2

## Product Goal

Evolve the current LLM reliability demo into a continuous evaluation platform that supports:
- reproducible regression testing,
- real failure replay,
- adversarial probing,
- and model-assisted test authoring with human review.

## Primary Users

- ML/LLM engineer
- QA engineer
- Data analyst
- Technical reviewer / team lead

## Core Product Capabilities (In Scope)

1. Evaluation execution:
- Run model batches by dataset version and evaluation mode.
- Track repeated attempts and consistency.

2. Oracle-based scoring:
- Keep transparent scoring with explanation and details.
- Separate strict and lenient interpretation where applicable.

3. Data governance:
- Dataset versions and source tracking (`regression`, `trace_replay`, `adversarial`, `synthetic`).
- Candidate test case review workflow before promotion.

4. Test authoring engine (new in V2):
- Generate candidate test cases from weak categories/failure patterns.
- Validate candidate quality and oracle compatibility.
- Export candidates for reviewer approval.

5. Frontend workflow:
- Run Lab (launch and monitor runs)
- Analytics (KPI + category/oracle/error views)
- Result Inspector (case-level root cause)
- Dataset Studio (candidate/review/promotion workflow)
- Model Comparison (multi-run summary)

## Out of Scope (V2)

- Multi-tenant authentication and organization-level RBAC
- Distributed serving/queueing infrastructure
- Cloud-native orchestration
- Fully automatic candidate promotion without human review

## Success Metrics

- >= 90% of failed attempts have an explainable root cause (`error_type` + `explanation`).
- <= 15% prompt duplication in the default synthetic benchmark set.
- Median-based model comparison supported across >= 3 runs/model.
- Candidate generation can produce review-ready cases by target category.

## V2 Design Principles

- Keep evaluation logic deterministic and auditable.
- Prefer explicit formulas and traceability over black-box scoring.
- Separate product layers clearly:
  ingestion -> run -> oracle -> storage -> analytics -> UI -> authoring/review.
- Keep local-first workflow (DuckDB + local models) functional.
