---
name: Project context
description: Current state of TCF Bot project - what is done, in progress, and pending. Update before every commit.
---

# TCF Bot - Current Context

**Last updated:** 2026-06-12 (session 62)

## What is done

- Python 3.12, uv, python-telegram-bot (latest), Motor/MongoDB stack fully configured on Replit.
- BOT_TOKEN and MONGODB_URI in Replit Secrets; PORT=8080 in environment.
- `uv run ruff format .` and `uv run ruff check .` both clean (70 files).
- All P1/P2/P3 backlog items resolved (pagination NameError, composite indexes, asyncio.gather conversions, shared replies.py, em-dash removal, cache TTL constants, keyboards.py dead code).
- `docs/mapping.md` updated: added `identity.py`, `replies.py` to helper section; added `pagination.py` to utils section.
- `maintenance.py` and `disconnecting.py` hardcoded `timeout=3.0` extracted to named constants.
- `maintenance.py` converted to `__help_text__` + `__help_sections__` format (last holdout; all modules now consistent).
- `replies.py` now has full permission-tier set: `PERM_TESTER_ABOVE`, `PERM_DEV_ABOVE`, `PERM_ADMIN_ABOVE`, `PERM_STAFF_ONLY`, `PERM_FOUNDER_ONLY`.
- `admins.py` and `broadcasting.py` updated to use `replies.PERM_FOUNDER_ONLY` / `replies.PERM_STAFF_ONLY` throughout.
- `start.py` welcome messages rewritten to fix broken grammar.
- Comprehensive source audit: CLEAN - no emoji, no emoticons anywhere in tcbot/.
- Em-dash cleanup (session 61): 2 remaining em-dash chars in noqa comments (mongos.py, modules/__init__.py) replaced with parenthetical form.
- Em-dash/en-dash FULL cleanup (session 62): 141 remaining em-dashes across 100 markdown files replaced with `: ` equivalents. Zero remaining in all project docs.
- Bug #44 (session 61): 4 callbacks (admins.py x3, appeal_flow.py on_decision) did DB await before q.answer(). Fixed with asyncio.gather pattern. Also fixed double-answer bug in appeal_flow.py:on_decision.
- Bug #45 (session 61): connected_flow.py on_join_decision did Telegram API call before q.answer(). Fixed.
- Perf (session 61): start.py _show_groups gathered q.answer + db.active_groups in parallel.
- Bug #46 (session 62): users_roles.py is_staff/can_act_on/get_effective_role asyncio.gather without return_exceptions. All auth checks now fault-tolerant with conservative-deny fallbacks. Added logging.
- Bug #46p2 (session 62): promote_flow.py request_admin enqueue+get_owner_id gather without return_exceptions; enqueue failure now returns user-facing error.
- Bug #47 (session 62): decorators.py resolve_and_check gather without return_exceptions. Fixed with None fallbacks.
- Perf (session 62): check_flow.py bans_list/warns_by_group/appeals_list/_per_chat_event_list: sequential _name(target_id) after main DB fetch replaced with asyncio.gather. All 5 check drill-down list views now fetch DB+name in one round-trip.
- Perf (session 62): appeal_flow.py on_decision approve path: _update_or_send_log + send_message(unban log) gathered in parallel.
- Bot restarts cleanly: MongoDB connected, indexes ensured, 75 handlers registered, polling active.
- `kicking_flow.py` SyntaxError fixed.
- All inline-string extractions complete across all modules and workflows.
- Comprehensive doc audit complete (2026-06-02): fixed 4 stale references.
- `tcbot/__main__.py`: module-level `warnings.filterwarnings` added for PTBUserWarning.
- Docstrings added to all public handler/executor functions (AST audit: 0 missing).
- Class docstrings on all public classes in documents.py.

- Sequential await fixes (session 5):
  - `identity.classify()`: gather get_user_mention_data + get_effective_role (affects all mod commands)
  - `stats.py`: refactored `_ack_and_render(q, data_coro)` - 12 handlers fixed
  - `groups.py _toggle` cache-hit path: gather q.answer() + safe_edit()
  - `admins.py cmd_promote/cmd_demote`: gather identity.classify + get_effective_role

