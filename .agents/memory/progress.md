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
| `uv run --extra test pytest tests/ -q` | PASS (332 tests, 26 files, all green) |

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

| cache.py TTL named constants | P3 | `_ROLE_CACHE_TTL_S`, `_CONNECTION_CACHE_TTL_S`, `_GROUPS_LIST_CACHE_TTL_S`, `_OWNER_CACHE_TTL_S` — replaced inline floats with named module-level constants | 2026-06-02 |
| BOT_TOKEN / MONGODB_URI validators | P3 | `_warn_bot_token_fmt` + `_warn_mongodb_uri_fmt` added to `__init__.py`; called from `Configs.load()`; `import re` moved to module level; 13 new tests in `test_config_parse.py` — total now 332 | 2026-06-02 |
| `resolve_and_check` type annotation | P3 | `Message` added to `from telegram import ...` in `decorators.py`; `msg` parameter typed as `msg: Message` | 2026-06-02 |
| `keyboards.py` dead code removal | P3 | Removed `baninfo_proof_kb` (zero callers); section header updated; docstrings added to 6 public functions | 2026-06-02 |
| `users_roles.get_owner_id` cast fix | P3 | `# type: ignore[return-value]` replaced with `cast(int | None, cached)` — consistent with `get_effective_role` line 209 and `groups_db.py` pattern | 2026-06-02 |
| `groups.py` NameError bug fix | P1 | `_kb` undefined; replaced both call sites with `tcgroups_kb` imported from `keyboards.py`; removed stale `keyboards` from module-level helper import | 2026-06-02 |
| Replit workflow commands | infra | Changed `Start Application` and `Run Tests` from `uv run ...` to `python ...`; uv sync fails on nix store (read-only); packages installed via pip | 2026-06-02 |

| Em-dash removal (source + docs) | P3 | `mongos.py` comment, `databases.md` table, `CHANGELOG.md` entry — all 3 fixed | 2026-06-02 |
| Shared reply constants (`replies.py`) | P3 | 10 constants extracted from 11 modules; 0 actionable string dupes remain | 2026-06-02 |

## Pending (remaining optional)

| Item | Priority | Notes |
|---|---|---|
| Module-interface types (types.py) | P3 | Only if cross-module signatures grow ambiguous |
| Query metrics collection | P3 | Data-driven tuning; gather Atlas PA data first |
