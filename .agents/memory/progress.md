---
name: Progress tracker
description: Item-by-item status of the improvement plan. Updated at each commit checkpoint.
---

# TCF Bot — Progress

**Last updated:** 2026-06-02

## Verification baseline

| Check | Result |
|---|---|
| `uv sync --extra test` | PASS |
| `uv run ruff format --check .` | PASS (97 files formatted/clean) |
| `uv run ruff check .` | PASS (0 errors) |
| `uv run --extra test pytest tests/ -q` | PASS (319 tests, 26 files, all green) |

## Completed items

| Item | Details | Date |
|---|---|---|
| Replit migration | Python 3.12, secrets in Replit Secrets, PORT=8080, bot starts and polls | 2026-06-02 |
| P1: ConversationHandler tests | ban_flow (8), warning_flow (12), appeal_flow (17) state-machine tests added | 2026-06-02 |
| P1: stats_flow NameError fix | `_paginate`, `_nav_row`, `_date` undefined — replaced with `paginate`, `nav_row`, `date_or_unknown` from `tcbot.utils.pagination` | 2026-06-02 |
| P1: check_flow NameError fix | Same undefined-name bug in check_flow.py, 12 call sites fixed, pagination import added | 2026-06-02 |
| P1: test_stats_flow.py import fix | Test imported `_paginate` from stats_flow; updated to import `paginate` from `tcbot.utils.pagination` | 2026-06-02 |
| P2: Flow class method docstrings | All flow class methods verified to have docstrings | 2026-06-02 |
| P2: Workflow docs | All 12 flows documented in docs/workflows/workflows.md | 2026-06-02 |
| check_flow test coverage | 19 new tests in test_check_flow.py covering all Check class view builders | 2026-06-02 |
| Memory files | context.md, progress.md, decisions.md, structure.md created | 2026-06-02 |
| pyproject.toml ruff fix | Ruff moved from `optional-dependencies.dev` to `[dependency-groups] dev`; `uv run ruff` now works | 2026-06-02 |
| P3.1 (PLAN Code Review) resolved | PLAN.md Code Review Findings P3.1 updated to Resolved; memory files purged of `uvx ruff` | 2026-06-02 |
| P3.3 composite index | `{user_id, first_name, username}` covered-query index added to `mongos.ensure_indexes()` | 2026-06-02 |
| P5.1 PLAN Code Review resolved | PLAN.md Code Review Findings P5.1 updated to Resolved (same composite index) | 2026-06-02 |
| README.md stale test count | Updated from 125/14 to 319/26 | 2026-06-02 |
| python-code-quality SKILL.md | pyproject.toml snippet updated to reflect current `[dependency-groups]` structure | 2026-06-02 |

## Pending (remaining P3 optional)

| Item | Priority | Notes |
|---|---|---|
| BOT_TOKEN format validation | P3 | Optional — PTB fails fast on malformed token; presence already enforced |
| MONGODB_URI format validation | P3 | Optional — Motor fails fast on malformed URI; presence already enforced |
| Module-interface types (types.py) | P3 | Only if cross-module signatures grow ambiguous |
| Query metrics collection | P3 | Data-driven tuning; gather Atlas PA data first |