- Session 6 doc / workflow accuracy fixes (2026-06-03):
  - Fixed `performance.yml` benchmark: `users_db` → `users_cache` (both benchmark functions), added `import os` to compare-baseline script.
  - Fixed 4 occurrences of "02:00 UTC" → "04:00 UTC" (auto-fix.yml comment, docs/workflows-guide.md ×2, README.md).
  - Fixed "Manual dispatch only / Manual deployment" in docs/workflows-guide.md and README.md for run-bot.yml (actual trigger: cron every 4 hours).
  - Fixed config.env.example: removed misleading `PORT=auto` "pick free port" comment; removed four `PROOFS/LOGS/LOGS_ERRORS/APPEALS=auto` "create forum thread" comments.
  - Added docstrings to 12 public functions: `bold`, `italic`, `code`, `link`, `esc`, `on_groups_details`, `on_groups_simple`, `on_help_menu`, `on_helpc_main`, `appeal_deep_link`, `on_menu_groups`, `on_menu_groups_simple`.
  - Added 8 new P4 findings rows to PLAN.md Code Review Findings; all `Resolved`.

- Session 7 constant propagation (2026-06-03):
  - Added `SEC_COMMANDS`, `SEC_WHO`, `SEC_WHERE`, `SEC_WHAT`, `SEC_EXAMPLES`, `SEC_TARGET` to `replies.py`; all 14 module files updated.
  - Added `NO_REASON = "No reason provided"` to `replies.py`; 7 callers updated.
  - Ruff clean (141 files).

- Session 8 symlinks (2026-06-03):
  - `.kilo/kilo.json` moved to `.agents/kilo.json`; `.kilo/` replaced with symlink `.kilo -> .agents`.
  - `.trae/skills/` (stale duplicate) deleted; `.trae/` replaced with symlink `.trae -> .agents`.
  - `.claude/` added as a symlink mirror `.claude -> .agents` (`ln -s .agents .claude`), same as `.kilo` and `.trae`.

- Session 9 docs audit (2026-06-03):
  - Full docs audit: all .md files reviewed; all Mermaid diagrams verified accurate; no stale content found.

- Session 14 (2026-06-06): docs
  - Fixed stale `handlers/` layout in `.agents/memory/structure.md`.
  - Documented `modules/types.py` in docs/mapping.md and docs/modules/modules.md.
  - Updated `nothing.md` operating brief baseline.

- Session 25 (2026-06-07): final QA pass on Replit after migration.
  - AST audit: 0 public functions or classes missing docstrings (after fixing `_MessageLike.get_bot()` stub in `prefixes.py`).
  - All sequential await pairs verified as data-dependent; no independent sequential awaits remain.
  - Ruff file-count baseline updated 143 -> 144 across all memory and CHANGELOG references.
  - Ruff 144 files clean.

- Session 26 (2026-06-06): magic number cleanup in check_flow.py and help.py.
  - Extracted `_REASON_PREVIEW_LEN = 80` and `_BUTTON_TITLE_MAX = 24` to named constants in `check_flow.py`; replaced all bare slice literals.
  - Replaced `data[6:]` / `data[7:]` in `help.py` with `data[len("helpc_"):]` / `data[len("helps_"):]` / `data[len("helpcs_"):]` for self-documentation.
  - Removed stale `nothing.md` broken link from MEMORY.md index.
  - Ruff 144 files clean.

- Session 27 (2026-06-06): coverage-driven cleanups.
  - Fixed `_RateLimiter.__slots__` monkeypatch: patch module-level name, not instance attribute.
  - Renamed 6 inner `wrapper` -> `_wrapper` in decorators.py.
  - Ruff 144 files clean.

- Session 28 (2026-06-06): named constants cleanup + formatter helper.
  - Extracted 8 named constants to `__main__.py` (HTTP timeouts, pool sizes, text/border widths).
  - Extracted `_DEFAULT_PORT` and `_ERR_OWNER_ID` constants to `__init__.py`; eliminated 6 repeated literals.
  - Added `proof_line(proof_desc)` to `formatter.py`; de-duplicated f-string from 3 flow files.
  - Extracted `_MAX_CONTEXT_LEN = 120` to `error_reporter.py`; replaced 2 bare `[:120]` slices.
  - Extracted `_SECS_PER_HOUR`, `_SECS_PER_DAY`, `_DAYS_PER_YEAR` to `muting_flow.py`; replaced all time-math literals.
  - Added `WHERE_CONNECTED_GROUP` to `replies.py`; replaced literal in kicking/muting/warnings.
  - Ruff 144 files clean.

- Session 30 (2026-06-06): magic number extraction: MongoDB pool params + all ratelimiter constants across all 16 module files.
  - Extracted 7 named MongoDB constants to `mongos.py`; replaced all 7 bare literals in `connect()`.
  - Extracted `_RL_*` named constants to all 16 `tcbot/modules/*.py` files with `@ratelimiter` decorators; replaced every bare `limit=` and `period=` literal. Every `@ratelimiter` call-site in `tcbot/modules/` now uses named constants.
  - Ruff 144 files clean.

