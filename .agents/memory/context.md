---
name: Project context
description: Current state of TCF Bot project - what is done, in progress, and pending. Update before every commit.
---

# TCF Bot - Current Context

**Last updated:** 2026-06-06 (session 30)

## What is done

- Python 3.12, uv, python-telegram-bot 22.5, Motor/MongoDB stack fully configured on Replit.
- BOT_TOKEN and MONGODB_URI in Replit Secrets; PORT=8080 in environment.
- 1486 tests across 71 test files; full suite passes offline with **0 warnings**.
- `uv run ruff format .` and `uv run ruff check .` both clean (144 files).
- All P1/P2/P3 backlog items resolved (ConversationHandler tests, pagination NameError, composite indexes, asyncio.gather conversions, shared replies.py, em-dash removal, cache TTL constants, keyboards.py dead code).
- `docs/mapping.md` updated: added `identity.py`, `replies.py` to helper section; added `pagination.py` to utils section.
- `maintenance.py` and `disconnecting.py` hardcoded `timeout=3.0` extracted to named constants.
- `maintenance.py` converted to `__help_text__` + `__help_sections__` format (last holdout; all modules now consistent).
- `replies.py` now has full permission-tier set: `PERM_TESTER_ABOVE`, `PERM_DEV_ABOVE`, `PERM_ADMIN_ABOVE`, `PERM_STAFF_ONLY`, `PERM_FOUNDER_ONLY`.
- `admins.py` and `broadcasting.py` updated to use `replies.PERM_FOUNDER_ONLY` / `replies.PERM_STAFF_ONLY` throughout.
- `start.py` welcome messages rewritten to fix broken grammar.
- Comprehensive source audit: CLEAN - no emoji, em-dash, or emoticons anywhere in tcbot/.
- Bot restarts cleanly: MongoDB connected, indexes ensured, 75 handlers registered, polling active.
- `kicking_flow.py` SyntaxError fixed.
- All inline-string extractions complete across all modules and workflows.
- Comprehensive doc audit complete (2026-06-02): fixed 4 stale references.
- 15 new test files added (2026-06-02): full coverage of db helpers, formatter, extraction, etc. Suite: 698 → 966 tests / 50 → 65 files.
- PTBDeprecationWarning eliminated: `PTB_TIMEDELTA=1` in conftest.py.
- `tcbot/__main__.py`: module-level `warnings.filterwarnings` added for PTBUserWarning.
- Docstrings added to all public handler/executor functions (AST audit: 0 missing).
- Class docstrings on all public classes in documents.py.
- 3 more test files (test_alive, test_documents, test_types): suite 966 → 1039 / 65 → 69 files.

- Sequential await fixes (session 5):
  - `identity.classify()`: gather get_user_mention_data + get_effective_role (affects all mod commands)
  - `stats.py`: refactored `_ack_and_render(q, data_coro)` - 12 handlers fixed
  - `groups.py _toggle` cache-hit path: gather q.answer() + safe_edit()
  - `admins.py cmd_promote/cmd_demote`: gather identity.classify + get_effective_role

- Handler-behavior tests added (session 5):
  - 13 async tests for `classify()` in test_identity.py: all 9 identity kinds + gather-correctness
  - 21 handler-behavior tests: cmd_ban_start(6), cmd_kick(5), cmd_mute(5), cmd_warn_entry(5)
  - 21 more handler-behavior tests: cmd_unban(3), cmd_unmute(4), cmd_unwarn(3), cmd_warnlist(2), cmd_resetwarns(3)
  - Suite: 1039 → 1112 → 1127 → 1141 → 1152 tests; all 69 test files, all green.
  - Batch 3 (14 tests): cmd_promote(4)+cmd_demote(5) in test_admins.py; cmd_checkme(3)+cmd_check(2) in test_checking.py.
  - Batch 4 (11 tests): cmd_tcconnect(5) in test_connecting.py; cmd_tcdisconnect(4)+cmd_rmtc(2) in test_disconnecting.py.

