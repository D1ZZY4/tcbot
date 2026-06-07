---
name: Progress tracker
description: Item-by-item status of the improvement plan. Updated at each commit checkpoint.
---

# TCF Bot - Progress

**Last updated:** 2026-06-07 (session 34)

## Verification baseline

| Check | Result |
|---|---|
| `uv sync` | PASS |
| `uv pip install -e .` | PASS |
| `uv run python -c "import tcbot; print('import OK')"` | PASS |
| `uv run python -m tcbot --help 2>&1 || uv run python -c "from tcbot import *; print('startup OK')"` | PASS by runtime evidence: bot started cleanly, connected MongoDB, ensured indexes, initialised, 75 handlers registered, polling active |
| `uv run ruff format .` | PASS (71 files already formatted) |
| `uv run ruff check --fix .` | PASS (All checks passed) |
| `uv run python -m tcbot` | PASS by runtime evidence: MongoDB connected, indexes ensured, scheduler started, bot polling active |
| annotation AST audit | PASS: 0 non-dunder function parameters missing type annotations (was 31 before session 34) |

## Completed items

| Item | Priority | Details | Date |
|---|---|---|---|
| Tracked workflow log cleanup | housekeeping | Removed tracked `check.log` and `format.log` from the repository root, and added targeted ignore rules so workflow-generated logs stay untracked in future runs | 2026-06-07 |
| Editable-install artifact ignore rule | housekeeping | Added `*.egg-info/` to `.gitignore` and removed the generated `tgbot_tcf.egg-info/` directory so mandatory `uv pip install -e .` no longer dirties the working tree | 2026-06-07 |
| docs/setup.md Docker command sync | docs | Corrected the Docker runtime command to match `Dockerfile` and removed the duplicated hosted-start command line | 2026-06-06 |
| Mermaid startup-log flowchart for agent Replit doc | docs | Added a compact Mermaid flowchart to `.agents/REPLIT.md` covering the Replit startup-log verification sequence and the handoff to Telegram testing | 2026-06-06 |
| Mermaid deployment-runtime flowchart for Replit doc | docs | Added a compact Mermaid flowchart to `replit.md` covering secrets, env setup, `uv sync`, startup prerequisites, polling, and health check exposure | 2026-06-06 |
| Mermaid flowchart for agent validation workflow | docs | Added a compact validation-order Mermaid diagram to `.agents/WORKFLOW.md` covering focused checks, Ruff, runtime verification, and reporting | 2026-06-06 |
| Mermaid coverage for top-level docs | docs | Added rendered Mermaid diagrams to `README.md` and `PLAN.md` for architecture summary, startup sequence, and request-processing flow | 2026-06-06 |
| Markdown dash cleanup across authored docs | docs | Removed remaining em dash and en dash characters from tracked memory docs and `CHANGELOG.md`; follow-up audit confirmed no tracked authored Markdown files still contain those Unicode dash characters | 2026-06-06 |
| `.agents/memory/context.md` Ruff baseline sync | docs | Updated stale Ruff file-count note from 142 to the current 143-file baseline verified in session 16 | 2026-06-06 |
| `.agents/CLAUDE.md` emoji-policy contradiction fix | docs | Replaced stale "use 1-3 emojis" guidance with the canonical no-emoji, no-emoticon bot-voice rule so agent instructions are internally consistent | 2026-06-06 |
| structure.md handlers/ layout fix | docs | Removed stale handlers/ subtree; modules are flat under tcbot/modules/ | 2026-06-06 |
| modules/types.py docs | docs | mapping.md + modules/modules.md entries | 2026-06-06 |
| decisions.md: frozen-dataclass monkeypatch lesson | docs | FrozenInstanceError on setattr; patch module-level name with MagicMock instead | 2026-06-06 |
| Replit migration | infra | Python 3.12, secrets in Replit Secrets, PORT=8080, bot starts and polls | 2026-06-02 |
| P1: stats_flow NameError fix | P1 | `_paginate`, `_nav_row`, `_date` undefined - replaced from `tcbot.utils.pagination` | 2026-06-02 |
| P1: check_flow NameError fix | P1 | Same undefined-name bug in check_flow.py, 12 call sites fixed | 2026-06-02 |
| P1: groups.py NameError bug fix | P1 | `_kb` undefined; replaced both call sites with `tcgroups_kb` from `keyboards.py` | 2026-06-02 |
| P2: Flow class method docstrings | P2 | All flow class methods verified to have docstrings | 2026-06-02 |
| P2: Workflow docs | P2 | All 12 flows documented in docs/workflows/workflows.md | 2026-06-02 |
| Memory files | infra | context.md, progress.md, decisions.md, structure.md created | 2026-06-02 |
| pyproject.toml ruff fix | P3.1 | Ruff moved from `optional-dependencies.dev` to `[dependency-groups] dev` | 2026-06-02 |
| P3.3 composite index | P3 | `{user_id, first_name, username}` covered-query index added | 2026-06-02 |
| cache.py TTL named constants | P3 | `_ROLE_CACHE_TTL_S`, `_CONNECTION_CACHE_TTL_S`, `_GROUPS_LIST_CACHE_TTL_S`, `_OWNER_CACHE_TTL_S` | 2026-06-02 |
| BOT_TOKEN / MONGODB_URI validators | P3 | `_warn_bot_token_fmt` + `_warn_mongodb_uri_fmt` in `__init__.py` | 2026-06-02 |
| `resolve_and_check` type annotation | P3 | `msg: Message` typed in `decorators.py` | 2026-06-02 |
| `keyboards.py` dead code removal | P3 | Removed `baninfo_proof_kb` (zero callers); docstrings on 6 functions | 2026-06-02 |
| `users_roles.get_owner_id` cast fix | P3 | `# type: ignore` replaced with `cast(int \| None, cached)` | 2026-06-02 |
| Replit workflow commands | infra | Changed to `python -m tcbot` | 2026-06-02 |
| Em-dash removal | P3 | `mongos.py`, `databases.md`, `CHANGELOG.md` - all 3 fixed | 2026-06-02 |
| Shared reply constants (`replies.py`) | P3 | 10 constants extracted from 11 modules; no string duplication remains | 2026-06-02 |
| Sequential awaits to asyncio.gather | P3 | `help.py`, `stats.py`, `reason_flow.py` - all converted | 2026-06-02 |
| `docs/mapping.md` freshness | docs | Added `identity.py`, `replies.py`, `pagination.py` entries | 2026-06-02 |
| `maintenance.py` magic number | P3 | `timeout=3.0` extracted to `_MEMBERSHIP_CHECK_TIMEOUT = 3.0` | 2026-06-02 |
| `disconnecting.py` magic number | P3 | `timeout=3.0` extracted to `_TG_TIMEOUT = 3.0` | 2026-06-02 |
| `maintenance.py` help format | P3 | Converted flat `__help_text__` blob to `__help_text__` + `__help_sections__` | 2026-06-02 |
| `replies.py` permission constants | P3 | Added `PERM_FOUNDER_ONLY`, `PERM_STAFF_ONLY`, `PERM_ADMIN_ABOVE` | 2026-06-02 |
| `admins.py` permission constants | P3 | "Who can use" and `show_alert` use `replies.PERM_FOUNDER_ONLY` | 2026-06-02 |
| `broadcasting.py` permission constants | P3 | Uses `replies.PERM_STAFF_ONLY` and `replies.CONTEXT_EXEC_OR_GROUP` | 2026-06-02 |
| `start.py` grammar fix | P3 | Rewrote two broken welcome strings | 2026-06-02 |
| docs-maintainer SKILL.md staleness | docs | date bumped to 2026-06-02 | 2026-06-02 |
| docs/helper/helper.md replies.py table | docs | Expanded from 10 to 15 constants; added ERR_GROUP_ONLY, ERR_NO_CONNECTED_GROUPS, ERR_GROUP_NOT_FOUND, PERM_FOUNDER_ONLY, PERM_STAFF_ONLY, PERM_ADMIN_ABOVE | 2026-06-02 |
| docs/utils/utils.md mermaid filename | docs | Fixed `logging_setup.py` → `logger.py` in Mermaid diagram node | 2026-06-02 |
| .agents/memory/structure.md filename | docs | Corrected `logging_setup.py` → `logger.py` | 2026-06-02 |
| PTBUserWarning runtime suppression | maintenance | warnings.filterwarnings in __main__.py; startup log now fully clean | 2026-06-02 (s2) |
| 20 handler docstrings | P4 | All public functions 30+ lines now have docstrings: admins(6), disconnecting(2), warning_flow(2), banning, broadcasting, checking, connecting, kicking, maintenance, muting, start, warnings, unban_flow | 2026-06-02 (s2) |
| 10 medium handler docstrings | P4 | All public functions 16-29 lines now have docstrings: admins(1), checking(2), logger(1), maintenance(1), muting(1), warning_flow(2), warnings(2) | 2026-06-02 (s2) |
| Docstrings batch 1 (14 fns, 10+ lines) | P4 | All public functions 10+ lines now have docstrings: __main__, admins, greeting, groups, decorators(×3), ban_flow, privacy(×2), start, stats, unbanning | 2026-06-02 (s3) |
| Docstrings batch 2 (22 fns, 5-9 lines) | P4 | about, additional, admins(×2), checking(×6), decorators(×4), ban_flow, stats(×3), warnings, logger, prefixes(×2) | 2026-06-02 (s3) |
| Docstrings batch 3 (13 fns, 3-4 lines) | P4 | checking(×2), parse_link, ban_flow, start, stats(×8). AST audit: 0 public fns 3+ lines missing | 2026-06-02 (s3) |
| Class docstrings (10 TypedDict classes) | P4 | All public classes in documents.py. AST audit: 0 public classes missing docstrings | 2026-06-02 (s3) |
| CHANGELOG.md duplicate removed | docs | Removed stale duplicate batch-1 docstring entry from session-3 header | 2026-06-02 (s3) |
| Sequential await fix: admins.py (cmd_promote/cmd_demote) | P3 | asyncio.gather(identity.classify(...), db.users_roles.get_effective_role(...)) | 2026-06-02 (s5) |
| Sequential await fix: stats.py (12 handlers) | P3 | Refactored _ack_and_render(q, data_coro); q.answer() + DB fetch now parallel | 2026-06-02 (s5) |
| Sequential await fix: groups.py _toggle cache-hit path | P3 | asyncio.gather(q.answer(), safe_edit(...)) in cache-hit branch | 2026-06-02 (s5) |
| Sequential await fix: identity.classify() (high-impact) | P3 | get_user_mention_data + get_effective_role now gathered; affects all mod commands | 2026-06-02 (s5) |
| performance.yml: `users_db` → `users_cache` + `import os` | P4 | Both benchmark fns fixed; missing import fixed; 3 bugs total | 2026-06-03 (s6) |
| 4x "02:00 UTC" to "04:00 UTC" | docs | auto-fix.yml comment + docs/workflows-guide.md x2 + README.md | 2026-06-03 (s6) |
| run-bot.yml description | docs | "Manual deployment" to correct schedule summary in docs/workflows-guide.md + README.md | 2026-06-03 (s6) |
| config.env.example PORT comment | docs | Removed "auto = pick free port", actual fallback is 5000 | 2026-06-03 (s6) |
| config.env.example PROOFS/LOGS/LOGS_ERRORS/APPEALS auto comments | docs | Removed 4 "auto = create forum thread in MAIN_GROUP" blocks (feature never existed) | 2026-06-03 (s6) |
| 12 public function docstrings | P4 | bold, italic, code, link, esc, on_groups_details, on_groups_simple, on_help_menu, on_helpc_main, appeal_deep_link, on_menu_groups, on_menu_groups_simple | 2026-06-03 (s6) |
| PLAN.md Code Review Findings | docs | Added P4 rows 2-8 for all session-6 findings; all Resolved | 2026-06-03 (s6) |
| replies.py section-header constants (SEC_*) | P4 | SEC_COMMANDS/WHO/WHERE/WHAT/EXAMPLES/TARGET added; all 14 module files updated | 2026-06-03 (s7) |
| replies.py NO_REASON constant | P4 | NO_REASON = "No reason provided"; 7 callers (ban_flow, kicking_flow, muting_flow, reason_flow×2, ban_info, checking) updated | 2026-06-03 (s7) |
| 30 property docstrings in tcbot/__init__.py | P4 | Configs (8) and _CfgAdapter (22) properties; AST audit: 0 public fns missing docstrings across all tcbot/ source | 2026-06-03 (s7) |
| `get_bot()` Protocol stub docstring | housekeeping | Added missing docstring to `_MessageLike.get_bot()` in `tcbot/utils/prefixes.py`; AST audit now reports 0 missing | 2026-06-07 (s25) |
| Ruff file-count baseline update 143->144 | housekeeping | Updated across CHANGELOG.md, context.md, progress.md | 2026-06-07 (s25) |
| `check_flow.py` magic number constants | housekeeping | Extracted `_REASON_PREVIEW_LEN = 80` and `_BUTTON_TITLE_MAX = 24`; replaced 3 bare slice literals | 2026-06-06 (s26) |
| `help.py` prefix-offset self-documentation | housekeeping | `data[6:]`/`data[7:]` replaced with `data[len("helpc_"):]`/`data[len("helps_"):]`/`data[len("helpcs_"):]` | 2026-06-06 (s26) |
| MEMORY.md stale link removal | housekeeping | Removed broken `../../nothing.md` index entry; file no longer exists | 2026-06-06 (s26) |
| MongoDB connection-pool named constants | housekeeping | Extracted 7 constants to `mongos.py`; replaced all bare literals in `AsyncIOMotorClient()` call | 2026-06-06 (s30) |
| Ratelimiter constants — all 16 modules | housekeeping | `_RL_*` constants extracted to all 16 modules with `@ratelimiter` decorators; every bare `limit=`/`period=` literal in `tcbot/modules/` replaced | 2026-06-06 (s30) |
| Full doc audit | housekeeping | Updated replies.py table in helper.md (+9 missing constants). All 10 developer docs verified accurate. | 2026-06-06 (s29) |

| Parameter type annotation coverage | housekeeping | Fixed 31 unannotated parameters across 13 files; AST audit now reports 0 missing in all non-dunder functions | 2026-06-07 (s34) |
| BaseFilter import location discovery | housekeeping | BaseFilter is in telegram.ext.filters, not telegram.ext; corrected imports across 6 workflow files after ImportError at startup | 2026-06-07 (s34) |
| Return type annotation coverage | housekeeping | Fixed 12 functions missing return types across 9 files (7 DB accessors, __main__, extraction.py); AST audit now reports 0 missing | 2026-06-07 (s35) |

## Pending (remaining optional)

| Item | Priority | Notes |
|---|---|---|
| Module-interface types (types.py) | P3 | Only if cross-module signatures grow ambiguous |
| Query metrics collection | P3 | Data-driven tuning; gather Atlas PA data first |