- Session 29 (2026-06-06): full doc audit.
  - Updated `docs/helper/helper.md` replies.py table: added 9 missing constants (ERR_PERM_EXPIRED, ERR_UNKNOWN_ROLE, WHERE_CONNECTED_GROUP, NO_REASON, SEC_* ×6).
  - Ruff 144 files clean.

- Session 38 (2026-06-07): Ruff rule expansion + 23 code quality fixes.
  - Expanded ruff select: added B, C4, RET, SIM, UP, W; added ignore=["UP047"].
  - Fixed UP017 (datetime.UTC), UP035 (collections.abc), UP037 (no quotes), UP046/UP047 (PEP 695 generics).
  - Fixed RET502/RET503/RET505 (explicit return None), SIM102 (merged if-and), SIM105 (contextlib.suppress).
  - Fixed B905 (zip strict=False in broadcasting.py and maintenance.py).
  - All checks pass: ruff check, ruff format, import OK, bot started cleanly.

- Session 37 (2026-06-07): pyproject.toml cleanup.
  - Removed duplicate `ruff` from `[project] dependencies` (kept only in `[dependency-groups] dev`).
  - Removed stale `# Migrate to latest channel version` comments from runtime deps.
  - Full verification sequence passed: uv sync, import OK, Ruff 71 files clean, bot started cleanly.

- Session 36 (2026-06-07): comprehensive docs audit.
  - Verified all 20+ docs files against current source; all accurate.
  - Fixed stale "144 files" reference in context.md current-state header (71 files).
  - Removed duplicate `types.py` entry from structure.md (was listed twice in modules/ section).
  - Code quality scans: 0 bare except, 0 wildcard imports, 0 direct utcnow(), 0 col() outside database/, 0 print() in production code.
  - All Mermaid diagrams in docs verified accurate. CHANGELOG and memory updated.

- Session 35 (2026-06-07): complete return type annotations across all non-dunder functions.
  - Fixed 12 functions missing return type across 9 files: `__main__.py`, all 7 database accessor files, `extraction.py`.
  - All DB collection accessor functions annotated `-> AsyncIOMotorCollection`; `extraction._safe_get_chat` annotated `-> Chat | None`.
  - Return type AST audit: 0 missing. Ruff 71 files clean.

- Session 34 (2026-06-07): complete parameter type annotations across all private/non-dunder functions.
  - Fixed 31 unannotated parameters across 13 files; all now have correct types.
  - Discovered: `BaseFilter` must be imported from `telegram.ext.filters`, not `telegram.ext` (not re-exported at top level in PTB 22.7).
  - Ruff 71 files clean; import check + bot startup clean.

- Session 33 (2026-06-07): pure side-effect `asyncio.gather` hardening.
  - Added `return_exceptions=True` to 20 pure side-effect gather calls across 12 files: `about.py`, `additional.py`, `privacy.py` (×2), `start.py`, `groups.py`, `connecting.py`, `greeting.py`, `stats.py` (×2), `maintenance.py`, `help.py` (×6), `admins.py` (×2), `appeal_flow.py`, `connected_flow.py`, `reason_flow.py` (×2), `ban_flow.py`.
  - Data-fetching gathers (those that unpack results) intentionally kept without `return_exceptions=True`.
  - Ruff 71 files clean.

- Session 39 (2026-06-11): TYPE_CHECKING import refactor + PERF/PIE cleanup.
  - Added `TC` rule set to `pyproject.toml` (ignoring TC001 for internal TypedDicts).
  - Ran `ruff check --unsafe-fixes` to move 151 annotation-only imports into `if TYPE_CHECKING:` blocks.
  - Affected: stdlib (`datetime.datetime`, `collections.abc.Callable/Awaitable`), third-party (`AsyncIOMotorCollection`).
  - All files had `from __future__ import annotations` so moves are safe (lazy string annotations).
  - Bot restarted cleanly after fix; ruff 71 files clean; import OK.
  - Also added PERF, PIE, TRY400, TRY401 rulesets and fixed all violations:
    - 4 PERF401 (list comprehension/extend), 1 PIE810 (startswith tuple)
    - 15 files: log.error→log.exception in except blocks; removed redundant exc args (TRY401); auto-fixed 14 unused `exc` vars (F841→`except Exception:`)
    - 2 ANN003 (safe_edit/safe_edit_cb **kwargs: Any)
  - pyproject.toml select now: `["B", "C4", "E4", "E7", "E9", "F", "I", "PERF", "PIE", "RET", "SIM", "TC", "TRY400", "TRY401", "UP", "W"]`.