- Session 6 doc / workflow accuracy fixes (2026-06-03):
  - Fixed `performance.yml` benchmark: `users_db` → `users_cache` (both benchmark functions), added `import os` to compare-baseline script.
  - Fixed 4 occurrences of "02:00 UTC" → "04:00 UTC" (auto-fix.yml comment, docs/workflows-guide.md ×2, README.md).
  - Fixed "Manual dispatch only / Manual deployment" in docs/workflows-guide.md and README.md for run-bot.yml (actual trigger: cron every 4 hours).
  - Fixed config.env.example: removed misleading `PORT=auto` "pick free port" comment; removed four `PROOFS/LOGS/LOGS_ERRORS/APPEALS=auto` "create forum thread" comments.
  - Added docstrings to 12 public functions: `bold`, `italic`, `code`, `link`, `esc`, `on_groups_details`, `on_groups_simple`, `on_help_menu`, `on_helpc_main`, `appeal_deep_link`, `on_menu_groups`, `on_menu_groups_simple`.
  - Added 8 new P4 findings rows to PLAN.md Code Review Findings; all `Resolved`.

- Session 7 constant propagation and tests (2026-06-03):
  - Added `SEC_COMMANDS`, `SEC_WHO`, `SEC_WHERE`, `SEC_WHAT`, `SEC_EXAMPLES`, `SEC_TARGET` to `replies.py`; all 14 module files updated.
  - Added `NO_REASON = "No reason provided"` to `replies.py`; 7 callers updated.
  - `test_replies.py` extended: 10 new constants in `_ALL_CONSTANTS`; all coverage tests pass automatically.
  - `test_ban_info.py` and `test_reason_flow.py` updated to use `replies.NO_REASON`.
  - Handler-behavior tests: 15 new tests across `test_broadcasting.py`, `test_greeting.py`, `test_groups.py`.
  - Test suite: 1152 → 1167 (all green, 0 warnings). Ruff clean (141 files).

- Session 8 symlinks + tests (2026-06-03):
  - `.kilo/kilo.json` moved to `.agents/kilo.json`; `.kilo/` replaced with symlink `.kilo -> .agents`.
  - `.trae/skills/` (stale duplicate) deleted; `.trae/` replaced with symlink `.trae -> .agents`.
  - Test file count corrected in all docs: 71 -> 70 (actual ls count).
  - Test count updated: 1251 -> 1259 (8 new handler-behavior tests).
  - 5 tests in test_maintenance.py: cmd_leaveall (no-groups error, status sent, status edited) + cmd_cleanup (no stale reply-zero, stale deactivated).
  - 3 tests in test_stats.py: cmd_stats (calls Stats.main, HTML parse mode, reply_markup forwarded).

- Session 9 callback handler tests + docs audit (2026-06-03):
  - 8 new stats callback tests (test_stats.py 19->27): on_stats_main, on_stats_admins, on_stats_bans (2), on_stats_bans_search, on_stats_search_cancel, on_bans_search_input (2).
  - 7 new help callback tests (test_help.py 18->25): on_help_menu_group, on_help_menu, on_helpc_main, on_help_topic_any (2), on_help_section (2).
  - 7 new admins callback tests (test_admins.py 31->38): on_demote_cancel, on_promote_role_cancel, on_demote_confirm (2), on_promote_role_btn, on_promo_decision (2).
  - 10 new checking callback tests (test_checking.py 25->35): on_checkme_detail, on_checkme_back, on_check_main, on_check_bans, on_check_ban_item, on_check_warns, on_check_warn_chat, on_check_kicks, on_check_mutes, on_check_appeals.
  - 7 new stats remaining callbacks (test_stats.py 27->34): on_stats_users, on_stats_user_item, on_stats_chats, on_stats_chat_item, on_stats_ban_item, on_stats_search_item, on_stats_search_back.
  - 4 new start callback tests (test_start.py 15->19): on_back_to_start, on_menu_groups, on_menu_groups_details, on_menu_groups_simple.
  - Test count: 1259 -> 1302 (70 files, 1 warning, all green).
  - Stale test inventory count fixed across all docs: 1251/71 -> 1302/70.
  - Full docs audit: all .md files reviewed; all Mermaid diagrams verified accurate; no stale content found beyond test counts.

