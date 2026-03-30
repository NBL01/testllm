# Roadmap V2

## Phase 1: Scope Freeze and Baseline Hardening (Weeks 1-2)

Deliverables:
- Product scope and architecture boundary docs
- Stable dataset baseline (`v2.x`) and evaluation configs
- Reliability metric freeze for baseline comparisons

Exit Criteria:
- Team agrees on in-scope/out-of-scope
- Reproducible benchmark run can be repeated end-to-end

## Phase 2: Test Authoring Engine (Weeks 3-5)

Deliverables:
- Candidate generation service (seeded + optional model-assisted prompt rewrite)
- Candidate validators and quality scoring
- Candidate export path (`data/candidates/*.jsonl`)

Exit Criteria:
- Generate category-targeted candidate sets from CLI
- Validation errors and quality score available per candidate

## Phase 3: Dataset Studio UX (Weeks 6-8)

Deliverables:
- Frontend Dataset Studio page
- Candidate review states: draft/reviewed/approved/rejected
- Promotion flow from candidate to reusable test cases

Exit Criteria:
- Reviewer can inspect and approve/reject candidate cases without editing raw files manually

## Phase 4: Comparative Analytics Upgrade (Weeks 9-10)

Deliverables:
- Strict-vs-lenient score split in reports
- Stronger model comparison summaries (multi-run medians)
- Coverage deltas by category/source/oracle

Exit Criteria:
- Comparison output supports reliable model selection decisions

## Phase 5: Operational Maturity (Weeks 11-12)

Deliverables:
- Better onboarding docs and runbooks
- Regression test expansion for critical modules
- Release checklist and version tagging process

Exit Criteria:
- New contributors can run and extend system in under 30 minutes