- Session 40 (2026-06-11): RUF ruleset + real bug fix.
  - Added `RUF` to pyproject.toml select; ignored `RUF001` (intentional `›` breadcrumb char).
  - Fixed RUF023 ×2: sorted `__slots__` in `cache.py` and `decorators.py`.
  - Fixed RUF022: sorted `__all__` in `stats_flow.py`.
  - Fixed RUF005: list-concat → unpacking in `modules/__init__.py`.
  - Fixed RUF059 ×4: unused unpacked vars → `_` in `admins.py` ×3, `checking.py`, `muting.py`.
  - Fixed RUF100 ×2: removed unused noqa directives in `decorators.py` and `parse_logmsg.py`.
  - Fixed RUF012 ×2: added `ClassVar` annotations to `BotLogFormatter._LEVELS` and `._COLORED_MSG` in `logger.py`.
  - Fixed RUF006 ×2 (real bug): `asyncio.create_task` / `loop.create_task` references now stored in module-level sets with `discard` done-callbacks in `ban_flow.py` and `logger.py`: prevents GC of in-flight tasks.
  - pyproject.toml select now: `["B", "C4", "E4", "E7", "E9", "F", "I", "PERF", "PIE", "RET", "RUF", "SIM", "TC", "TRY400", "TRY401", "UP", "W"]`.
  - Bot restarted cleanly; ruff all checks passed.

- Session 41 (2026-06-11): PTH + FBT + D rulesets + comprehensive audit.
  - Added `PTH`: fixed PTH110 in `mongos.py`.
  - Added `FBT`: 16 violations fixed: keyword-only bool params in 6 functions; call sites updated; noqa on 3 third-party call sites.
  - Added `D` (pydocstyle): fixed 18 violations: D107/D105 docstrings added, D301 r-string, D205 module docstring, D401 imperative mood rephrases, D202/D413 auto-fixed; D203/D213 in ignore (incompatible with D211/D212).
  - Excluded `.local/`, `.agents/`, `.kilo/`, `.trae/`, `.claude/` from ruff scan (skills/symlinks not our code).
  - pyproject.toml select now: `["B", "C4", "D", "E4", "E7", "E9", "F", "FBT", "I", "PERF", "PIE", "PTH", "RET", "RUF", "SIM", "TC", "TRY400", "TRY401", "UP", "W"]`.

- Session 42 (2026-06-11): PLE + PLC rulesets.
  - Added `PLC` (Pylint-convention) and `PLE` (Pylint-error) to `pyproject.toml` ruff select.
  - `# noqa: PLE0604` on `__all__` spread in `modules/__init__.py` (false positive; `ALL_MODULES` is `list[str]` at runtime).
  - `# noqa: PLC0415` on three intentional lazy imports: `dns.resolver` in `mongos.py` (optional dep), `ban_info.build_ban_detail` in `checking.py` (circular break), `error_reporter` in `logger.py` (circular break).
  - Did NOT add `PLR` (refactoring): fires on large handler functions without benefit.
  - pyproject.toml select now: `["B", "C4", "D", "E4", "E7", "E9", "F", "FBT", "I", "PERF", "PIE", "PLC", "PLE", "PTH", "RET", "RUF", "SIM", "TC", "TRY400", "TRY401", "UP", "W"]`.

- Session 43 (2026-06-11): real correctness bug fix in Layer 3 error handling.
  - Fixed a dangling fire-and-forget task in `__main__.py`'s asyncio exception handler: `lp.create_task(error_reporter.report_exc(...))` discarded the task, so it could be garbage collected before running and silently drop the last-resort error report.
  - Added module-level `_asyncio_report_tasks: set[asyncio.Task[None]]`; task is stored and released via a `discard` done-callback (mirrors `logger._tg_tasks`).
  - RUF006 did not catch it because the task is created through the `lp` event-loop parameter, which ruff cannot statically identify as an event loop.
  - Verified the fix in isolation (task registered on schedule, discarded on completion, report coroutine ran). Ruff clean (70 files); import OK.
  - Reconciled memory drift: `context.md` and `progress.md` were stale at session 41 while CHANGELOG/`decisions.md`/`pyproject.toml` were already at session 42; file-count note corrected 71 -> 70.