- Session 14 (2026-06-06): docs + tests
  - Fixed stale `handlers/` layout in `.agents/memory/structure.md`.
  - Added 6 admins callback happy-path/guard tests (`on_demote_confirm`, `on_promote_role_btn`).
  - Added `tests/test_module_types.py` (6 tests) for `tcbot.modules.types`.
  - Documented `modules/types.py` in docs/mapping.md and docs/modules/modules.md.
  - Synced test inventory 1394/70 -> 1405/71 across root docs and memory files.
  - Updated `nothing.md` operating brief baseline.

- Session 25 (2026-06-07): final QA pass on Replit after migration.
  - AST audit: 0 public functions or classes missing docstrings (after fixing `_MessageLike.get_bot()` stub in `prefixes.py`).
  - All sequential await pairs verified as data-dependent; no independent sequential awaits remain.
  - Ruff file-count baseline updated 143 -> 144 across all memory and CHANGELOG references.
  - 1405 tests / 71 files, 0 warnings, all green. Ruff 144 files clean.

- Session 26 (2026-06-06): magic number cleanup in check_flow.py and help.py.
  - Extracted `_REASON_PREVIEW_LEN = 80` and `_BUTTON_TITLE_MAX = 24` to named constants in `check_flow.py`; replaced all bare slice literals.
  - Replaced `data[6:]` / `data[7:]` in `help.py` with `data[len("helpc_"):]` / `data[len("helps_"):]` / `data[len("helpcs_"):]` for self-documentation.
  - Removed stale `nothing.md` broken link from MEMORY.md index.
  - 1405 tests / 71 files, 0 warnings, all green. Ruff 144 files clean.

- Session 27 (2026-06-06): added 61 tests for previously-uncovered functions.
  - global_rate_limit_handler (6), all_roles (2), role_label property (7), parse_logmsg functions (14), Configs properties (12), ensure_indexes (2), get_handlers (4), ConversationHandler factories (14). 
  - _CfgAdapter property tests (3).
  - Fixed `_RateLimiter.__slots__` monkeypatch: patch module-level name, not instance attribute.
  - Renamed 6 inner `wrapper` -> `_wrapper` in decorators.py (false-positive coverage gaps).
  - 1466 -> 1469 tests / 71 files, 0 warnings. Ruff 144 files clean.

- Session 28 (2026-06-06): named constants cleanup + formatter helper + tests.
  - Extracted 8 named constants to `__main__.py` (HTTP timeouts, pool sizes, text/border widths).
  - Extracted `_DEFAULT_PORT` and `_ERR_OWNER_ID` constants to `__init__.py`; eliminated 6 repeated literals.
  - Added `proof_line(proof_desc)` to `formatter.py`; de-duplicated f-string from 3 flow files.
  - Extracted `_MAX_CONTEXT_LEN = 120` to `error_reporter.py`; replaced 2 bare `[:120]` slices.
  - Extracted `_SECS_PER_HOUR`, `_SECS_PER_DAY`, `_DAYS_PER_YEAR` to `muting_flow.py`; replaced all time-math literals.
  - Added `WHERE_CONNECTED_GROUP` to `replies.py`; replaced literal in kicking/muting/warnings.
  - Added 12 tests for 6 uncovered `parse_logmsg` functions; 5 tests for `proof_line()` helper.
  - 1466 -> 1486 tests / 71 files, 0 warnings. Ruff 144 files clean.

- Session 30 (2026-06-06): magic number extraction — MongoDB pool params + all ratelimiter constants across all 16 module files.
  - Extracted 7 named MongoDB constants to `mongos.py`; replaced all 7 bare literals in `connect()`.
  - Extracted `_RL_*` named constants to all 16 `tcbot/modules/*.py` files with `@ratelimiter` decorators; replaced every bare `limit=` and `period=` literal. Every `@ratelimiter` call-site in `tcbot/modules/` now uses named constants.
  - 1492 tests / 71 files, 0 warnings. Ruff 144 files clean.

- Session 29 (2026-06-06): full doc audit + coverage gap fill.
  - Fixed stale test counts in all 8 docs and memory files (1405/1466/1481 -> 1492).
  - Updated `docs/helper/helper.md` replies.py table: added 9 missing constants (ERR_PERM_EXPIRED, ERR_UNKNOWN_ROLE, WHERE_CONNECTED_GROUP, NO_REASON, SEC_* ×6).
  - Added 6 `TestCountErrors` tests to `test_dispatch.py`: `count_errors()` was the only public function in `tcbot/` with no test mention. Suite: 1486 -> 1492 / 71 files, 0 warnings. Ruff 144 files clean.

