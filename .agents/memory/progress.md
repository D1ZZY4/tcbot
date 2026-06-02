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
| `uvx ruff format --check .` | PASS (97 files formatted/clean) |
| `uvx ruff check .` | PASS (0 errors) |
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
| check_flow test coverage | 18 new tests in test_check_flow.py covering all Check class view builders | 2026-06-02 |
| Memory files | context.md, progress.md, decisions.md, structure.md created | 2026-06-02 |

## Pending (P3 optional)

| Item | Priority | Notes |
|---|---|---|
| BOT_TOKEN format validation | P3 | Optional — PTB fails fast on malformed token |
| MONGODB_URI format validation | P3 | Optional — Motor fails fast on malformed URI |
| Composite index on member_cache | P3 | `{user_id,first_name,username}` for covered queries; marginal gain |
| Module-interface types (types.py) | P3 | Only if cross-module signatures grow ambiguous |