- Session 44 (2026-06-11): skill-doc drift fix.
  - Synced the embedded `pyproject.toml` snapshot in `.agents/skills/python-code-quality/SKILL.md` and `REFERENCE.md` with the real file: stale 5-group ruff select -> current 22-group set; `ruff` moved to `[dependency-groups] dev`; removed 4 stale `# Migrate to latest channel version` comments; added `[tool.ruff] exclude`; fixed REFERENCE.md's false "not a full strict style suite" line.
  - `.agents/RUFF.md` confirmed canonical and already accurate (select + ignore + exclude match pyproject.toml exactly).
  - Confirmed there is no JobQueue usage anywhere in `tcbot/`: temporary mutes use Telegram's native `until_date` in `muting_flow.py` (restart-safe; Telegram lifts the restriction on expiry). The `[job-queue]` extra stays declared per project policy. Repo docs only describe it as a declared extra, which is accurate, so no doc drift there.

- Session 45 (2026-06-11): pyproject.toml editable-install fix.
  - Added `[tool.setuptools.packages.find] include = ["tcbot*"]` to fix `uv pip install -e .` failure caused by Replit's `attached_assets/` folder being discovered as a second top-level package.
  - Added `attached_assets/` to `[tool.ruff] exclude` so Ruff does not scan uploaded task files.
  - Updated `.agents/RUFF.md`, `python-code-quality/SKILL.md`, `python-code-quality/REFERENCE.md` to reflect new exclude list.
  - Full verification sequence PASS: uv sync, editable install, import check, ruff format, ruff check, bot restart (MongoDB connected, 75 handlers, polling active).

- Session 47 (2026-06-11): code quality + docs gaps.
  - broadcasting.py and connected_flow.py: replaced inline `sum(isinstance...)` patterns with `count_errors(results)`; added import.
  - docs/helper/helper.md: expanded parse_editmsg section to table covering safe_edit + safe_edit_cb (safe_edit_cb was entirely missing).
  - docs/utils/utils.md: added count_errors to dispatch table; split ANY_CMD_FILTER row into 2 explicit rows; added full pagination.py section + Mermaid node.
  - docs/workflows/workflows.md: added Demotion: demote_flow.py section (with trigger table); added Check: check_flow.py section (full 8-method table with callback prefixes). Both were missing entirely.
  - docs/workflows-guide.md: removed 4 prohibited characters (em-dash, emoji).
  - docs/databases/databases.md: added `kicks` and `mutes` rows to Startup indexes table; added Kick model and Mute model sections (parallel to Warning model).
  - docs/databases/databases.md (Member cache optimization): expanded to 5-row table adding get_first_names_batch and get_mention_data_batch; added get_group_titles note; updated performance tip.
  - docs/databases/databases.md: renamed "Ban document fields" to "Ban model"; added Key helper functions bullet list for all 14 public bans_db functions. Consistent with kick/mute model sections.
  - docs/databases/databases.md: Warning model section updated: removed private _sync_warn_count reference; added Key helper functions for all 8 public warns_db functions.
  - Ruff 70 files clean; import OK.

- Session 46 (2026-06-11): docs gap fixes in helper.md.
  - Added `proof_line(proof_desc)` to formatter.py table (was missing; function added session 28, used by kicking/muting/warning flows).
  - Added 7 missing keyboards.py factories to table: `groups_menu_kb`, `tcgroups_kb`, `stats_main_kb`, `stats_back_kb`, `module_help_kb`, `back_to_module_kb`, `additional_menu_kb` across new Groups/Stats rows and Menus/help row.
  - Table now covers all 25 public keyboard factories in keyboards.py.
  - Full 7-step verification PASS: uv sync, editable install, import OK, ruff format (70 files), ruff check, bot start (handlers registered, polling), docs audit.

- Session 48 (2026-06-12): real correctness bug fix in greeting.py.
  - Bug #3: `greeting.py` `_handle_member`: replaced bare `asyncio.gather(ban_chat_member, reply_text)` in `try/except` with `return_exceptions=True` gather. Previously if reply failed after ban succeeded, logged "Auto-ban on join failed" (misleading). Now ban failure logs ERROR; reply failure logs DEBUG.
  - Full asyncio.gather audit across all 50+ gather calls: all pure side-effect gathers have `return_exceptions=True`; data-fetching gathers correctly omit it.

- Session 49 (2026-06-12): HTML escaping bug fix in moderation flows.
  - Bug #4: `reason` / `reason_text` (user-provided input) was embedded unescaped in HTML messages in ban_flow.py, muting_flow.py, kicking_flow.py, warning_flow.py. Fixed all four: added `esc` to formatter import and wrapped reason with `esc()` at display point. Stored data unchanged.
  - Full HTML escaping audit: `LogBuilder.field()` already escapes by default; `code()` and `mention()` escape internally; `proof_line()` safe (only "Photo/Video (msg N)" strings); `cfg.community_name` is admin-controlled config (not user-provided).
  - Ruff 70 files clean after all fixes.

