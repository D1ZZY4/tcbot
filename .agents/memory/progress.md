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
| `uv run ruff format --check .` | PASS (98 files unchanged) |
| `uv run ruff check .` | PASS (0 errors) |
| `uv run --extra test pytest tests/ -q` | PASS (332 tests, 26 files, all green) |

## Completed items

| Item | Priority | Details | Date |
|---|---|---|---|
| Replit migration | infra | Python 3.12, secrets in Replit Secrets, PORT=8080, bot starts and polls | 2026-06-02 |
| P1: ConversationHandler tests | P1 | ban_flow (8), warning_flow (12), appeal_flow (17) state-machine tests added | 2026-06-02 |
| P1: stats_flow NameError fix | P1 | `_paginate`, `_nav_row`, `_date` undefined — replaced with `paginate`, `nav_row`, `date_or_unknown` from `tcbot.utils.pagination` | 2026-06-02 |
| P1: check_flow NameError fix | P1 | Same undefined-name bug in check_flow.py, 12 call sites fixed, pagination import added | 2026-06-02 |
| P1: test_stats_flow.py import fix | P1 | Test imported `_paginate` from stats_flow; updated to import `paginate` from `tcbot.utils.pagination` | 2026-06-02 |
| P1: groups.py NameError bug fix | P1 | `_kb` undefined; replaced both call sites with `tcgroups_kb` from `keyboards.py` | 2026-06-02 |
| P2: Flow class method docstrings | P2 | All flow class methods verified to have docstrings | 2026-06-02 |
| P2: Workflow docs | P2 | All 12 flows documented in docs/workflows/workflows.md | 2026-06-02 |
| check_flow test coverage | P2 | 19 new tests in test_check_flow.py covering all Check class view builders | 2026-06-02 |
| Memory files | infra | context.md, progress.md, decisions.md, structure.md created | 2026-06-02 |
| pyproject.toml ruff fix | P3.1 | Ruff moved from `optional-dependencies.dev` to `[dependency-groups] dev`; `uv run ruff` now works | 2026-06-02 |
| P3.3 composite index | P3 | `{user_id, first_name, username}` covered-query index added to `mongos.ensure_indexes()` | 2026-06-02 |
| README.md stale test count | docs | Updated from 125/14 to 319/26 | 2026-06-02 |
| python-code-quality SKILL.md | docs | pyproject.toml snippet updated to reflect current `[dependency-groups]` structure | 2026-06-02 |
| cache.py TTL named constants | P3 | `_ROLE_CACHE_TTL_S`, `_CONNECTION_CACHE_TTL_S`, `_GROUPS_LIST_CACHE_TTL_S`, `_OWNER_CACHE_TTL_S` | 2026-06-02 |
| BOT_TOKEN / MONGODB_URI validators | P3 | `_warn_bot_token_fmt` + `_warn_mongodb_uri_fmt` in `__init__.py`; 13 new tests; total 332 | 2026-06-02 |
| `resolve_and_check` type annotation | P3 | `msg: Message` typed in `decorators.py` | 2026-06-02 |
| `keyboards.py` dead code removal | P3 | Removed `baninfo_proof_kb` (zero callers); docstrings on 6 functions | 2026-06-02 |
| `users_roles.get_owner_id` cast fix | P3 | `# type: ignore` replaced with `cast(int \| None, cached)` | 2026-06-02 |
| Replit workflow commands | infra | Changed to `python -m tcbot` / `python -m pytest`; uv sync fails on nix store | 2026-06-02 |
| Em-dash removal | P3 | `mongos.py`, `databases.md`, `CHANGELOG.md` — all 3 fixed | 2026-06-02 |
| Shared reply constants (`replies.py`) | P3 | 10 constants extracted from 11 modules; no string duplication remains | 2026-06-02 |
| Sequential awaits → asyncio.gather | P3 | `help.py`, `stats.py`, `reason_flow.py` — all converted | 2026-06-02 |
| `docs/mapping.md` freshness | docs | Added `identity.py`, `replies.py`, `pagination.py` entries | 2026-06-02 |
| `maintenance.py` magic number | P3 | `timeout=3.0` extracted to `_MEMBERSHIP_CHECK_TIMEOUT = 3.0` | 2026-06-02 |
| `disconnecting.py` magic number | P3 | `timeout=3.0` extracted to `_TG_TIMEOUT = 3.0` | 2026-06-02 |
| `maintenance.py` help format | P3 | Converted flat `__help_text__` blob to `__help_text__` + `__help_sections__` (last holdout) | 2026-06-02 |
| `replies.py` permission constants | P3 | Added `PERM_FOUNDER_ONLY`, `PERM_STAFF_ONLY`, `PERM_ADMIN_ABOVE` | 2026-06-02 |
| `admins.py` permission constants | P3 | "Who can use" and `show_alert` use `replies.PERM_FOUNDER_ONLY` | 2026-06-02 |
| `broadcasting.py` permission constants | P3 | "Who can use" / "Where to use" use `replies.PERM_STAFF_ONLY` / `replies.CONTEXT_EXEC_OR_GROUP` | 2026-06-02 |
| `start.py` grammar fix | P3 | Rewrote two broken welcome strings; "all help menu" / "assistant of X to manage" eliminated | 2026-06-02 |

## Pending (remaining optional)

| Item | Priority | Notes |
|---|---|---|
| Module-interface types (types.py) | P3 | Only if cross-module signatures grow ambiguous |
| Query metrics collection | P3 | Data-driven tuning; gather Atlas PA data first |