## What is in progress

Nothing. Session 29 checkpoint complete.

## What is pending (optional)

- Query metrics collection (data-driven; gather Atlas PA data first).

## Known runtime notes

- `python -m ruff check .` and `python -m ruff format .` are the correct lint/format commands on Replit (packages installed via pip; uv sync fails on nix store).
- `python -m pytest tests/ -q` is the correct test command on Replit.
- Workflows are configured to use `python -m tcbot` and `python -m pytest tests/ -v` (no `uv run`).
- Flask keep-alive runs on PORT=8080 (mapped by Replit to external port 80).
- Bot fails fast when BOT_TOKEN/MONGODB_URI/OWNER_ID are not set. Secrets must be in Replit Secrets.
- Communication with user: Indonesian. Code/docs/commits: English.
- Agent-rule docs are being re-audited for internal consistency; session 15 fixed a contradiction in `.agents/CLAUDE.md` where one section still allowed emojis even though the canonical bot voice forbids pictograph emoji and text emoticons.
- Session 15 verification baseline passed end to end: `uv sync --extra test`, editable reinstall, import check, startup check, Ruff, runtime start, full pytest, and stale-rule grep audit.
- Session 16 re-verified runtime after a transient local bind conflict on port 5000: `PORT=5001 uv run python -m tcbot` started cleanly, so the issue was environmental rather than code-related.
- Session 17 removed the remaining em dash and en dash characters from authored Markdown so the repository docs now match the no-dash typography rule more closely.
- Session 17 verification passed after rerunning startup and runtime checks sequentially on isolated ports (`5006` and `5007`), avoiding the self-induced bot-instance conflict from the earlier parallel check attempt.
- Session 18 improved docs coverage by adding Mermaid diagrams to `README.md` and `PLAN.md`, covering the top-level architecture summary plus startup and request-processing flows.
- Session 18 verification passed end to end with isolated runtime ports `5008` and `5009`; docs audit also confirmed both top-level files now contain Mermaid blocks.
- Session 19 is improving internal agent documentation coverage: `.agents/WORKFLOW.md` now has a Mermaid flowchart for the validation order described in the file.
- Session 19 verification passed end to end with isolated runtime ports `5010` and `5011`; docs audit confirmed `.agents/WORKFLOW.md` now contains a Mermaid block.
- Session 20 is extending Mermaid coverage into deployment docs: `replit.md` now includes a compact flowchart for hosted startup prerequisites, polling, and health-check exposure.
- Session 20 verification passed end to end with isolated runtime ports `5012` and `5013`; docs audit confirmed `replit.md` now contains a Mermaid block.
- Session 21 is extending Mermaid coverage into agent runtime docs: `.agents/REPLIT.md` now has a startup-log flowchart for Replit checks.
- Session 21 verification passed end to end with isolated runtime ports `5014` and `5015`; docs audit confirmed `.agents/REPLIT.md` now contains a Mermaid block.
- Session 22 is correcting setup-document drift: `docs/setup.md` now matches the actual Docker runtime command from `Dockerfile` and no longer repeats the hosted start command.
- Session 22 verification passed end to end with isolated runtime ports `5016` and `5017`; docs audit confirmed `docs/setup.md` now matches the runtime command in `Dockerfile`.
- Session 23 tightened repo hygiene after the mandatory editable install step: `.gitignore` now ignores generated `*.egg-info/` metadata, so `uv pip install -e .` no longer leaves commit noise in the working tree.
- Session 23 verification passed end to end with isolated runtime ports `5022` and `5023`; docs audit reconfirmed `docs/setup.md` and `Dockerfile` stay in sync.
- Session 24 removed tracked workflow log artifacts from the repository root: `check.log` and `format.log` are gone, and `.gitignore` now ignores those exact filenames so auto-fix runs stay quiet.
- Session 24 verification passed end to end with isolated runtime ports `5026` and `5027`; repository-status audit confirmed the tracked log files are removed and no new untracked log files appeared after validation.

## Blockers

None.