- Session 50 (2026-06-12): Two correctness bug fixes.
  - Bug #5: `proof_flow.py` `step_prompt`/`noted_prompt` embedded `reason`/`inline_reason` in HTML `<b>` tags without `esc()`. Added `esc` import and wrapped both strings. Circular import risk confirmed absent.
  - Bug #6: `admins.py` `cmd_promote_request` always rejected all promotion requests with "Promoting yourself? Nice try..." because `identity.classify(user.id, user.id, ...)` always returns `Identity("self")` in self-submission flows. Removed identity check; replaced with parallel `get_effective_role` + `get_request` check. Users with existing roles get clear rejection; duplicate-request guard retained.
  - Comprehensive audit of all remaining critical files completed: `checking.py`, `parse_logmsg.py` (full 767 lines), `check_flow.py` (full 513 lines), `stats.py`, `appeals.py`, `groups.py`, `demote_flow.py`: all clean.
  - Ruff 70 files clean; bot running (MongoDB connected, 75 handlers, polling active).

- Session 51 (2026-06-12): disable link preview globally.
  - Added `Defaults(link_preview_options=LinkPreviewOptions(is_disabled=True))` to `ApplicationBuilder` chain in `__main__.py`. All 205+ reply_text/send_message/edit_message_text calls now suppress Telegram link-preview cards without touching individual call sites.
  - Audit completed: `about.py`, `additional.py`, `unbanning.py`, `privacy.py`, `error_reporter.py`, `unban_flow.py`, `promote_flow.py`, `connected_flow.py`, `broadcasting.py`, `maintenance.py`, `decorators.py`: all clean.
  - Bot restart verified: Defaults active, MongoDB connected, 75 handlers, polling active.

- Session 52 (2026-06-12): audit wave 2: found and fixed stats search query bug.
  - Bug #7: `stats.py` `on_bans_search_input` never stored `query` to `ctx.user_data["stats_last_query"]`. When user tapped "« Back" from a search-detail card, `on_stats_search_back` rendered `Search: "" (N found)`: query string always blank.
  - Fix: added `ctx.user_data["stats_last_query"] = query` after RESULTS_KEY is set in `on_bans_search_input`.
  - Also: `Stats.clear_search` did not clear `"stats_last_query"`: stale data would survive to next search session. Added it to the clear loop in `stats_flow.py`.
  - Full audit wave 2 complete: all 50+ files read (greeting, appeals, broadcasting, additional, maintenance, privacy, check_flow, proof_flow, connecting, disconnecting, promote_flow, demote_flow, __main__, groups_db, warns_db, kicks_db, mutes_db, queues_db, users_roles, users_cache, mongos, dispatch, prefixes, parse_logmsg, error_reporter, pagination, stats_flow, stats): all clean except the above two-line fix.
  - Ruff 70 files clean; bot running (MongoDB connected, 75 handlers, polling active).

