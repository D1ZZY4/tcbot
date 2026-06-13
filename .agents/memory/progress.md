---
name: Progress tracker
description: Item-by-item status of the improvement plan. Updated at each commit checkpoint.
---

# TCF Bot - Progress

**Last updated:** 2026-06-12 (session 77)

## Verification baseline

| Check | Result |
|---|---|
| `uv sync` | PASS |
| `uv pip install -e .` | PASS |
| `uv run python -c "import tcbot; print('import OK')"` | PASS (session 43: re-verified after `__main__.py` edit) |
| `uv run python -m tcbot --help 2>&1 || uv run python -c "from tcbot import *; print('startup OK')"` | PASS by runtime evidence: bot started cleanly, connected MongoDB, ensured indexes, initialised, 75 handlers registered, polling active |
| `uv run ruff format .` | PASS (72 files; includes redis_client.py, scheduler.py) |
| `uv run ruff check --fix .` | PASS (All checks passed) |
| asyncio task-GC fix isolated test (session 43) | PASS: task registered on schedule, discarded on completion, report coroutine ran |
| `uv run python -m tcbot` | PASS by runtime evidence: MongoDB connected, indexes ensured, scheduler started, bot polling active |
| annotation AST audit | PASS: 0 non-dunder function parameters missing type annotations (was 31 before session 34) |
| docs audit (session 36) | PASS: all 20+ docs files verified accurate; 0 code quality violations; 0 stale Mermaid diagrams |
| docs audit (session 74) | PASS: mapping.md top-level layout completed; 3 new Mermaid diagrams added (ownership boundaries, ban flow, mute flow, appeal flow); all code files audited clean |

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
| Ratelimiter constants: all 16 modules | housekeeping | `_RL_*` constants extracted to all 16 modules with `@ratelimiter` decorators; every bare `limit=`/`period=` literal in `tcbot/modules/` replaced | 2026-06-06 (s30) |
| Full doc audit | housekeeping | Updated replies.py table in helper.md (+9 missing constants). All 10 developer docs verified accurate. | 2026-06-06 (s29) |
| Parameter type annotation coverage | housekeeping | Fixed 31 unannotated parameters across 13 files; AST audit now reports 0 missing in all non-dunder functions | 2026-06-07 (s34) |
| BaseFilter import location discovery | housekeeping | BaseFilter is in telegram.ext.filters, not telegram.ext; corrected imports across 6 workflow files after ImportError at startup | 2026-06-07 (s34) |
| Return type annotation coverage | housekeeping | Fixed 12 functions missing return types across 9 files (7 DB accessors, __main__, extraction.py); AST audit now reports 0 missing | 2026-06-07 (s35) |
| TC (TYPE_CHECKING) import refactor | code quality | Added TC ruleset to pyproject.toml; fixed 151 violations across 50 files with --unsafe-fixes; stdlib and motor imports moved to TYPE_CHECKING blocks; bot startup clean | 2026-06-11 (s39) |
| PERF + PIE rulesets | code quality | Added PERF and PIE to pyproject.toml select; fixed 4 PERF401 (for-loop→comprehension/extend in check_flow, stats_flow) and 1 PIE810 (startswith tuple in __init__); ruff 71 files clean | 2026-06-11 (s39) |
| TRY400 + TRY401 rulesets | code quality | Added TRY400+TRY401 to pyproject.toml; 15 files: log.error→log.exception in except blocks; removed redundant exc args; auto-fixed 14 unused exc vars to bare except Exception: | 2026-06-11 (s39) |
| ANN003 kwargs annotation | code quality | Annotated **kwargs: Any in safe_edit/safe_edit_cb (parse_editmsg.py) | 2026-06-11 (s39) |
| PLE + PLC rulesets | code quality | Added PLE+PLC to pyproject.toml select; PLE0604 noqa on __all__ spread; PLC0415 noqa on 3 intentional lazy imports (dns.resolver, ban_info, error_reporter); PLR intentionally not added | 2026-06-11 (s42) |
| Dangling asyncio error-report task fix | P2 (correctness) | `__main__.py` Layer 3 asyncio handler created `lp.create_task(...)` without a strong ref; could be GC'd before running and drop the report. Added module-level `_asyncio_report_tasks` set + `discard` done-callback; verified in isolation. RUF006 missed it (task via `lp` parameter) | 2026-06-11 (s43) |
| Memory drift reconciliation | docs | context.md/progress.md were stale at s41 while CHANGELOG/decisions/pyproject were at s42; brought both current and corrected file-count note 71 -> 70 | 2026-06-11 (s43) |
| python-code-quality skill doc sync | docs | SKILL.md + REFERENCE.md embedded pyproject.toml snapshot was stale (5-group ruff select, ruff in [project] deps, 4 stale Migrate comments, false "not a full strict style suite" line); synced to actual 22-group config matching .agents/RUFF.md | 2026-06-11 (s44) |
| `pyproject.toml` setuptools package discovery fix | infra | Added `[tool.setuptools.packages.find] include = ["tcbot*"]` to prevent `attached_assets/` from being discovered as a second top-level package during `uv pip install -e .`; added `attached_assets/` to ruff exclude | 2026-06-11 (s45) |
| Bug #9: ConversationHandler TIMEOUT silent end | P2 (UX/correctness) | All 3 ConversationHandlers (ban_flow, reason_flow, appeal_flow) had `conversation_timeout` but no TIMEOUT state. PTB `_trigger_timeout` is called proactively by scheduler; without TIMEOUT handlers conversation silently ends with no notification. Fixed in all 3: ban_flow (`TypeHandler(Update, on_proof_timeout)`); reason_flow (inner `_on_timeout` handler); appeal_flow (`BuildAppeal._on_timeout` method + `_MSG_TIMEOUT`). | 2026-06-12 (s55) |
| Bug #10: connected_flow spurious disconnect log | P2 (correctness) | `on_bot_added` gather: `was_connected` could be BaseException (truthy) on DB error → false "bot removed" log. Added `return_exceptions=True` and `isinstance` guard with `was_connected = False` fallback. | 2026-06-12 (s56) |
| Bug #11: unban_flow fan-out crash | P1 (correctness) | `execute_unban`: `groups` could be BaseException → `for grp in groups` TypeError. Added `return_exceptions=True` and `groups = []` fallback. | 2026-06-12 (s56) |
| Bug #12: ban_flow fan-out crash | P1 (correctness) | `_execute_ban`: same pattern as Bug #11 in ban enforcement path. Added `return_exceptions=True` and `groups = []` fallback. | 2026-06-12 (s56) |
| Bug #13: appeal_flow review ban.get() AttributeError | P1 (correctness) | `on_review_decision`: `ban` could be BaseException (truthy) → `if not ban:` False → `ban.get("is_active")` AttributeError. Added `return_exceptions=True`, `isinstance` guard, and `return` on DB failure. | 2026-06-12 (s56) |
| Bug #14: appeal_flow approve branch crash | P1 (correctness) | `on_review_decision` approve: `groups`/`target_fname` could be BaseException → fan-out crash / string crash. Added `return_exceptions=True` and individual fallbacks. | 2026-06-12 (s56) |
| Bug #15: promote_flow pure-side-effect gathers | P2 (correctness) | 3 DB-write gathers in `promote_flow.py` lacked `return_exceptions=True`. Added per project convention. | 2026-06-12 (s56) |
| Bug #16: admins on_promo_decision req subscript | P1 (correctness) | `req` could be BaseException → `if not req:` False → `req["target_id"]` crash. Added `return_exceptions=True`, `isinstance` guard, and `return` on failure. | 2026-06-12 (s56) |
| Bug #17: admins on_demote_confirm tuple unpack | P1 (correctness) | `(target_fname, target_uname) = BaseException` TypeError. Refactored to unpack `mention_data` separately with `isinstance` guard. | 2026-06-12 (s56) |
| Bug #18: admins on_promote_role_select Promote.execute crash | P1 (correctness) | `target_fname`/`current_role` could be BaseException passed directly to `Promote.execute()`. Added `return_exceptions=True` and per-field fallbacks. | 2026-06-12 (s56) |
| Bug #19: greeting.py CRITICAL false federation ban | P0 (critical) | `ban` could be BaseException (truthy on DB error) → `bot.ban_chat_member()` called on innocent user. Added `return_exceptions=True`, `isinstance` guard, `ban = None`, and `log.error`. | 2026-06-12 (s56) |
| Bug #20: warns_db gather result access | P2 (correctness) | `clear_warns` and `remove_last_warn` gathers lacked `return_exceptions=True`. DB result accessed without BaseException guard. Fixed both. | 2026-06-12 (s56) |
| Bug #5: proof_flow reason HTML injection | P1 (correctness) | `step_prompt`/`noted_prompt` embedded `reason`/`inline_reason` in `<b>` tags without `esc()`. Fixed: added esc import and wrapped both strings. Any `<>&` in user-typed reason would break HTML parse mode. | 2026-06-12 (s50) |
| Bug #6: cmd_promote_request always rejected | P1 (correctness) | `identity.classify(user.id, user.id, ...)` always returns `Identity("self")` in self-submission flows, causing every request to be rejected. Removed identity check; replaced with parallel `get_effective_role` + `get_request` guard. | 2026-06-12 (s50) |
| Global link preview disable | UX | Added `Defaults(link_preview_options=LinkPreviewOptions(is_disabled=True))` to `ApplicationBuilder` chain in `__main__.py`; all 205+ message send/edit/reply calls now suppress link-preview cards with one change. | 2026-06-12 (s51) |
| Bug #35: ban_flow album user_data not cleared after flush | P2 (correctness) | `_flush_album` did not clear `ctx.user_data` ban keys after executing. Second album could re-fire `_execute_ban` for same target. Added `_album_userdata` reference dict and post-flush cleanup loop over `_BAN_USER_DATA_KEYS`. | 2026-06-12 (s58) |
| Bug #36: ban_flow album meta missing required keys | P2 (correctness) | `_flush_album` only checked `if not msgs or not meta` but not content. If conversation interrupted before keys set, `target_id=None` would corrupt ban record. Added guard for `ban_target_id` and `ban_admin_id`. | 2026-06-12 (s58) |
| Bug #37: anonymous admin silent rejection in all auth decorators | P2 (correctness) | GroupAnonymousBot (id 1087968824) treated as regular user → silent fail with generic "no rank" message. Added `_is_anon_admin()` + `_ERR_ANON_ADMIN` constant; all 4 decorators now check first and reply clearly. | 2026-06-12 (s58) |
| Bug #40: stats_flow.py main+staff_roster gathers no return_exceptions | P2 (correctness) | `Stats.main()` 7-coro gather and `Stats.staff_roster()` 4-coro gather both lacked `return_exceptions=True`. Any DB error crashed the entire stats command. Added `return_exceptions=True` + individual BaseException fallbacks (counts→0, lists→[], owner→None). | 2026-06-12 (s59) |
| Bug #41: ban_info.py build_ban_detail gather no return_exceptions | P2 (correctness) | Parallel gather for banned-user + admin mention data lacked `return_exceptions=True`. TypeError on unpack if either raised. Refactored to r_target/r_admin pattern with per-result fallbacks. | 2026-06-12 (s59) |
| Bug #42: warnings.py cmd_warn gather no return_exceptions | P2 (correctness) | `gather(identity.classify, resolve_and_check)` lacked `return_exceptions=True`. Crash on tuple unpack if either raised, leaving ConversationHandler open. Refactored with individual isinstance guards. | 2026-06-12 (s59) |
| groups.py _toggle serial awaits | perf | Cache-hit: q.answer+safe_edit sequential → gathered. Cache-miss: q.answer+active_groups sequential → gathered with groups=[] fallback. | 2026-06-12 (s59) |
| Bug #39: checking.py q.answer() after DB call | P2 (correctness/UX) | `on_checkme_detail` and `on_checkme_back` awaited `get_ban()` before `q.answer()`. Fixed: `asyncio.gather(q.answer(), get_ban(), return_exceptions=True)` + edit_message on error (not show_alert, since query already answered). Also: all 8 `on_check_*` handlers had sequential `q.answer()` + `Check.method()` -- refactored to gather with `return_exceptions=True` and isinstance guard. | 2026-06-12 (s59) |
| Bug #38: chat migration handler absent | P2 (correctness) | No handler for migrate_to/migrate_from. When basic group migrates to supergroup, old chat_id in DB causes ban enforcement and group ops to silently fail. Added `migrate_group()` in groups_db.py + `on_chat_migration` handler in greeting.py with `filters.StatusUpdate.MIGRATE`. | 2026-06-12 (s58) |
| Bug #43: banning/muting/kicking ConversationHandler entry gathers no return_exceptions | P2 (correctness) | `cmd_ban_start`, `cmd_mute`, `cmd_kick` all used `asyncio.gather(identity.classify, resolve_and_check)` without `return_exceptions=True`. DB failure would propagate out of the entry point, leaving the ConversationHandler open. Identical to Bug #42 (warnings.py). Refactored all three with individual isinstance guards + ConversationHandler.END on failure. | 2026-06-12 (s60) |
| Bug #46: users_roles.py auth gather no return_exceptions | P2 (correctness) | `is_staff`, `can_act_on`, `get_effective_role`: all three had `asyncio.gather` without `return_exceptions=True`. Any DB timeout during an auth check would crash the command handler. Added `return_exceptions=True` + conservative-deny fallbacks (False/None). Added `import logging` + `log`. | 2026-06-12 (s62) |
| Bug #46p2: promote_flow.py request_admin gather no return_exceptions | P2 (correctness) | `asyncio.gather(enqueue, get_owner_id)` lacked `return_exceptions=True`. If enqueue raised, request_id was undefined. If get_owner_id raised, silent skip. Fixed with individual fallbacks. | 2026-06-12 (s62) |
| Bug #47: decorators.py resolve_and_check gather no return_exceptions | P2 (correctness) | `asyncio.gather(get_effective_role x2)` lacked `return_exceptions=True`. Fixed with None fallbacks (conservative deny). | 2026-06-12 (s62) |
| check_flow.py bans_list/warns_by_group/appeals_list/_per_chat_event_list serial awaits | perf | Main DB fetch + _name(target_id) were sequential. Now gathered in parallel for all 5 check drill-down list views. BaseException fallbacks added for both results. | 2026-06-12 (s62) |
| appeal_flow.py on_decision approve log sends serial | perf | _update_or_send_log + send_message(unban log) to same channel were sequential with no data dependency. Combined into asyncio.gather. | 2026-06-12 (s62) |
| Em-dash/en-dash full cleanup | docs | Python script replaced all remaining U+2014/U+2013 in 100 markdown files. Zero remaining anywhere in project. | 2026-06-12 (s62) |
| Session 65 - extraction.py sender_chat + Telegram skip | correctness | Added `_TELEGRAM_USER_ID` skip in reply path; added `sender_chat` branch so linked-channel auto-forwards resolve to channel entity | 2026-06-12 (s65) |
| Session 65 - identity.py anon_admin kind | correctness | Added `"anon_admin"` to `IdentityKind`, `classify()` detection, and all 11 per-action refusal tables | 2026-06-12 (s65) |
| Session 65 - appeal_flow None guards | correctness | Guards for `update.effective_message/user/callback_query` and `ctx.user_data` throughout; non-text input returns `WAITING_APPEAL` | 2026-06-12 (s65) |
| Session 65 - ban_flow None guards | correctness | Guards for `update.effective_message`, `update.callback_query`, `ctx.user_data` in cancel/timeout handlers | 2026-06-12 (s65) |
| Session 65 - reason_flow None guards | correctness | Guards for `msg is None or msg.text is None`, `q is None` in all step handlers | 2026-06-12 (s65) |
| Session 65 - check_flow "Regular user" label | voice | Role label fallback `None` -> `"Regular user"` in main profile view | 2026-06-12 (s65) |
| Session 65 - stats_flow "No staff assigned" | voice | `"- None assigned"` -> `"- No staff assigned"` in staff roster empty state | 2026-06-12 (s65) |
| Session 65 - mongos.py 5 new indexes | performance | `federated_groups.is_active`, `member_cache.last_updated`, `kicks/mutes/bans.chat_id` indexes added | 2026-06-12 (s65) |
| Session 65 - broadcasting/admins gather order | performance | Reordered gather calls to prioritize user-facing edits before log sends | 2026-06-12 (s65) |
| Session 67 - Bug #50: appeal_flow instruction_text HTML injection | correctness | `community_name` unescaped in HTML reply; fixed with `esc()` | 2026-06-12 (s67) |
| Session 67 - Bug #51/52/53/54: gather results not checked (4 locations) | correctness | `connecting.py`, `connected_flow.py`, `unban_flow.py`, `admins.cmd_transfer` - silent failure on log/reply send. Added `log.error`/`log.debug` checks. | 2026-06-12 (s67) |
| Session 67 - Bug #55/56 (HIGH): promo_decision DB writes not checked | correctness | approve: `add_admin` fail = approved in queue but not promoted. reject: `resolve` fail = request stays pending. Both now log.error. | 2026-06-12 (s67) |
| Session 67 - Bug #57: proof_line() unescaped HTML | correctness | `proof_desc` embedded raw in HTML messages in 3 flows (kicking, muting, warning). Fixed with `esc()` in `formatter.py` at source. | 2026-06-12 (s67) |
| Session 67 - DB perf: estimated_document_count | performance | `total_users()` and `admin_count()` switched to `estimated_document_count()`; `ensure_initial_owner` left exact. | 2026-06-12 (s67) |
| Session 68 - Full audit verification pass | audit | All critical files re-read; no new bugs found; bot running cleanly (75 handlers, MongoDB connected, 70 files ruff-clean) | 2026-06-12 (s68) |
| Session 69 - New task file v4 (1781284726574) full read + DRY confirm | audit | Read all 1097 lines of new task file; all agent rules re-read; comprehensive targeted audit: identity.py (no emoji/emoticons), callback q.answer() patterns (all correct via gather), all sequential awaits (verified data-dependent), symlinks (.kilo/.trae/.claude), em-dash sweep (clean). No new bugs found. Audit remains DRY. Full 7-step verification PASS. | 2026-06-12 (s69) |
| Session 70 - Bug #63: em-dash in admins.py (2 locations) | correctness | Em-dashes in block comments replaced with ASCII hyphens. | 2026-06-12 (s70) |
| Session 70 - Bug #64: stats.py on_stats_search_back sequential awaits | performance | q.answer()+safe_edit_cb() sequential despite synchronous data source. Fixed with gather. | 2026-06-12 (s70) |
| Session 70 - Bug #65: appeal_flow._on_cancel sequential awaits | performance | q.answer()+q.edit_message_text() sequential. Fixed with gather+return_exceptions. | 2026-06-12 (s70) |
| Session 70 - Bug #66/#66b: connected_flow on_join_decision error paths | performance | edit_message_reply_markup+reply_text sequential (2 locations). Fixed with gather. | 2026-06-12 (s70) |
| Session 70 - Bug #67: connected_flow add_pending+edit_message_text | performance | DB write+TG call sequential. Fixed with gather. | 2026-06-12 (s70) |
| Session 70 - docs/performance.md v4 targets | documentation | Updated all performance targets to mandatory v4 values (table added). | 2026-06-12 (s70) |
| Session 70 - Ultra-comprehensive audit pass | audit | 70 files, 14077 lines, 0 em-dash, 0 curly-quotes, 0 bare-except. Ruff clean. All consecutive-await pairs verified. DB+TG sequential scan: 0 remaining. q.answer()-in-gather scan: all correct. | 2026-06-12 (s70) |
| Session 71 - Bug #68: reason_flow _on_skip_reason gather no return_exceptions | correctness | `asyncio.gather(q.answer(), q.edit_message_text())` inside try/except but no `return_exceptions=True`. Refactored to standard pattern with isinstance check and log.debug. | 2026-06-12 (s71) |
| Session 71 - Bug #69: reason_flow _on_cancel gather no return_exceptions | correctness | Same pattern as #68 in `_on_cancel`. Refactored to standard pattern. | 2026-06-12 (s71) |
| Session 71 - Bug #70: disconnecting.py cmd_rmtc bare update.effective_user | correctness | `update.effective_user.id/.first_name` accessed directly inside asyncio.gather args without local var. Extracted `admin = update.effective_user` and `msg = update.effective_message` at function top. | 2026-06-12 (s71) |
| Session 71 - Bug #71: warnings.py cmd_warnlist bare update.effective_message | code quality | `update.effective_message.text` without local var. Extracted `msg = update.effective_message` for consistency. | 2026-06-12 (s71) |
| Session 71 - Explorer-assisted audit | audit | Full modules/ + database/ explored by subagent. All 4 findings fixed. Ruff 70 files clean, bot running (75 handlers). | 2026-06-12 (s71) |
| Session 73 - uv lock --upgrade | maintenance | All 25 packages at latest compatible (PTB 22.8, Motor 3.7.1, PyMongo 4.17.0). No version changes from prior lock. | 2026-06-12 (s73) |
| Session 73 - Bug #81: error_reporter.py `[:100]` | code quality | Hardcoded slice in `_condensed_tb` → `_MAX_LINE_CONTENT = 100`. | 2026-06-12 (s73) |
| Session 73 - Bug #82: error_reporter.py `"━" * 30` | code quality | Hardcoded separator length → `_REPORT_SEP_LEN = 30`. | 2026-06-12 (s73) |
| Session 73 - Bug #83: identity.py `community_name` unescaped | HTML safety | `staff_notice` interpolates `community_name` raw into HTML string sent with parse_mode="HTML". Wrapped with `esc()`. | 2026-06-12 (s73) |
| Session 73 - Bug #84: checking.py `community_name` unescaped | HTML safety | `_ban_summary` interpolates `cfg.community_name` raw into HTML string returned for parse_mode="HTML" caller. Wrapped with `esc()`. | 2026-06-12 (s73) |
| Session 73 - Bug #85: check_flow.py `[:60]` hardcoded | code quality | Ban list reason truncation → `_BAN_LIST_REASON_LEN = 60`. Intentionally different from `_REASON_PREVIEW_LEN = 80`. | 2026-06-12 (s73) |
| Session 73 - Bug #86: check_flow.py `3` buttons-per-row × 2 | code quality | Hardcoded `3` in `Check.bans` and `Check.appeals` → `_BTNS_PER_ROW = 3`. | 2026-06-12 (s73) |
| Session 73 - Bug #87: stats_flow.py `3` buttons-per-row × 2 | code quality | Hardcoded `3` in `_item_list_kb` and `Stats._search_results_kb` → `_BTNS_PER_ROW = 3`. | 2026-06-12 (s73) |
| Session 73 - Bug #88: appeal_flow.py `log_channel` unescaped | HTML safety | `AppealConfig.instruction_text` sends `self.log_channel` raw in HTML string. Wrapped with `esc()`. | 2026-06-12 (s73) |
| Session 73 - Bug #89: __main__.py handler group literals | code quality | `group=-1` and `group=10` → `_HANDLER_GROUP_RATE_LIMITER = -1` and `_HANDLER_GROUP_CACHE = 10`. | 2026-06-12 (s73) |
| Session 73 - Sub-agent audit waves A-F | audit | 6 sub-agent waves covering all modules, flows, utils, __main__. 7/9 bugs were HTML safety or named-constant fixes; 2 were esc(). Ruff 70 files clean, bot running (75 handlers, MongoDB, polling). | 2026-06-12 (s73) |
| Session 75 - Bug #90-99: cfg.community_name HTML escaping (comprehensive sweep) | HTML safety | 10 modules had `cfg.community_name` interpolated raw into HTML strings sent with `parse_mode="HTML"`: `about.py` (×4), `additional.py` (×1), `start.py` (×2), `help.py` (×1), `groups.py` (×2), `broadcasting.py` (×2), `connecting.py` (×3), `disconnecting.py` (×2), `privacy.py` (×5). Root fix: `LogBuilder.__init__` now calls `esc(str(title))` so all 20+ log titles are safe. Each module extracted `_CNAME = esc(cfg.community_name)` at module level. Ruff 70 files clean, bot running (75 handlers). | 2026-06-12 (s75) |
| Session 76 - Bug #100: cache.py fire-and-forget tasks RUF006 | correctness | Redis bg tasks missing strong references; could be GC'd before completing. Added `_redis_bg_tasks` set with discard callbacks. | 2026-06-12 (s76) |
| Session 80 - Bug #109: scheduler.py 3 em-dash in docstring/comments | style | Em-dash chars in docstring "same task -- requirement..." and comments "Background task --" and "Schedule did not exist --". Replaced with parens/colons. | 2026-06-12 (s80) |
| Session 80 - Bug #110: appeal_flow.py hardcoded "12" in _ERR_REVIEW_LOCKED | DRY | "12 hours" literal in error string despite _LOCK_WINDOW = timedelta(hours=12) existing. Added _LOCK_HOURS: int = 12 constant, used it in both _LOCK_WINDOW and _ERR_REVIEW_LOCKED. | 2026-06-12 (s80) |
| Session 80 - Mermaid fix: PLAN.md startup flowchart | docs | get_handlers/add_handler now shown before run_polling; post_init shown as pre-polling step triggered by run_polling. | 2026-06-12 (s80) |
| Session 80 - Mermaid fix: docs/mapping.md startup sequenceDiagram | docs | Corrected order: get_handlers before run_polling; post_init inside run_polling; added Redis/APScheduler/error_reporter steps. | 2026-06-12 (s80) |
| Session 80 - Bug #111: greeting.py unguarded welcome reply | robustness | await msg.reply_text welcome message unguarded; if bot muted every join generates error report. Wrapped try/except log.debug. | 2026-06-12 (s80) |
| Session 80 - Bug #112: muting_flow.py unguarded fallback reply | robustness | fallback await msg.reply_text(summary) unguarded; wrapped try/except log.debug. | 2026-06-12 (s80) |
| Session 80 - Bug #113: kicking_flow.py unguarded error reply | robustness | error notification reply in except block unguarded; wrapped try/except log.debug. | 2026-06-12 (s80) |
| Session 80 - Bug #114: warning_flow.py auto-ban notification replies unguarded | robustness | Two reply_text in auto-ban branch (success + failure notices) unguarded; wrapped both try/except log.debug. | 2026-06-12 (s80) |
| Session 80 - Em-dash fixes: replit.md (5), CHANGELOG.md (4), .agents/memory/ files | style | All em-dash in project docs and memory files eliminated. | 2026-06-12 (s80) |
| Session 80 - Ruff clean (72 files), bot running | audit | All session 80 fixes done; ruff check passes; bot restarted with MongoDB+Redis+APScheduler+75 handlers. | 2026-06-12 (s80) |
| Session 81 - Bug #115: unban_flow.py deactivate_ban result silently discarded | correctness | deactivate_ban gather result captured in _ not checked; if DB write fails, user is unbanned from all groups but ban record stays active (state inconsistency). Renamed to deactivate_r + log.error check. | 2026-06-12 (s81) |
| Session 81 - Bug #116: unban_flow.py no-active-ban early-return reply unguarded | robustness | await msg.reply_text() in no-ban early-return path unguarded; wrapped try/except log.debug. | 2026-06-12 (s81) |
| Session 81 - Bug #117: reason_flow.py _end_conv cancel-via-command reply unguarded | robustness | _end_conv (fired on command-during-flow) reply_text unguarded; added if guard + try/except log.debug. | 2026-06-12 (s81) |
| Session 81 - Bug #118: reason_flow.py _on_timeout reply unguarded | robustness | _on_timeout reply_text unguarded; added try/except log.debug. | 2026-06-12 (s81) |
| Session 81 - Bug #119: reason_flow.py _on_reason_text else-branch fallback reply unguarded | robustness | fallback reply when no prompt_id/chat exists unguarded; added try/except log.debug. | 2026-06-12 (s81) |
| Session 81 - Bug #120: ban_flow.py on_proof_unexpected reply unguarded | robustness | on_proof_unexpected reply_text unguarded; added try/except log.debug. | 2026-06-12 (s81) |
| Session 81 - Bug #121: ban_flow.py on_proof_timeout reply unguarded | robustness | on_proof_timeout reply_text unguarded; added try/except log.debug. | 2026-06-12 (s81) |
| Session 81 - Bug #122: stats.py cmd_stats reply unguarded | robustness | cmd_stats reply_text unguarded; command callable from muted group; wrapped try/except log.debug. | 2026-06-12 (s81) |
| Session 81 - Bug #123: stats.py on_bans_search_input edit_message_text unguarded | robustness | search result edit unguarded; if panel message deleted before search completes, propagates to error handler. Wrapped try/except log.debug. | 2026-06-12 (s81) |
| Session 81 - Bug #124: appeal_flow.py _end fallback reply unguarded | robustness | _end reply_text unguarded; wrapped try/except log.debug. | 2026-06-12 (s81) |
| Session 81 - Bug #125: appeal_flow.py _on_timeout reply unguarded | robustness | _on_timeout reply_text unguarded; wrapped try/except log.debug. | 2026-06-12 (s81) |
| Session 81 - Bug #126: maintenance.py cmd_leaveall no-groups early-return reply unguarded | robustness | wrapped try/except log.debug. | 2026-06-12 (s81) |
| Session 81 - Bug #127: maintenance.py cmd_leaveall status=await reply_text NameError if raises | correctness | status assignment unguarded - if reply fails status undefined, status.edit_text() crashes with NameError. Wrapped try/except; status falls back to None; edit gated on status is not None. CRITICAL. | 2026-06-12 (s81) |
| Session 81 - Bug #128: maintenance.py cmd_cleanup final reply unguarded | robustness | wrapped try/except log.debug. | 2026-06-12 (s81) |
| Session 81 - Bug #129-133: appeal_flow.py on_decision 5 q.edit_message_text calls unguarded | robustness | not-authorized, ban-not-found (x2), already-resolved, review-locked edit calls unguarded. Wrapped try/except log.debug. | 2026-06-12 (s81) |
| Session 81 - Bug #134: groups.py cmd_tcfgroups 2 reply_text unguarded + missing log | robustness | Both reply_text calls unguarded; missing import logging and log = getLogger. Added logger; wrapped try/except log.debug. | 2026-06-12 (s81) |
| Session 82 - Bug #136: appeal_flow.py _start instr=await NameError CRITICAL | correctness | instr=await msg.reply_text() unguarded; instr.message_id crashes if reply fails. Wrapped try/except; message_id only stored on success. | 2026-06-12 (s82) |
| Session 82 - Bug #137: appeal_flow.py _on_message 2 unguarded reply_text | robustness | ERR_SESSION_EXPIRED and ERR_INVALID_LOG replies unguarded. Wrapped try/except log.debug. | 2026-06-12 (s82) |
| Session 82 - Bug #138-142: decorators.py 4 auth decorators + resolve_and_check 8 unguarded | robustness | owner_only/staff_only/mod_only/basic_mod_only anon+refusal replies + resolve_and_check rank/outrank replies all unguarded. All wrapped try/except log.debug. | 2026-06-12 (s82) |
| Session 82 - Bug #143-144: muting.py cmd_mute prompt=await CRITICAL (x2) | correctness | Both inline-reason and fallback prompt assignment unguarded; prompt.message_id crashes. Wrapped try/except; mute_prompt_id only stored on success. | 2026-06-12 (s82) |
| Session 82 - Bug #145-149: muting.py cmd_mute/cmd_unmute 5 unguarded | robustness | no-target, refusal, no-target, refusal, notice replies all unguarded. All wrapped try/except log.debug. | 2026-06-12 (s82) |
| Session 82 - Bug #150: start.py cmd_start + _show_groups 5 unguarded | robustness | group reply, about reply, PM welcome, no-groups edit, list edit all unguarded. All wrapped try/except log.debug. | 2026-06-12 (s82) |
| Session 82 - Bug #151: help.py cmd_help 3 unguarded | robustness | module, not-found, index replies unguarded. All wrapped try/except log.debug. | 2026-06-12 (s82) |
| Session 82 - Bug #152: kicking.py cmd_kick 4 unguarded | robustness | no-target, refusal, proof-prompt, reason-prompt unguarded. All wrapped try/except log.debug. | 2026-06-12 (s82) |
| Session 82 - Bug #153-160: admins.py 22 unguarded across 8 functions | robustness | cmd_promote(6), on_promote_role_btn(1), cmd_demote(6), on_demote_confirm(5), cmd_transfer(2), cmd_promote_request(3), cmd_promote_list(2), on_promo_decision(3) all unguarded. All wrapped try/except log.debug. | 2026-06-12 (s82) |
| Session 82 - Bug #161: banning.py cmd_ban_start 4 unguarded incl. CRITICAL | correctness | no-target, no-reason, refusal unguarded + prompt=await msg.reply_text() CRITICAL (prompt.message_id crashes). All fixed; message_id only stored on success. | 2026-06-12 (s82) |
| Session 82 - Bug #162: broadcasting.py cmd_broadcast CRITICAL + 3 unguarded | correctness | status=await msg.reply_text() CRITICAL - status.edit_text() in subsequent asyncio.gather raises UnboundLocalError before return_exceptions can catch. Fixed: status=None fallback; conditional coroutine. Also 3 unguarded replies. | 2026-06-12 (s82) |
| Session 82 - Bug #163: connecting.py cmd_tctc 6 unguarded | robustness | group-only, role-verify, admin-required, already-connected, pending-request, perms-required. All wrapped try/except log.debug. | 2026-06-12 (s82) |
| Session 82 - Bug #164: disconnecting.py cmd_tcleave/cmd_rmtc 6 unguarded | robustness | group-only, not-connected, role-verify, not-authorized, usage, not-found. All wrapped try/except log.debug. | 2026-06-12 (s82) |
| Session 82 - Bug #165: connected_flow.py on_join_decision 2 unguarded edits | robustness | perms-verify and already-connected q.edit_message_text unguarded. Both wrapped try/except log.debug. | 2026-06-12 (s82) |
| Session 79 - Bug #107: checking.py _ban_summary nested tuple unpack gather no return_exceptions | correctness | Nested tuple unpack ((_, user_uname), (admin_fname_cached, admin_uname)) from gather - DB failure cannot be destructured, crashes /checkme ban detail. Refactored to flat _user_r/_admin_r with isinstance guards. | 2026-06-12 (s79) |
| Session 79 - Bug #108: checking.py cmd_checkme gather no return_exceptions | correctness | 3-item gather (get_owner_id, get_effective_role, get_active_ban) without return_exceptions. Any DB failure crashes /checkme command. Added return_exceptions=True with None fallbacks. | 2026-06-12 (s79) |
| Session 79 - Ruff clean (72 files), bot running clean (75 handlers) | audit | All 2 bugs fixed, ruff check passes, bot restarted with MongoDB+Redis+APScheduler. | 2026-06-12 (s79) |
| Session 78 - Bug #101: check_flow.py Check.profile gather no return_exceptions | correctness | 9-coro gather with nested tuple unpack - any DB failure crashes entire /check profile. Refactored to flat intermediaries with individual isinstance fallbacks. | 2026-06-12 (s78) |
| Session 78 - Bug #102: check_flow.py Check.warns_in_group gather no return_exceptions | correctness | get_warns+get_group_titles gather without return_exceptions. Added fallbacks warns=[]/titles={}. | 2026-06-12 (s78) |
| Session 78 - Bug #103: check_flow.py _per_chat_event_list gather no return_exceptions | correctness | get_group_titles+get_first_names_batch gather without return_exceptions. Added empty-dict fallbacks. | 2026-06-12 (s78) |
| Session 78 - Bug #104: admins.py cmd_promote two gathers no return_exceptions | correctness | (1) extract_target tuple unpack crash on exception; (2) classify exception passed as ident to refuse_message -> AttributeError. Refactored both. | 2026-06-12 (s78) |
| Session 78 - Bug #105: admins.py cmd_demote two gathers no return_exceptions | correctness | Identical pattern to Bug #104 in cmd_demote. Fixed with same pattern. | 2026-06-12 (s78) |
| Session 78 - Bug #106: admins.py cmd_promote_request gather no return_exceptions | correctness | get_effective_role+get_request gather without return_exceptions. Added None fallbacks. | 2026-06-12 (s78) |
| Session 78 - Ruff clean (72 files), bot running clean (75 handlers) | audit | All 6 bugs fixed, ruff check passes, bot restarted with MongoDB+Redis+APScheduler. | 2026-06-12 (s78) |
| Session 83 - Bug #135a-c: banning/kicking/muting ConversationHandler invisible-state | correctness | try/except swallowed prompt send failure but still returned WAITING_PROOF/WAITING_REASON; user stuck in invisible conversation. All three now return ConversationHandler.END in except block. | 2026-06-12 (s83) |
| Session 83 - mongos.py asyncio.gather return_exceptions | correctness | ensure_indexes gather lacked return_exceptions=True. Fixed with per-result isinstance checks. | 2026-06-12 (s83) |
| Session 83 - cache.py cachetools TTLCache migration | correctness | LRU+TTL eviction now consistent across all caches; maxsize-aware eviction prevents unbounded growth. | 2026-06-12 (s83) |
| Session 83 - warnings.py notice-before-execute | correctness | Admin feedback sent before execute path to prevent silent hangs on slow DB. | 2026-06-12 (s83) |
| Session 84 - Bug #166: appeal_flow.py _start invisible-state | correctness | Instruction send wrapped in try/except but fell through to return WAITING_APPEAL; user stuck invisible. Added return ConversationHandler.END in except. | 2026-06-12 (s84) |
| Session 84 - Bug #167: promote_flow.py unguarded send_message + HTML escaping | robustness/HTML safety | _assign_admin and _assign_subrole send_message calls unguarded; cfg.community_name not escaped. Wrapped gather + return_exceptions; added esc(). | 2026-06-12 (s84) |
| Session 84 - Bug #168: reason_flow.py ConversationHandler invisible-state + 4 unguarded | correctness/robustness | _on_reason_text fell through to WAITING state on prompt fail; 4 unguarded reply_text wrapped. | 2026-06-12 (s84) |
| Session 84 - Bug #169: unban_flow.py None checks + 2 unguarded | correctness/robustness | Missing None guards for effective_message/user at entry; 2 reply_text in early-return paths wrapped. | 2026-06-12 (s84) |
| Session 84 - Bug #170: demote_flow.py unguarded send_message | robustness | execute() send_message calls unguarded; wrapped gather+return_exceptions. | 2026-06-12 (s84) |
| Session 84 - Bug #171: check_flow.py active_ban dict isinstance guard | correctness | Key access on active_ban without isinstance(active_ban, dict) guard; TypeError possible. Added guard. | 2026-06-12 (s84) |
| Session 84 - Bug #172: stats_flow.py int(q) overflow | correctness | Overly long search query produces ints too large for MongoDB int32/int64. Wrapped in try/except with fallback. | 2026-06-12 (s84) |
| Session 84 - Bug #173: database layer hardening (all 8 Motor helpers) | correctness/robustness | Exception handling on all Motor calls; return_exceptions on all gathers; cache invalidation in try/finally; None checks on query results; find_one_and_delete for atomic remove_last_warn. | 2026-06-12 (s84) |
| Session 84 - Ruff clean (72 files), bot running (MongoDB+Redis+APScheduler+28 indexes) | audit | All session 84 bugs fixed; ruff check passes; bot running clean. | 2026-06-12 (s84) |
| Session 84b - Bug #174: reason_flow.py _on_reason_text invisible-state | correctness | Both edit+reply branches could fail independently; fell through to return WAITING_PROOF with no prompt visible. Added prompt_sent flag; return ConversationHandler.END if neither succeeded. | 2026-06-12 (s84b) |
| Session 84b - Bug #175: reason_flow.py _on_reason_unexpected + _on_proof_unexpected unguarded | robustness | Two reply_text calls in type-rejection handlers unguarded; wrapped try/except log.debug. | 2026-06-12 (s84b) |
| Session 84b - error_reporter.py + dispatch.py full audit | audit | error_reporter.py all TG calls guarded; dispatch.py _slot wrapper handles all exceptions correctly; no bugs found. | 2026-06-12 (s84b) |
| Session 85 - GitHub workflow action versions (all 4 files) | correctness | checkout@v6/setup-python@v6/setup-uv@v7/upload-artifact@v7/github-script@v9 do not exist; updated to v4/v5/v4/v4/v7. | 2026-06-12 (s85) |
| Session 85 - codeql.yml dead matrix + placeholder step removed | cleanup | Removed 'actions' language matrix and unused placeholder manual-build step from codeql.yml. | 2026-06-12 (s85) |
| Session 85 - dependency-update.yml emoji removed | cleanup | Emoji in PR body title violates voice rules; replaced with plain text. | 2026-06-12 (s85) |
| Session 85 - Dockerfile missing project install | correctness | uv sync --no-install-project left tcbot package un-installed; added second uv sync after COPY tcbot/. | 2026-06-12 (s85) |
| Session 85 - docker-compose network isolation | security | MongoDB and Redis accessible on default bridge; added internal:true network so no external container can reach them. | 2026-06-12 (s85) |
| Session 85 - sequential awaits audit | audit | All 7 candidates verified: set_owner order-dependent, cmd_transfer order-dependent, others already gathered or depend. No performance bug found. | 2026-06-12 (s85) |
| Session 85b - admins.py inline string → constant | refactor | Two duplicate inline strings extracted to _ERR_CLASSIFY_FAILED constant. | 2026-06-12 (s85b) |
| Session 85b - ban_info.py Exception→BaseException | fix | Bug #176: isinstance(r_admin, Exception) → BaseException; CancelledError not caught = tuple-unpack crash. | 2026-06-12 (s85b) |
| Session 85b - warning_flow.py unguarded replies | fix | Bug #177: 4 unguarded reply_text in execute_unwarn/warnlist/resetwarns wrapped try/except. | 2026-06-12 (s85b) |
| Session 85b - muting_flow.py unguarded reply | fix | Bug #178: execute_unmute else-branch (no log channel) bare reply_text wrapped try/except. | 2026-06-12 (s85b) |
| Session 86-87 - Bugs #179-201 | correctness/robustness/docs | See CHANGELOG.md session 86-87 entries for full list | 2026-06-13 (s86-87) |
| Session 88 wave 1 - Bug #202: run-bot.yml uv sync --frozen | CI | Missing --frozen flag; added | 2026-06-13 (s88) |
| Session 88 wave 1 - Bug #203: run-bot.yml 10 missing env vars | CI | PORT/REDIS_URL/APPEAL_LOG_HANDLE/APPEAL_DISCUSSION_TOPIC/WARN_EXPIRY_DAYS/PROOF_TIMEOUT_SECONDS/APPEAL_TIMEOUT_SECONDS/ALBUM_DEBOUNCE_SECONDS/MODULES_LOAD/MODULES_NO_LOAD all missing | 2026-06-13 (s88) |
| Session 88 wave 1 - Bug #204: auto-fix.yml uv sync --frozen | CI | Missing --frozen flag; added | 2026-06-13 (s88) |
| Session 88 wave 1 - Bug #205: checking.py gather no return_exceptions | correctness | on_checkme_back gather was missing return_exceptions=True | 2026-06-13 (s88) |
| Session 88 wave 1 - Bug #206: admins.py on_demote_confirm target_role isinstance | correctness | target_role BaseException was truthy; skipped guard; called Demote.execute with exception | 2026-06-13 (s88) |
| Session 88 wave 2 - Bug #207: connected_flow.py gather arg None check | correctness | effective_message.reply_text() as gather arg without None check; AttributeError before return_exceptions fires | 2026-06-13 (s88) |
| Session 88 wave 2 - Bug #208: connected_flow.py q.message.message_id None check | correctness | q.message.message_id without guard; AttributeError in inline context | 2026-06-13 (s88) |
| Session 88 wave 2 - Bug #209: admins.py on_promo_decision q.message.text None check | correctness | q.message.text as gather arg without q.message guard; AttributeError bypasses return_exceptions (x2) | 2026-06-13 (s88) |
| Session 88 wave 2 - Bug #210: kicking_flow.py results[0] unban unchecked | correctness | unban_chat_member result after kick not checked; failure leaves user banned; added log.warning | 2026-06-13 (s88) |
| Session 88 wave 2 - Bug #211: mongos.py dead bans(chat_id) index | housekeeping | BanDoc has no chat_id field; index wasted slot/write overhead; removed | 2026-06-13 (s88) |
| Session 88 wave 2 - Perf: connected_flow.py cancel 2 gathers -> 1 | performance | Cancel action: 2 sequential gathers -> single 4-op gather | 2026-06-13 (s88) |
| Session 88 wave 2 - Ruff clean (72 files), 27/27 indexes, bot running | audit | All fixes verified; ruff clean; app restarted; MongoDB+Redis+APScheduler+27 indexes; polling active | 2026-06-13 (s88) |
| Session 89 wave 1 - Bug #212: identity.py _WARN_REFUSE missing other_bot+founder | correctness | other_bot: warn stored permanently with no semantic value; founder: not blocked by warn unlike all other actions | 2026-06-13 (s89) |
| Session 89 wave 1 - Bug #213: identity.py _UNMUTE_REFUSE missing other_bot | correctness | other_bot could be unmuted even though bots can't be muted | 2026-06-13 (s89) |
| Session 89 wave 1 - Bug #214: identity.py _DEMOTE_REFUSE missing other_bot | correctness | other_bot could be passed to demotion logic | 2026-06-13 (s89) |
| Session 89 wave 1 - Bug #215: disconnecting.py cmd_tcleave/cmd_rmtc gather results not captured | correctness | deactivate_group failure invisible; state inconsistency undetected | 2026-06-13 (s89) |
| Session 89 wave 2 - Bug #216: admins.py U+203A separator in help text | style | Role Hierarchy section used › (U+203A) as visual separator; replaced with > (ASCII) | 2026-06-13 (s89) |
| Session 89 wave 2 - Bug #217: help.py U+203A separator in section header | style | section header template used \u203a as separator; replaced with HTML entity &gt; | 2026-06-13 (s89) |
| Session 89 wave 2 - SKILL.md em-dash cleanup | housekeeping | .agents/skills/context7-mcp/SKILL.md 4 em-dashes replaced with N/A or parens | 2026-06-13 (s89) |
| Session 89 wave 2 - Final AST gather audit (0 real bugs) | audit | AST scan: 1 hit in dispatch.py FALSE POSITIVE (_slot catches all exceptions); 0 real gather bugs remain | 2026-06-13 (s89) |
| Session 89 wave 2 - Final Unicode audit (0 issues) | audit | Full regex scan: 0 emoji/em-dash/en-dash/U+203A in any tcbot/ Python file; 0 in docs/; 0 in .agents/ | 2026-06-13 (s89) |

## Pending (remaining optional)

| Item | Priority | Notes |
|---|---|---|
| Module-interface types (types.py) | P3 | Only if cross-module signatures grow ambiguous |
| Query metrics collection | P3 | Data-driven tuning; gather Atlas PA data first |