- Session 55 (2026-06-12): ConversationHandler TIMEOUT state fix (Bug #9).
  - All three ConversationHandlers (ban_flow, reason_flow, appeal_flow) had `conversation_timeout` set but no `ConversationHandler.TIMEOUT` state. PTB's scheduler proactively calls `_trigger_timeout`, which runs TIMEOUT handlers -- without them, conversation silently ends with no user notification.
  - ban_flow: added `ConversationHandler.TIMEOUT: [TypeHandler(Update, on_proof_timeout)]`; moved Update to runtime import; added TypeHandler.
  - reason_flow: added inner `_on_timeout` handler (None-guarded) and TIMEOUT state; added TypeHandler.
  - appeal_flow: added `_MSG_TIMEOUT` constant, `BuildAppeal._on_timeout` method (None-guarded), and TIMEOUT state; added TypeHandler.
  - Ruff 70 files clean; all imports OK; bot restarted (MongoDB connected, 75 handlers, polling active).

- Session 56 (2026-06-12): asyncio.gather return_exceptions systematic audit + critical bug fix.
  - Audited all asyncio.gather calls codebase-wide. Found pattern: gathers that use results (groups, ban, req, etc.) without return_exceptions, so BaseException values flowed into the code as if they were real data → crashes or false behavior.
  - Bug #10: connected_flow.py on_bot_added: was_connected could be BaseException → truthy → spurious disconnect log sent.
  - Bug #11: unban_flow.py execute_unban: groups could be BaseException → fan_out list comprehension crash.
  - Bug #12: ban_flow.py _execute_ban: same groups crash in ban enforcement path.
  - Bug #13: appeal_flow.py on_review_decision: ban could be BaseException → ban.get() AttributeError crash.
  - Bug #14: appeal_flow.py on_review_decision approve branch: groups/target_fname BaseException crashes.
  - Bug #15: promote_flow.py: 3 pure DB-write gathers without return_exceptions (add_admin, set_role, upsert_user combinations).
  - Bug #16: admins.py on_promo_decision: req could be BaseException → req["target_id"] crash.
  - Bug #17: admins.py on_demote_confirm: tuple unpacking (target_fname, target_uname) from BaseException crash.
  - Bug #18: admins.py on_promote_role_select: target_fname/current_role BaseException passed directly to Promote.execute().
  - Bug #19 (CRITICAL): greeting.py _handle_member: ban could be BaseException (truthy) → auto-ban issued for user who was NOT federation-banned. False ban of innocent user.
  - Bug #20: warns_db.py clear_warns + remove_last_warn: DB result access without return_exceptions protection.
  - All 10 bugs fixed. Ruff 70 files clean; bot restarted clean (MongoDB connected, 75 handlers, polling active).

- Session 54 (2026-06-12): dependency upgrade.
  - PTB 22.7 -> 22.8 (released 2026-06-12). `Defaults` was already imported from `telegram.ext` (correct); `LinkPreviewOptions` still in `telegram`. No breaking changes in codebase.
  - ruff 0.15.16 -> 0.15.17. No new rule violations (70 files unchanged).
  - CHANGELOG.md updated with entries for sessions 52, 53, and 54.
  - Bot restarted clean: MongoDB connected, indexes ensured, scheduler started, 75 handlers, polling active.

- Session 53 (2026-06-12): audit wave 4 + bug fix.
  - DRY fix in `help.py`: added `_ERR_SECTION_NOT_FOUND` constant; replaced two inline literals in `_show_section()` with named constants. (`_ERR_TOPIC_NOT_FOUND` was already extracted; now `_ERR_SECTION_NOT_FOUND` joins it.)
  - Audit wave 4 completed: `decorators.py`, `kicking_flow.py`, `warning_flow.py`, `reason_flow.py`, `connected_flow.py`, `unban_flow.py`, `parse_editmsg.py`, `parse_link.py`, `replies.py`, `keyboards.py`, `muting_flow.py`: all clean.
  - Explorer audited `banning.py`, `kicking.py`, `muting.py`, `warnings.py`: all clean; confirmed `WARN_LIMIT=3` is correct (explorer false-positive about `_RL_WARN_LIMIT=5` which is rate-limiter constant, not warn limit).
  - Explorer audited `unbanning.py`, `groups.py`, `admins.py`: false positives on `@mod_only`-guarded functions; one real bug found.
  - Bug #8: `admins.py` `on_promo_decision` promo_approve branch: `asyncio.gather(add_admin, resolve)` missing `return_exceptions=True`. Counterpart `promo_reject` branch already had it. Fixed: consistent with project convention for pure side-effect gathers.
  - Full audit now covers all 30+ module and helper files; no remaining unaudited files.
  - Ruff 70 files clean; bot running (MongoDB connected, 75 handlers, polling active).

- Session 57 (2026-06-12): systematic HTML-escaping audit across all modules.
  - Bug #28: `privacy.py` `on_privacy_menu`/`on_privacy_policy_menu`: `ctx.bot.first_name` raw in HTML format strings. Wrapped with `esc()`.
  - Bug #29: `start.py` `cmd_start`/`on_back_to_start`: same pattern. Wrapped with `esc()`.
  - Bug #30: `appeal_flow.py` `_on_approve`: `self.community_name` raw in HTML DM to user. Wrapped with `esc()`.
  - Bug #31: `demote_flow.py` `Demote.execute`: `role_label` (inside `<b>` tags) and `cfg.community_name` unescaped in DM. Wrapped both with `esc()`.
  - Bug #32: `help.py` `_show_help_index`/`cmd_help`: `ctx.bot.first_name` raw in HTML format strings. Wrapped with `esc()`.
  - Bug #33: `help.py` `cmd_help`: `query` (lowercased user input) raw in `f"Module <b>{query}</b> not found."` with `parse_mode="HTML"`. Wrapped with `esc(query)`.
  - Bug #34: `warning_flow.py` `execute_warnlist`: `w.get('reason', 'No reason')` (admin-typed warn reason from DB) raw in HTML list. Wrapped with `esc()`.
  - Comprehensive audit completed: `keyboards.py`, `parse_logmsg.py`, `parse_editmsg.py`, `extraction.py`, `bans_db.py`, `warns_db.py`, `queues_db.py`, `dispatch.py`, `timedate_format.py`, `unban_flow.py`, `promote_flow.py`, `reason_flow.py`, `admins.py`, `banning.py`, `kicking.py`, `warns.py`: all clean.
  - All false positives resolved: `staff_only`/`mod_only`/`owner_only` decorators guard `effective_user is None`; `promote_flow.py:161` gather without `return_exceptions=True` is correct for data-fetching gather; `admins.py:542` early-reject pattern is correct.
  - Ruff 70 files clean; bot running (MongoDB connected, scheduler started, polling active).

- Session 58 (2026-06-12): anonymous admin, album flush, chat migration.
  - Bug #37: `decorators.py` all 4 auth decorators (owner/staff/mod/basic_mod) -- GroupAnonymousBot (1087968824) silently failed as "no rank". Added `_is_anon_admin()` + `_ERR_ANON_ADMIN`, applied first in all decorators.
  - Bug #35: `ban_flow.py` `_flush_album` -- user_data not cleared after ban execute; second album could re-fire ban. Added `_album_userdata` reference dict and post-flush cleanup.
  - Bug #36: `ban_flow.py` `_flush_album` -- no guard for required meta keys (target_id, admin_id). Added early-return warning.
  - Bug #38: `greeting.py` / `groups_db.py` -- no chat migration handler. Added `migrate_group()` in groups_db + `on_chat_migration` handler using `filters.StatusUpdate.MIGRATE`.
  - Discovered PTB 22.8 uses `filters.StatusUpdate.MIGRATE` (not `MIGRATE_FROM_CHAT_ID`/`MIGRATE_TO_CHAT_ID`). Saved to decisions.md.
  - Ruff 70 files clean; bot running (MongoDB connected, scheduler started, polling active).

- Session 59 (2026-06-12): checking.py q.answer race, stats_flow gathers, ban_info gather, warnings.py gather, groups._toggle serial awaits.
  - Bug #39: `checking.py` `on_checkme_detail`/`on_checkme_back`: DB before `q.answer()`. Fixed with `asyncio.gather(q.answer(), get_ban(), return_exceptions=True)`.
  - Perf: all 8 `on_check_*` handlers serial q.answer+method → gathered with `return_exceptions=True` and isinstance guards.
  - Bug #40: `stats_flow.py` `Stats.main` (7-coro) and `Stats.staff_roster` (4-coro) gathers lacked `return_exceptions=True`. Fixed with per-field fallbacks.
  - Bug #41: `ban_info.py` `build_ban_detail` gather lacked `return_exceptions=True`. Fixed with r_target/r_admin unpack guards.
  - Bug #42: `warnings.py` `cmd_warn` gather (classify + resolve_and_check) lacked `return_exceptions=True` in ConversationHandler entry. Fixed with isinstance guards + END on failure.
  - Perf: `groups.py` `_toggle` cache-hit and cache-miss serial awaits → gathered.
  - Ruff 70 files clean; bot running (MongoDB connected, scheduler started, polling active).

- Session 60 (2026-06-12): Bug #43: banning/muting/kicking ConversationHandler entry gathers.
  - Bug #43: `banning.py` `cmd_ban_start`, `muting.py` `cmd_mute`, `kicking.py` `cmd_kick` all had `asyncio.gather(identity.classify, resolve_and_check)` without `return_exceptions=True`. DB failure left ConversationHandler open (identical pattern to Bug #42 in warnings.py, missed in that session). Fixed all three with individual isinstance guards + ConversationHandler.END on failure.
  - AST audit confirms no remaining ConversationHandler entry points with unguarded classify/resolve_and_check gathers.
  - Ruff 70 files clean; bot running (MongoDB connected, scheduler started, polling active).

## What is in progress

Nothing. Session 60 checkpoint complete.

## What is pending (optional)

- Query metrics collection (data-driven; gather Atlas PA data first).

## Known runtime notes

- `python -m ruff check .` and `python -m ruff format .` are the correct lint/format commands on Replit (packages installed via pip; uv sync fails on nix store).
- Workflows are configured to use `python -m tcbot` (no `uv run`).
- Flask keep-alive runs on PORT=8080 (mapped by Replit to external port 80).
- Bot fails fast when BOT_TOKEN/MONGODB_URI/OWNER_ID are not set. Secrets must be in Replit Secrets.
- Communication with user: Indonesian. Code/docs/commits: English.
- Agent-rule docs are being re-audited for internal consistency; session 15 fixed a contradiction in `.agents/CLAUDE.md` where one section still allowed emojis even though the canonical bot voice forbids pictograph emoji and text emoticons.
- Session 15 verification baseline passed end to end: `uv sync`, editable reinstall, import check, startup check, Ruff, runtime start, and stale-rule grep audit.
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
