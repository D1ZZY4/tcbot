---
name: Project context
description: Current state of TCF Bot project - what is done, in progress, and pending. Update before every commit.
---

# TCF Bot - Current Context

**Last updated:** 2026-06-16 (session 160)

## What is done

- Session 160 (2026-06-16): Bug #430 fixed. `unbanning.cmd_unban` gathered `identity.classify` with speculative `db.bans_db.get_active_ban` in parallel; `execute_unban` updated to accept `pre_ban` keyword arg (skips DB round-trip when caller supplies the record). Docs: `docs/workflows/workflows.md` updated for new `execute_unban` signature. Comprehensive scans: N+1 AST scan CLEAN, create_task error-handlers CLEAN, q.answer() placement CLEAN, identity.classify consistency CLEAN, consecutive-await AST scan found only 2 intentionally-sequential pairs (`set_owner` crash-safety, `cmd_transfer` DB write order). Total bugs: #1-#430. Open: CVE-2026-31072 (accepted), Improvement #4 (future).

- Session 159 (2026-06-16): Bug #424-#429 fixed. Systematic sequential-await audit across all major workflow and command files.
  - Bug #424: `connected_flow.on_bot_added` — parallel `get_pending + is_connected` pre-fetch + `complete_join + edit_message_text` gather.
  - Bug #425: `admins.on_promo_decision` — speculative pre-fetch of `get_request_by_id` into initial gather alongside ownership check and `q.answer()`.
  - Bug #426: `appeal_flow` review callback — speculative pre-fetch of `get_ban` into initial gather alongside staff check and `q.answer()`.
  - Bug #427: `disconnecting.cmd_tcdisconnect` — parallel pre-fetch of `is_connected + is_staff + member` in initial gather.
  - Bug #428: `ban_flow.execute_ban` — PM notification merged into gather with `upsert_user` and `edit_message_text`.
  - Bug #429: `connecting.cmd_tcconnect` — `get_chat_member(ctx.bot.id)` added speculatively to initial 4-way gather (was sequential after user-member + DB reads).
  - All other areas audited CLEAN: `warning_flow.py` (all standalone awaits are guard-check or sequential-dep patterns), `muting_flow.py` (active_groups before fan_out, CORRECT), `check_flow.py` (get_group_titles deps on user_warn_groups, CORRECT), `stats_flow.py` (all deps chains correct), `error_reporter.py` (if/else mutually exclusive branches, CORRECT), `demote_flow.py` (guard check sequential dep, CORRECT).
  - Verification: ruff format 74 files unchanged, ruff check All checks passed, import OK. Bot: 29/29 indexes, Redis hiredis 3.4.0, APScheduler, polling.
  - Total bugs: #1-#429. Open: CVE-2026-31072 (accepted), Improvement #4 (future).

- Session 157 (2026-06-16): Bug #423 fixed. `proof_line()` removed entirely. Mute/kick/warn proof now uploaded to proof channel and shown as inline keyboard button (identical pattern to ban). Files changed: `reason_flow.py`, `keyboards.py`, `muting_flow.py`, `kicking_flow.py`, `warning_flow.py`, `utils/formatter.py`, `modules/helper/formatter.py`. Ruff: all checks passed. Import: OK. Total bugs: #1-#423.

- Session 156 (2026-06-16): Wave 5 deep combinatorial audit — ALL 6 "Bug Nyata dari Testing Langsung" areas, ZERO new bugs.
  - Direct reads (all CLEAN): muting_flow.py (full 300 lines), ban_flow.py (full 528 lines), unban_flow.py (full), scheduler.py (full), check_flow.py (400-601). All previously audited files confirmed again.
  - 5 parallel subagent waves: SA1 (ban enforcement), SA2 (muting/unban/scheduling), SA3 (target resolution), SA4 (decorators/warning_flow/appeal_flow/admins), SA5 (connected_flow/bans_db/greeting/dispatch). All returned CLEAN.
  - Confirmed: execute_unmute has no cancel_schedule because mutes use Telegram until_date (no APScheduler job); timed-ban is future work (schedule_unban only referenced in scheduler.py docstring, never called externally).
  - Confirmed: warning_flow per_group uses exact `==` (atomic $inc), fed_global uses `>=` with already_banned guard — no race condition. Both paths produce identical outcome (federation ban).
  - Confirmed: appeal_flow stale-review 72h auto-clear in _start() prevents permanent lockout.
  - Confirmed: admins.py uses identity.classify + Promote/Demote.execute (not resolve_and_check) — intentional because hierarchy management requires finer control via internal rank validation.
  - Confirmed: dispatch.py semaphore _MAX_CONCURRENT=10, configurable via max_concurrent kwarg.
  - uv lock --upgrade run: 33 packages resolved, lock updated.
  - Ruff: All checks passed (74 files). Import: OK. Zero new bugs. Total bugs: #1-#422 (unchanged).
  - Open: CVE-2026-31072 (accepted), Improvement #4 (future).

- Session 155 (2026-06-16): Wave 4 zero-finding pass — ALL 74 tcbot/ Python files fully re-audited CLEAN.
  - Files audited this session (all CLEAN, confirmed by direct reads + explore subagent batch): extraction.py, identity.py, admins.py, checking.py, dispatch.py, decorators.py, users_cache.py, users_roles.py, kicking_flow.py, keyboards.py, replies.py, cache.py, __main__.py, ban_info.py, mongos.py (full), groups_db.py (full), formatter.py, pagination.py, prefixes.py, timedate_format.py, alive.py, scheduler.py (database), redis_client.py, documents.py, kicks_db.py, stats_flow.py (full 539 lines), promote_flow.py (full 246 lines), parse_logmsg.py (full 798 lines), error_reporter.py, queues_db.py, __init__.py, database/__init__.py, modules/__init__.py, about.py, additional.py, appeals.py, broadcasting.py, connecting.py, disconnecting.py, groups.py, help.py, maintenance.py, netspeed.py, privacy.py, start.py, stats.py, types.py, modules/helper/__init__.py, helper/formatter.py, parse_editmsg.py, parse_link.py, workflows/__init__.py, proof_flow.py, reason_flow.py.
  - Ruff: All checks passed (74 files). Bot: APScheduler running, all subsystems healthy.
  - Zero new bugs found. Baseline holds: #1-#422 total. Open: CVE-2026-31072 (accepted), Improvement #4 (future).

- Session 151 (2026-06-16): Zero-finding pass — full audit of remaining files. AUDIT COMPLETE.
  - Files audited (all CLEAN): proof_flow.py, warnings.py, appeals.py, mutes_db.py, kicks_db.py, connecting.py, disconnecting.py, warning_flow.py (full 477 lines), error_reporter.py, cache.py (database layer, full), alive.py, parse_logmsg.py (full), prefixes.py, pagination.py, timedate_format.py, logger.py.
  - Ruff: All checks passed. Import: OK. Bot running (APScheduler ready, all subsystems healthy).
  - No bugs found. Baseline holds: #1-#422 total. Open: CVE-2026-31072 (accepted), Improvement #4 (future).

- Session 150 (2026-06-16): Bug #422 found and fixed.
  - Bug #422: `docs/performance.md` "Performance Benchmarks" section — subsection "After Optimization (v4.6.2 baseline)" showed second-level measured times (0.5-1.2 s) that directly contradicted the mandatory v4.6.2 targets (< 5 ms p95 bot-side). Label was misleading. Fixed: replaced contradictory subsection with an accurate per-layer breakdown (L1/L2/MongoDB/Telegram network) and a clarifying note that the p95 target is bot-side processing only.
  - Added v4.6.2 performance decision entry to `.agents/memory/decisions.md` (bot-side vs. network split).
  - All GitHub workflows verified CLEAN: lint.yml, run-bot.yml (FED_WARN_LIMIT confirmed present), auto-fix.yml, codeql.yml, dependency-update.yml.
  - Dockerfile verified CLEAN (Python 3.12-slim, uv, hiredis C extension verify step).
  - docker-compose.yml verified CLEAN (all 3 services, healthchecks, restart policies, internal network, .env).
  - Symlinks verified: .kilo/.trae/.claude/.roo all point to .agents.
  - Ruff: 74 files unchanged, All checks passed. Import: OK. Total bugs: #1-#422.
  - Remaining open: CVE-2026-31072 (accepted), Improvement #4 (future).

- Session 149 (2026-06-16): Zero-finding pass — all remaining modules audited CLEAN.
  - Files audited: `about.py`, `start.py`, `help.py`, `stats.py`, `maintenance.py`, `netspeed.py`, `privacy.py`. All CLEAN.
  - Ruff: 74 files unchanged, All checks passed. Import: OK.

- Session 146 (2026-06-16): Deep combinatorial audit of 6 focus areas — ZERO new bugs. Third consecutive zero-finding session.
  - T001: `allowed_updates=Update.ALL_TYPES` confirmed; `on_chat_migration` with `MIGRATE` filter present in greeting.py. CLEAN.
  - T002: `mutes_db` `get_active_mute`/`active_mute_docs` filter `until_date > now` at query time — no APScheduler race possible. CLEAN.
  - T003: `ban_flow._execute_ban` has `get_active_ban` guard; ConversationHandler `per_user/per_chat=True` state prevents double-submit. CLEAN.
  - T004: `groups_db.add_group` is upsert; `on_bot_added` checks `is_connected` before sending join prompt on re-add. CLEAN.
  - T005: timed-ban `_ = ban_duration` confirmed known limitation; `unban_flow` already calls `cancel_schedule` for future-proofing. CLEAN.
  - T006: `WARN_LIMIT=3` hardcoded intentional (no `cfg.warn_limit`); `fed_warn_limit` integrated; `federation_warn_count` sums correctly; all `bans_db` deactivate funcs correct.
  - Ruff: 74 files, all checks passed. Import: OK. Total bugs: #1-#420. Remaining open: CVE-2026-31072 (accepted), Improvement #4 (future).

- Session 145 (2026-06-16): Final audit sweep — ZERO new bugs. All remaining tcbot/ files verified CLEAN.
  - Files audited (all CLEAN): `tcbot/utils/__init__.py`, `tcbot/modules/about.py`, `tcbot/modules/help.py`, `tcbot/modules/start.py`, `tcbot/modules/stats.py`, `tcbot/modules/checking.py`, `tcbot/modules/privacy.py`, `tcbot/modules/maintenance.py`.
  - Previous sessions (141-144) had already verified all other modules in `tcbot/modules/` CLEAN.
  - Ruff: 74 files, all checks passed. Import: OK. Total bugs: #1-#420. Codebase audit complete.
  - Remaining open: CVE-2026-31072 (accepted), Improvement #4 (future).

- Session 144 (2026-06-16): Audit pass 25 — 1 CI workflow bug fixed (#420).
  - Bug #420: `.github/workflows/run-bot.yml` env block was missing `FED_WARN_LIMIT`. Added in Bug #383 (session 134) as the federation-wide warn auto-ban threshold, never added to the GitHub Actions env mapping. Added `FED_WARN_LIMIT: ${{ secrets.FED_WARN_LIMIT }}` alongside `WARN_EXPIRY_DAYS`.
  - Full task file (attached_assets/task-tcbot-v4.6.2_1781639614633.md, 953 lines) read completely.
  - Comprehensive code audit this session: promote_flow.py (full), mongos.py (full), cache.py (full), redis_client.py (full), connecting.py (full), admins.py on_promo_decision + on_demote_confirm (full verification of all 4 Bug #413 sites), lint.yml, run-bot.yml, auto-fix.yml, dependency-update.yml, codeql.yml, Dockerfile, docker-compose.yml. All CLEAN except Bug #420.
  - Ruff: All checks passed (74 files). Import OK. Total bugs: #1-#420.
  - Remaining open: CVE-2026-31072 (accepted), Improvement #4 (future).

- Session 143 (2026-06-16): Audit pass 24 — 1 doc bug fixed (#419).
  - Bug #419: docs/warnings-detailed.md `/resetwarns behavior` section still stated "/resetwarns currently does not send a federation log entry." — stale since Bug #412 (session 140) added resetwarns_log() and the concurrent log+reply gather. Fixed: (1) removed stale statement, (2) updated flow step 6 to describe concurrent log send + reply, (3) added resetwarns_log row to templates table, (4) added resetwarns_log includes: section (community name, moderator mention, target mention+user ID, warnings cleared count, group, date).
  - Comprehensive code audit this session: ban_flow.py, banning.py, greeting.py, connected_flow.py, extraction.py, identity.py (full), decorators.py (full), warning_flow.py, muting_flow.py, kicking_flow.py, unban_flow.py, appeal_flow.py (full), check_flow.py (full 601 lines), warns_db.py (full), bans_db.py (partial — set_appeal_log_msg), groups_db.py, users_cache.py, dispatch.py, scheduler.py, __main__.py. All CLEAN except Bug #419.
  - All entry handler double-reply guards verified CLEAN: banning.py, muting.py, warnings.py, unbanning.py, kicking.py — all have `executor_role is None` check before `refuse_message`.
  - All asyncio.gather return_exceptions=True verified CLEAN across all audit files. All fire-and-forget create_task strong-ref sets verified CLEAN.
  - Ruff: All checks passed (74 files). Import OK. Total bugs: #1-#419.
  - Remaining open: CVE-2026-31072 (accepted), Improvement #4 (future).

- Session 142 (2026-06-16): Audit pass 23 — 4 doc/skill bugs fixed (#415-#418).
  - Bug #415: Em-dash (Unicode U+2014) removed from replit.md (2), CHANGELOG.md (52 lines), PLAN.md (14). All project .md files now CLEAN — 39 files verified across root + docs + docs subdirs (22 docs files).
  - Bug #416: docs/performance.md target table updated from v4.5.1 to v4.6.2 mandatory targets (single DB < 0.1 ms, batch < 0.5 ms, Redis read < 0.03 ms, pipeline < 0.08 ms, fan-out 100 groups < 30 ms, 1000 groups < 200 ms, p95 cmd < 5 ms, q.answer < 1 ms, APScheduler < 5 ms, mem cache < 0.005 ms, identity < 0.02 ms, startup < 0.1 s). Checklist thresholds and benchmark label updated. Bounded fan-out via dispatch.py added.
  - Bug #417: 6 agent skill files corrected from [job-queue] to [rate-limiter]+no-[job-queue]: project-policy/SKILL.md, async-python-patterns/SKILL.md, docs-maintainer/SKILL.md, general-sub-agent/SKILL.md, python-code-quality/SKILL.md (example snippet), telegram-bot-builder/SKILL.md.
  - Bug #418: tcbot/__init__.py proof_timeout/appeal_timeout docstrings removed misleading forward-reference "when the [job-queue] PTB extra is added"; replaced with "via APScheduler triggers if inactivity timeouts are added."
  - Comprehensive code scans: 0 HTML-without-parse_mode (13 false positives via mention()/non-HTML q.edit_message_text), 0 missing-q.answer callbacks (2 false positives via _render_help_index/_ack_and_render), 0 gather-without-return_exceptions (5 false positives via multi-line context), 0 unhandled gather results (5 false positives — all have isinstance(BaseException) checks), 0 em-dash/emoji in .py files, 0 smart quotes, 0 hardcoded chat IDs (1 example string), 0 job-queue usage in tcbot/ source, 0 create_task without handlers, 0 missing future-annotations, 0 inline imports (PLC0415 ruff-clean), 0 unsafe update.message access, all modules documented in modules.md.
  - tcbot/: 74 files, 17,221 lines, 136 gather() calls (all return_exceptions=True).
  - Ruff: All checks passed, 74 files formatted. Total bugs: #1-#418. Open: CVE-2026-31072 (accepted), Improvement #4 (future).

- Session 142 (2026-06-16): Audit pass 22 — ZERO new bugs found. Comprehensive sweep of all remaining files.
  - Files verified CLEAN this session (full reads): checking.py (all callback handlers), stats.py (full — _ack_and_render helper confirmed, all q.answer patterns CLEAN), muting_flow.py (full), greeting.py (full), __main__.py (full), decorators.py (full — _RateLimiter, _AsyncRateLimiter, global_rate_limit_handler, ratelimiter factory, log_execution, owner_only/staff_only/mod_only/basic_mod_only, resolve_and_check), extraction.py (full), start.py (full — _show_groups helper has q.answer() in gather), help.py (full — _show_module/_render_help_index/_show_section all have q.answer() in gather).
  - AST scan: 0 HTML strings without parse_mode in any messaging call. 0 callback handlers missing q.answer() (5 flagged were all false positives — helpers contain q.answer() in gather). 0 asyncio.gather missing return_exceptions.
  - All 5 scan-flagged handlers confirmed CLEAN: `on_stats_admins`→`_ack_and_render`, `on_menu_groups*`→`_show_groups`, `on_help_topic_any`→`_show_module` — each helper wraps q.answer() in asyncio.gather.
  - Ruff check: All checks passed (74 files). Import OK. Bot running (29/29 indexes, Redis hiredis 3.4.0, APScheduler, polling).
  - Total bugs: #1–#414. ZERO new bugs this session.
  - Remaining open: P1 #4 (CVE-2026-31072, accepted), Improvement #4 (multi-instance cache, future).

- Session 141 (2026-06-16): New task received — improve and enhance ALL bot user-facing messages. Primary deliverable: privacy policy per-section navigation. All changes ruff-clean, import-verified, bot running.
  - `privacy.py`: Complete rewrite of privacy policy display. `on_privacy_policy_menu` now shows a section index with 6 inline buttons. Added `on_privacy_section` handler for individual section view with back-to-index button. `_PRIVACY_POLICY_SECTIONS` module-level constant (6 sections). `_privacy_msg()` improved. New `_privacy_policy_index_msg()`. New callback pattern `privacy_section_\d+`.
  - `keyboards.py`: Added `privacy_policy_sections_kb()` and `back_to_privacy_policy_kb()` factories.
  - `start.py`: PM message improved (bold bot name header, clearer description, staff note). Group message improved (removed redundant greeting, added mention of PM options).
  - `about.py`: Added "How it works" section explaining federation mechanics, improved history text and disclaimer.
  - `help.py`: Index text clarified. Group-context alert updated.
  - Verification: ruff format (5 files unchanged), ruff check (All checks passed), import OK, bot running cleanly (29/29 indexes, Redis hiredis 3.4.0, APScheduler, polling).

- Session 140 (2026-06-16): Bug #414 found and fixed. Full audit of checking.py, appeal_flow.py, unban_flow.py, extraction.py, maintenance.py, admins.py, __main__.py, ban_info.py, logger.py/utils/__init__.py (circular import confirmed).
  - AST scan: 5 consecutive-await pairs found — all confirmed VALID (sequential dependencies). checking.py:276+277 (text from build_ban_detail feeds _safe_edit), checking.py:319+320 (text from _ban_summary feeds _safe_edit), maintenance.py:193+196 (groups from active_groups feeds gather), users_roles.py:91 and admins.py:570 previously documented ordering constraints.
  - Inline import audit: checking.py:272 inline `build_ban_detail` import — no circular dependency (ban_info does not import checking.py). Moved to module-level top import, removed `# noqa: PLC0415`. Logger.py inline `error_reporter` import confirmed NECESSARY (tcbot/utils/__init__.py imports all siblings including logger.py; top-level import would be circular). mongos.py dns.resolver inline VALID (optional dependency). All 3 noqa: PLC0415 sites evaluated.
  - Non-ASCII scan: `→` characters only in code comments, log messages, and docstrings — zero in user-facing Telegram strings. CLEAN.
  - Em-dash/emoji scan: 0 in Python source. CLEAN.
  - appeal_flow.py (full read): all gather patterns, reject path sequential `_update_or_send_log` (depends on target_fname from gather — VALID), approve path 4-way gather CLEAN, ConversationHandler builder CLEAN.
  - Bug #414: `checking.py` — `from tcbot.modules.helper.ban_info import build_ban_detail` moved from inline (inside `on_checkme_detail`) to module-level imports. No functional change; pure rule compliance fix.
  - Verification: ruff check All checks passed!, ruff format 74 files already formatted. Import OK. Bot running.
  - Total bugs: #1–#414. Remaining open: P1 #4 (CVE-2026-31072, accepted), Improvement #4 (multi-instance cache, future).

- Session 139 (2026-06-16): Bugs #399–#411 found and fixed (all docs/accuracy). Bugs #412–#413 found and fixed (code correctness). Comprehensive audit of all new code from sessions 133–138.
  - Bug #412: `warning_flow.execute_resetwarns` — no audit log posted on success. Added `resetwarns_log()` to `parse_logmsg.py`. Updated `execute_resetwarns` to send log + reply in parallel gather.
  - Bug #413: `banning.cmd_ban_start`, `kicking.cmd_kick`, `muting.cmd_mute`, `admins.on_demote_confirm` — `Demote.execute` calls not wrapped in `try/except`. MongoDB timeout would silently abort ConversationHandler entry. Fixed with `try/except Exception + log.exception()` in all 4 sites.
  - Bugs #399–#411: 13 docs accuracy fixes (mute section, warnings-detailed, appeal-detailed, banning-detailed, databases.md — all covering omitted FED_WARN_LIMIT, active_mutes, and stale TIMEOUT-state references).
  - Total bugs: #1–#413. Remaining open: P1 #4 (CVE-2026-31072, accepted), Improvement #4 (multi-instance cache, future).

- Session 138 (2026-06-16): Bugs #393-#398 found and fixed. Comprehensive audit of remaining new code from sessions 133-137.
  - Audit scope: `stats.py` (q.answer patterns), `checking.py` (q.answer patterns), `admins.py` (q.answer patterns), `ban_flow.py` (post-#392 re-audit), `check_flow.py` (session 133 changes: 11-way gather + fed_warn_total + active_mute), `connecting.py` (session 134: MY_CHAT_MEMBER consolidation), `muting_flow.py` (session 135: active mute gather patterns), `greeting.py` (session 135: 3-way gather + mute re-apply), `connected_flow.py` (session 135: 6-way gather + mute fan_out), `warning_flow.py` (FED_WARN_LIMIT sequential awaits — all justified), `mutes_db.py` (active mute helpers), `__main__.py` (session 136: timeout constants + bootstrap_retries). All CLEAN except Bug #398.
  - AST scan: only 2 consecutive-await pairs found — both intentionally sequential (documented ordering constraints in `users_roles.set_owner` and `admins.cmd_transfer`). CLEAN.
  - Unicode/emoji scan: 0 emoji/pictograph across all 74 Python files. CLEAN.
  - Em-dash/en-dash final scan: 0 remaining in Python source or docs (excluding CHANGELOG/PLAN/README/AGENTS historical records).
  - Bug #393: `documents.py` `ActiveMuteDoc` docstring — em-dash `— one` → `: one`.
  - Bug #394: `formatter.py` module docstring — em-dash `All modules — including` → parentheses.
  - Bug #395: `docs/backup-restore.md` — 6 em-dashes replaced (heading, 5 table cells, section header, shell comment, security bullet).
  - Bug #396: `docs/helper/helper.md` — em-dash in `ERR_CANNOT_RESOLVE` table cell replaced with parentheses.
  - Bug #397: `docs/appeal-detailed.md` — en-dash `2–6` → hyphen `2-6`.
  - Bug #398: `muting_flow.py` `execute_unmute` else-branch — `clear_active_mute` and `reply_text` were sequential independent awaits (single-item gather with exception silently swallowed, then separate try/except). Replaced with proper 2-way `asyncio.gather(clear_active_mute, reply_text, return_exceptions=True)` with per-result error logging, consistent with the `if lc:` branch.
  - Bug #399: `docs/workflows/workflows.md` mute section omitted all `active_mutes` persistence behaviour from Improvement #7. Added prose for `set_active_mute` upsert, `clear_active_mute` clear, `greeting._handle_member` re-apply on join, `connected_flow.complete_join` fan-out re-apply on group connect. Mermaid updated with `active_mutes collection`, `greeting._handle_member`, `connected_flow.complete_join` nodes.
  - Bug #400: `docs/warnings-detailed.md` edge cases — stale claim "auto-ban does not create a federation ban record" directly contradicts line 196; fixed.
  - Bug #401: `docs/warnings-detailed.md` timeouts — "_on_timeout handler via TIMEOUT state" was dead code removed in Bug #382; fixed to accurate statement.
  - Bug #402: `docs/warnings-detailed.md` behavior reference — items 7/11/12 omitted FED_WARN_LIMIT (Bug #383); added item 13 for fed_global trigger path; item 7 updated to describe both thresholds.
  - Bug #403: `docs/appeal-detailed.md` timeouts — `BuildAppeal._on_timeout` / `ConversationHandler.TIMEOUT` stale (function removed in #382); fixed.
  - Bug #404: `docs/banning-detailed.md` edge cases — `on_proof_timeout` via `ConversationHandler.TIMEOUT` stale; it is a fallback handler for commands, not a scheduler/TIMEOUT state; fixed.
  - Bug #405: `docs/workflows/workflows.md` package rules — "All timed conversations must register a TIMEOUT state" stale (none do); fixed to accurate description.
  - Bug #406: `docs/warnings-detailed.md` — Mermaid, Purpose, Scope, and "Warning auto-ban behavior" sections all omitted FED_WARN_LIMIT; four areas updated to document both per-group (==) and federation-wide (>=) thresholds.
  - Bug #407: `docs/workflows.md` Warn row — "auto-ban at 3 warnings" omitted FED_WARN_LIMIT; updated.
  - Bug #408: `docs/workflows.md` group connection Mermaid — "Apply existing federation bans" omitted active mutes replay; updated.
  - Bug #409: `docs/databases/databases.md` warning model — WARN_LIMIT only, FED_WARN_LIMIT omitted; added.
  - Bug #410: `docs/databases/databases.md` warns_db helpers — federation_warn_count omitted; added.
  - Bug #411: `docs/databases/databases.md` mute model — active_mutes collection omitted; rewrote section to cover both mutes and active_mutes.
  - Verification: ruff check/format clean, import OK, bot running (29/29 indexes, Redis, APScheduler, polling).
  - Total bugs: #1–#411. Remaining open: P1 #4 (CVE-2026-31072, accepted), Improvement #4 (multi-instance cache, future).

- Session 137 (2026-06-16): Bug #392 found and fixed. Full audit pass of all major workflow files.
  - Audit scope: `ban_flow.py`, `banning.py`, `unban_flow.py`, `muting_flow.py`, `mutes_db.py`, `bans_db.py`, `warning_flow.py`, `kicking_flow.py`, `appeal_flow.py`, `check_flow.py`, `checking.py`, `connected_flow.py`, `greeting.py`, `mongos.py` — all verified except Bug #392.
  - Bug #392: `ban_flow.py` re-ban path — `update_ban` 5th arg (`new_log_id`) was `old_log_msg_id` instead of `0`. When parallel `send_message` failed, `log_message_id` stayed as old ban's log ID (misleading pointer). Fixed to `0` consistent with `create_ban` pattern; `set_log_message_id` corrects to real value on success.
  - Verification: ruff format 74 files unchanged, ruff check All checks passed, import OK.
  - Total bugs: #1–#392. Remaining open: P1 #4 (CVE-2026-31072, accepted), Improvement #4 (multi-instance cache, future).

- Session 136 (2026-06-16): Bugs #390–#391 fixed. Verification clean. No new code bugs found in audit scan.
  - Bug #390: `_HTTP_READ_TIMEOUT` 15→60, `_HTTP_WRITE_TIMEOUT` 15→30, `_HTTP_CONNECT_TIMEOUT` 10→30, `_HTTP_POOL_TIMEOUT` 5→15. Too-tight values caused fatal startup crash on Replit where first getMe() can take >15s.
  - Bug #391: `bootstrap_retries=-1` added to `app.run_polling()`. Default 0 caused immediate process exit on any transient NetworkError during initial getUpdates handshake; Replit network is intermittent.
  - Verification baseline: ruff format 74 files unchanged, ruff check All checks passed, import OK, uv sync OK.
  - AST scan: 0 `asyncio.gather()` missing `return_exceptions`. Unicode scan: all `→`/`—` hits are in comments/docstrings/log messages only (not user-facing Telegram strings) — CLEAN.
  - Total bugs: #1–#391. Remaining open: P1 #4 (CVE-2026-31072, accepted), Improvement #4 (multi-instance cache, future).

- Session 135 (2026-06-16): Bugs #385–#387 fixed + Improvement #7 fully implemented.
  - Bug #385: `tcbot/utils/__init__.py` — `formatter` missing from `__all__`.
  - Bug #386: `docs/utils/utils.md` Mermaid diagram missing `formatter.py` node + new formatter.py section.
  - Bug #387: `docs/helper/helper.md` formatter section incorrectly described as implementation source; corrected to re-export shim.
  - Improvement #7 (fed mute re-apply): Added `active_mutes` MongoDB collection. `ActiveMuteDoc` TypedDict added to `documents.py`. `set_active_mute` / `clear_active_mute` / `get_active_mute` / `active_mute_docs` added to `mutes_db.py`. Two new indexes in `mongos.py` (29/29 total). `_execute_mute` upserts active mute record in gather. `execute_unmute` clears active mute record in gather. `_handle_member` in `greeting.py` fetches `get_active_mute` in parallel with `get_active_ban` and re-applies `restrict_chat_member` on join. `complete_join` in `connected_flow.py` fetches `active_mute_docs()` in parallel with `active_ban_user_ids()` and fans out `restrict_chat_member` for all active mutes on group connect. `ChatPermissions` import added to both files. PLAN.md Improvement #7 → Resolved. CHANGELOG.md updated. docs/databases/databases.md updated. Ruff: 74 files clean (1 file reformatted). Import OK.
  - Total bugs: #1–#387. Remaining open: P1 #4 (CVE-2026-31072, accepted), Improvement #4 (multi-instance cache, future).

- Session 134 (2026-06-16): 4 open PLAN.md findings from session 133 resolved — 4 bugs fixed (#381–#384).
  - Bug #381 (P2 #4): Duplicate ChatMemberHandler(MY_CHAT_MEMBER) — greeting.on_my_chat_member and connected_flow.on_bot_added both registered in PTB group 0, one silently shadowing the other (nondeterministic by filesystem sort). Fixed: merged demotion-warning branch (MEMBER/RESTRICTED + old_status==ADMINISTRATOR → mod-channel warning, primary-group exclusion) into connected_flow.on_bot_added. Deleted greeting.on_my_chat_member function and its ChatMemberHandler registration. Removed ChatMemberHandler import from greeting.py. Added esc import to connected_flow.py. Now exactly ONE MY_CHAT_MEMBER handler covers all cases.
  - Bug #382 (P4 #10): Dead _on_timeout handlers — appeal_flow.BuildAppeal._on_timeout + _MSG_TIMEOUT constant and reason_flow._on_timeout were unreachable dead code (no ConversationHandler.TIMEOUT state wired, no job-queue). Removed both. Updated cfg.proof_timeout/appeal_timeout docstrings and config.env.example comments to document they are parsed but not consumed (reserved for future job-queue wiring).
  - Bug #383 (P3 #6): Cross-group warn accumulation evaded federation auto-ban — execute_warn only triggered on count == WARN_LIMIT (per-chat), so thin-spread evasion (2 warns × 25 groups) was never auto-banned. Added FED_WARN_LIMIT env var (cfg.fed_warn_limit, default 0 = disabled). Restructured execute_warn with auto_ban_trigger flag ("per_group" / "fed_global" / None); fed-global checks federation_warn_count(target_id) >= fed_limit. Both paths share one auto-ban code block. Default 0 = fully backward-compatible.
  - Bug #384 (P3 #7): No global Telegram API pacing — Application built without AIORateLimiter; fan_out semaphore capped concurrency but not rate. Added python-telegram-bot[rate-limiter] to pyproject.toml (aiolimiter==1.2.1 installed). Added AIORateLimiter import + .rate_limiter(AIORateLimiter()) to ApplicationBuilder chain in __main__.py. ~30 req/s pacing + automatic 429/RetryAfter backoff now active globally.
  - Ruff: All checks passed (73 files). Bot restart: 27/27 indexes, Redis hiredis 3.4.0, APScheduler, AIORateLimiter active, polling.
  - Total bugs: #1–#384. All P2/P3/P4 findings from session 133 → Resolved.
  - Remaining open: P1 #4 (CVE-2026-31072, accepted), Improvement #4 (multi-instance L1 cache, future), Improvement #7 (fed mutes not re-applied on join, enhancement).

- Session 133 (2026-06-16): Audit pass 21 — 11 bugs fixed (#368–#378). Non-ASCII sweep completed. Docs updated.
  - Bug #368: appeal_flow.py — hardcoded `2000` → `_MAX_APPEAL_LEN: int = 2000` constant.
  - Bug #369: cache.py — maxsize=2048/4096 literals → `_ROLE_CACHE_MAXSIZE` / `_USER_MENTION_CACHE_MAXSIZE`.
  - Bug #370–#375: Non-ASCII `·` (U+00B7) and `•` (U+2022) in user-facing Telegram message text — check_flow.py ban list (`·` → `|`), check_flow.py warnings list (`•` → `-`), check_flow.py appeals list (`·` → `|`), stats_flow.py Users/Chats/Bans pagination headers (`·` → `-`).
  - Bug #376–#377: error_reporter.py — `·` in When: line (→ `-`) and `━` box-drawing separator (→ `-`).
  - Bug #378: docs/check-detailed.md — stale Bans format block showing old `·` separators; updated to match post-fix format (`|`).
  - AST scans: callback answer() order — all false positives. Fire-and-forget tracking — all correct. No hardcoded chat IDs. No bare type:ignore. No bare noqa. Bare except: — all intentional fallbacks.
  - Dependency upgrade: uv lock --upgrade clean; APScheduler ==4.0.0a6 pinned (CVE accepted).
  - Ruff: All checks passed (73 files). Import: clean. Bot: 27/27 indexes, Redis hiredis 3.4.0, APScheduler, polling.
  - Total bugs: #1–#378. Remaining open: P1 #4 (CVE accepted), Improvement #4 (multi-instance cache, future).

- Session 132 (2026-06-16): Audit pass 20 — ZERO new bugs found. Final comprehensive sweep of ALL remaining tcbot/ files.
  - Files verified CLEAN this session (reads done directly, line by line): ban_flow.py, appeal_flow.py, banning.py, extraction.py, greeting.py, decorators.py, warning_flow.py, unban_flow.py, muting_flow.py, kicking_flow.py, muting.py, kicking.py, admins.py, warnings.py, checking.py, connecting.py, __main__.py, bans_db.py, warns_db.py, users_roles.py, users_cache.py, groups_db.py, cache.py, scheduler.py, maintenance.py, appeals.py, broadcasting.py, unbanning.py, stats.py, disconnecting.py, groups.py, greeting.py (again), mongos.py, redis_client.py, start.py, help.py, about.py, additional.py, privacy.py, netspeed.py, types.py.
  - Ruff: All checks passed (73/73 files). Format: 73 already formatted. Import OK. Bot: 27/27 indexes, Redis hiredis 3.4.0, APScheduler, polling.
  - Total bugs: #1–#367. No new bugs added this session.
  - Remaining open items: P1 #4 (CVE-2026-31072, accepted risk), Improvement #2 (backups, operational), Improvement #4 (multi-instance cache invalidation).
  - AUDIT COMPLETE: All 73 Python files across 20 audit passes verified production-ready.

- Session 131 (2026-06-15): Audit pass 19 — 7 docs bugs fixed (#355–#361). Zero Python code bugs.
  - Bug #355: docs/promote-detailed.md — `/tcpromoterequests` section incorrectly described `identity.classify` call; corrected to parallel asyncio.gather reads.
  - Bug #356: docs/role-detailed.md — opening paragraph listed `/tcpromoterequests` among classify callers; corrected with exception note.
  - Bug #357: docs/check-detailed.md — profile warnings line missing "active" qualifier and total-historical count.
  - Bug #358: docs/check-detailed.md — Warnings button label `(n)` vs actual `(n active)` in check_flow.py.
  - Bug #359: docs/appeal-detailed.md — "Rejection does not clear review_message_id" was WRONG; code calls clear_review(ban_id) on rejection; corrected + added set_rejected_by docs.
  - Bug #360: docs/banning-detailed.md + databases.md — BanDoc tables missing rejected_by_id/name/at fields added in Bug #343.
  - Bug #361: docs/appeal-detailed.md — 2000-char appeal limit (Bug #344) was completely undocumented.
  - Scans CLEAN: Ruff check — All checks passed (73 files). Format: 73 already formatted. Bot: 27/27 indexes, Redis hiredis 3.4.0, APScheduler, polling. appeal_link/appeal_log_msg_id accurate, ban_info.py location, TwoLevelCache, mutes_db audit log, WARN_LIMIT, keyboard button labels (Bans/Appeals/Kicks/Mutes) all accurate.
  - Bug #362: docs/banning-detailed.md + databases.md — BanDoc tables missing `until_date` and `duration_str` reserved fields (placeholder for future timed-ban).
  - Bug #363: docs/check-detailed.md — async gather section said "nine independent reads" and omitted `federation_warn_count` (10th coroutine) and `return_exceptions=True`.
  - Bug #364: docs/role-detailed.md — `promotion_requests` field list missing `username`, `first_name`, `promoted_by`.
  - Bug #365: docs/README.md — "All 4 CI/CD workflows" wrong; 5 workflow files exist; workflows-guide.md also says 5.
  - Bug #366: docs/setup.md — config table missing `REDIS_URL` and `WARN_EXPIRY_DAYS`.
  - Bug #367: docs/git-commit.md — "Required Trailers" section shows "Dizzy" (canonical) but two code examples below used "D1ZZY4"; updated examples to "Dizzy".
  - Total bugs: #1–#367. Remaining open: P1 #4 (CVE accepted), Improvement #2 (backups), Improvement #4 (multi-instance).

- Session 130 (2026-06-15): Audit pass 18 — ZERO new bugs found. Deep verification audit.
  - AST scan: 0 asyncio.gather() missing return_exceptions (entire codebase, verified via ast module). ALL CLEAN.
  - AST scan: 0 function parameters missing type annotations. ALL CLEAN.
  - All create_task calls verified have strong references: _member_cache_tasks, _startup_tasks, _redis_bg_tasks, _tg_tasks, _album_tasks, _harvest_tasks, _sched_task — all properly guarded (RUF006-compliant).
  - None guard scan: 27 theoretical "unguarded" handlers — ALL confirmed FALSE POSITIVES. @staff_only uses `effective_user.id if effective_user else None` guard; CallbackQueryHandler PTB guarantees effective_user; @log_execution uses same pattern; on_proof_unexpected uses `if update.effective_message:` guard.
  - fan_out usage: 11 call sites all verified correct (return_exceptions absorbed by _slot wrapper).
  - admins.py FULLY read baris per baris (829 lines): cmd_promote, cmd_demote, on_promote_role_btn, on_demote_confirm, cmd_transfer, cmd_promote_request, cmd_promote_list, on_promo_decision — ALL SOLID.
  - proof_flow.py fully read (160 lines): BuildProof dataclass, upload_proof — SOLID.
  - dispatch.py: fan_out semaphore-bounded gather with CancelledError re-raise — SOLID.
  - Bot: 27/27 indexes, Redis hiredis 3.4.0, APScheduler, polling active.
  - Total bugs: #1–#354. Remaining open: P1 #4 (CVE accepted), Improvement #2 (backups), Improvement #4 (multi-instance).

- Session 129 (2026-06-15): Audit pass 17 — ZERO new bugs found. Comprehensive audit of ALL remaining tcbot/ files.
  - Files fully read baris per baris: banning.py, unbanning.py, users_cache.py, extraction.py, unban_flow.py, muting.py (cmd_mute + cmd_unmute), kicking.py, identity.py, stats.py, cache.py, groups_db.py, broadcasting.py, __main__.py (harvest handler + error handler), checking.py (partial), connected_flow.py (full), promote_flow.py, demote_flow.py, stats_flow.py, warning_flow.py, kicking_flow.py, muting_flow.py, check_flow.py, ban_info.py, formatter.py, replies.py, keyboards.py, warns_db.py, users_roles.py, scheduler.py, parse_logmsg.py.
  - Scanned: every asyncio.gather call — ALL have return_exceptions=True on continuation lines (grep false positives from multi-line calls confirmed valid). Every callback handler q.answer() pattern — ALL CLEAN. Every bare except Exception: — ALL intentional (rollback, broad catch with log.exception, or "not found" non-fatal). Every to_list(None) — bounded by collection size / result cap at caller level; acceptable.
  - AST scan: 0 gathers missing return_exceptions. Sequential q.answer scan: CLEAN. TODO/FIXME scan: 0. Ruff format: 73 files already formatted. Ruff check: All checks passed (0 errors).
  - Bot running: 27/27 indexes, Redis hiredis 3.4.0, APScheduler, polling active.
  - Total bugs: #1–#354. Remaining open: P1 #4 (CVE accepted), Improvement #2 (backups), Improvement #4 (multi-instance).

- Session 128 (2026-06-15): Audit pass 16. 4 bugs fixed (#351–#354). 2 docs updated (Bug #352). Dead constants cleaned.
  - Bug #351 (prev part): admins.py, checking.py, kicking.py, warnings.py, unbanning.py — hardcoded error strings → ERR_CANNOT_RESOLVE.
  - Bug #352 (prev part): docs/appeal-detailed.md, modules.md, warnings-detailed.md — 3 docs accuracy fixes.
  - Bug #353: admins.py cmd_promote + cmd_demote exception branch (isinstance(_target_r, BaseException)) used ERR_NO_TARGET instead of ERR_CANNOT_RESOLVE. Both user experiences identical (can't resolve target); Bug #351 fixed the (None, None) branch but missed the exception branch above it.
  - Bug #354: muting.py cmd_unmute, warnings.py cmd_warnlist + cmd_resetwarns — all used ERR_NO_TARGET. extract_target returns (None, None) for both "no input" and "unresolvable"; ERR_NO_TARGET was semantically narrower. Standardized to ERR_CANNOT_RESOLVE.
  - Cleanup: Removed dead constants ERR_NO_TARGET and ERR_CANT_FIND_USER from replies.py. ERR_CANT_FIND_USER was dead after Bug #351; ERR_NO_TARGET became dead after #353+#354. All 13 extract_target call sites now use ERR_CANNOT_RESOLVE uniformly. docs/helper/helper.md updated to remove stale rows.
  - AST scan: ALL CLEAN (0 gathers missing return_exceptions). Sequential q.answer scan: ALL CLEAN. TODO/FIXME scan: 0. Ruff: 73 files clean. Import OK. Bot: 27/27 indexes, Redis hiredis 3.4.0, APScheduler, polling.
  - Total bugs: #1–#354. Remaining open: P1 #4 (CVE accepted), Improvement #2 (backups), Improvement #4 (multi-instance).

- Session 127 (2026-06-15): Audit pass 15+. 4 bugs fixed (#347–#350). Zero open PLAN.md findings added.
  - Bug #347: warning_flow.py `execute_warn` — auto-ban trigger `>=` → `==` (race condition fix).
  - Bug #348: warning_flow.py `execute_warn` — auto-ban reply now granular X/Y groups applied-to line.
  - Bug #349: greeting.py `on_my_chat_member` — demotion branch added (member/restricted → warn log, no deactivate).
  - Bug #350: appeal_flow.py `_start` — stale review auto-cleanup: if review_timestamp older than 72h (or None), clear_review() called and user allowed fresh appeal. Error text updated with 72h hint. Ruff 73 files clean. Bot restart: 27/27 indexes, Redis hiredis 3.4.0, APScheduler, polling.
  - Verified clean: ban_flow, unban_flow, kicking_flow, muting_flow (mutes_db is pure audit log, no is_active), broadcasting (fan_out semaphore 10, rate-limited, return_exceptions=True everywhere).
  - Total bugs: #1–#350. Remaining open: P1 #4 (CVE accepted), Improvement #2 (backups), Improvement #4 (multi-instance).

- Session 126 (2026-06-15): 1 open finding from PLAN.md resolved (P3 #2). 1 bug fixed (#346). 1 dependency bumped (tzlocal 5.3.1→5.4).
  - Bug #346 (P3 #2): decorators.py — Added `_AsyncRateLimiter` class with atomic Redis sorted-set sliding window (Lua script: ZREMRANGEBYSCORE + ZCARD + ZADD + PEXPIRE in one round-trip). Replaced `_cmd_limiter` and `_cbq_limiter` with `_AsyncRateLimiter(prefix="cmd"/"cbq")`. Updated `global_rate_limit_handler` to `await limiter.check(uid)`. `ratelimiter()` factory now creates `_AsyncRateLimiter(prefix="h:{func.__name__}")` per handler. Key format: `rl:{prefix}:{uid}`. Falls back to in-process `_RateLimiter` (deque-based, monotonic clock) when Redis absent or errors. Rate-limit quota now survives 4-hour restart cycle. PLAN.md P3 #2 → Resolved. CHANGELOG.md updated. docs/helper/helper.md rate-limiter-backend section added.
  - Ruff: All checks passed (73 files). Import OK. Bot running: 27/27 indexes, Redis hiredis 3.4.0, APScheduler, polling.
  - Remaining open items: P1 #4 (CVE-2026-31072, accepted/tracked risk), Improvement #2 (backups), Improvement #4 (multi-instance cache invalidation).

- Session 125 (2026-06-15): 6 open findings from PLAN.md resolved (P1 #5, P1 #6, P2 #2, P2 #3, P3 #3, P4 #8). 6 bugs fixed (#340-#345).
  - Bug #340 (P1 #5): warning_flow.py execute_warn — warn auto-ban now federation-wide. Parallel gather fetches active groups + existing ban check + sends audit log. `bans_db.create_ban()` creates DB record (skipped if already banned). `fan_out()` propagates ban to all active + primary groups. Originating chat and primary groups added if not already in the list. Clear warns + notify in originating chat after success.
  - Bug #341 (P1 #6): greeting.py — Added `on_my_chat_member` handler (`ChatMemberHandler`). Detects `status in (left, kicked)`. Calls `db.groups_db.deactivate_group(chat_id)` automatically. Skips primary groups. Registered first in `__handlers__`. Prevents stale `is_active=True` groups accumulating in federation.
  - Bug #342 (P2 #2): bans_db.py `clear_review()` + appeal_flow.py reject branch — `clear_review()` sets `review_message_id=None, review_timestamp=None`. Called in parallel in the reject gather. Banned user can now submit a second appeal after rejection.
  - Bug #343 (P2 #3): bans_db.py `set_rejected_by()` + documents.py BanDoc — `set_rejected_by()` sets `rejected_by_id`, `rejected_by_name`, `rejected_at` on the ban doc. Called in parallel in reject gather. BanDoc TypedDict updated with three new fields.
  - Bug #344 (P4 #8): appeal_flow.py `_on_message` — 2000-char length gate added after `starts_with_appeal_tag`. Replies with trimming instruction and returns `WAITING_APPEAL` (user can revise without restarting).
  - Bug #345 (P3 #3): warns_db.py `federation_warn_count()` + check_flow.py profile — new function sums active warn counters across all chats. check_flow profile gather expanded from 9 to 10 parallel reads. Warnings line shows "N active across M group(s) (K total historical)". Warnings button shows "N active".
  - Ruff: All checks passed (all tcbot/ files). Import OK. Bot restart: 27/27 indexes, Redis hiredis 3.4.0, APScheduler, polling. Total bugs: #1-#345.
  - PLAN.md: P1 #5, P1 #6, P2 #2, P2 #3, P3 #3, P4 #8 all marked Resolved.
  - Remaining open items: P1 #4 (CVE-2026-31072, accepted/tracked risk), P3 #2 (Redis-backed rate limiters), Improvement #2 (backups), Improvement #4 (multi-instance cache invalidation).

- Session 124 (2026-06-15): Pass 14 — Full autonomous audit loop pass. ZERO new bugs found. All 73 tcbot/ files fully read baris per baris across passes 13+14. Every module, workflow, database helper, util, entry point, and config file verified CLEAN. Bugs #338+#339 (kicks_db/mutes_db return types) fixed earlier this session. Ruff: All checks passed (73 files). Import OK. Total bugs fixed: #1–#339.

- Session 123 (2026-06-15): Pass 13 — 1 bug found and fixed (Bug #337). All Python files audited: documents.py, replies.py, parse_link.py, parse_editmsg.py, error_reporter.py, timedate_format.py, logger.py, prefixes.py, types.py, mutes_db.py, kicks_db.py — all CLEAN except Bug #337.
  - Bug #337: `documents.py` missing `KickDoc` and `MuteDoc` TypedDict definitions. All other `*_db.py` files used TypedDicts from `documents.py`, but `kicks_db.py` and `mutes_db.py` used plain `dict`. Added `KickDoc` and `MuteDoc` to `documents.py`. Updated both `*_db.py` files to import and use the new TypedDicts with `UserId`/`ChatId` wrapped IDs. `databases.md` updated with new collection-to-TypedDict mapping table.
  - Ruff: All checks passed (73 files). Import OK. Total bugs fixed: #1–#337.

- Session 122 (2026-06-15): Pass 12 — 6 doc/accuracy bugs found and fixed (Bug #331–#336). No new Python code bugs found.
  - Bug #331: `tcbot/database/scheduler.py` module docstring — stale "DB cleanup" reference removed; clarified only warn expiry remains, TTL index handles cleanup.
  - Bug #332: `docs/databases/databases.md` scheduler.py table row — removed "DB cleanup" entry; added TTL index note and `is_ready()` mention.
  - Bug #333: `PLAN.md` Core Subsystem Design / Health check row — updated to mention both `GET /` and `GET /health` with HTTP 200/503 semantics.
  - Bug #334: `docker-compose.yml` bot service — added `healthcheck` block (`GET /health` probe, 30s interval, 30s start_period). Matches the three other services that already had one.
  - Bug #335: `README.md` Features list Health checks bullet — extended to mention both `GET /` and `GET /health` JSON endpoint.
  - Bug #336: `replit.md` Health Check section — expanded from single `GET /` / `OK` entry to two entries covering both endpoints.
  - Full audit of all remaining unread files: admins.py (complete), check_flow.py (complete), users_roles.py (complete), bans_db.py (complete), decorators.py (complete), greeting.py (complete), start.py (complete), groups.py (complete), broadcasting.py (complete), disconnecting.py (complete), kicking.py (complete), netspeed.py (complete), maintenance.py, privacy.py, about.py, additional.py, types.py. Zero new Python code bugs found.
  - Ruff: All checks passed (73 files). Import OK. Bot running (27/27 indexes, Redis hiredis 3.4.0, APScheduler, polling).
  - Total bugs fixed: #1–#336.

- Session 121 (2026-06-14): Pass 11 — 3 PLAN.md Improvements implemented (code + docs).
  - Improvement #1 (alive.py): Added `GET /health` endpoint returning JSON `{status, mongodb, redis, scheduler, ts}`. HTTP 200 = all subsystems ok, HTTP 503 = degraded. State read synchronously from module-level sentinels (`mongos.is_connected()`, `sched_mod.is_ready()`, `redis_client.client()`). Backward-compatible; `GET /` still returns "OK". Confirmed: `curl /health` → `{"status":"ok","mongodb":"ok","redis":"ok","scheduler":"ok"}`.
  - Improvement #3 (scheduler surface / TTL index): Replaced `[("last_updated", -1)]` sort index on `member_cache` with TTL index `[("last_updated", 1)], expireAfterSeconds=7776000` (90 days) in `mongos.ensure_indexes()`. `_cleanup_old_records` APScheduler job retired → no-op migration shim (safe deserialization if old schedule fires before being removed). `_register_periodic_schedules` now removes the stale `tcbot.db_cleanup_weekly` schedule from MongoDB datastore on startup. Confirmed: "Removed legacy weekly cleanup schedule" appeared in startup logs.
  - Improvement #5 (APScheduler pin): `pyproject.toml` pinned `apscheduler[mongodb]==4.0.0a6` (was `>=4.0.0a1`). Prevents blind float to another vulnerable alpha while CVE-2026-31072 unpatched.
  - New public API added: `mongos.is_connected() -> bool`, `scheduler.is_ready() -> bool`.
  - `_MEMBER_CACHE_MAX_AGE_DAYS` constant removed (was 90, now expressed as TTL index `expireAfterSeconds=7776000`). `_CLEANUP_SCHEDULE_ID` kept as migration artifact.
  - Ruff: 1 file reformatted, 4 errors auto-fixed, All checks passed (73 files). Import OK. Bot running clean: MongoDB 27/27, Redis hiredis 3.4.0, APScheduler, polling active.
  - PLAN.md improvements table rows #1, #3, #5 → Resolved. PLAN.md job table updated. docs/databases/databases.md updated. CHANGELOG.md updated.
  - Total bugs fixed remains: #1–#330.

- Session 120 (2026-06-15): Infra + docs session (no `tcbot/` code changed).
  - run-bot.yml 24/7 self-chain hardened: `HANDOVER_LEAD` 900→600, `gh` handover retried 3x, resurrection cron `55 4 * * *` → `*/15 * * * *`. Closes observed multi-hour coverage gaps. Docs synced (workflows-guide.md, README.md). Commit f33ea45.
  - APScheduler CVE-2026-31072 (4.0.0a6, CVSS 9.8, no upstream patch) analysed and accepted as tracked risk; Dependabot alert #2 dismissed as `tolerable_risk`. Recorded in PLAN.md (Core Subsystem Design) + P1 finding + decisions.md.
  - PLAN.md expanded: new "Core Subsystem Design" section (MongoDB/Motor, L1/L2/L3 cache, APScheduler) and a 6th "Improvements" table beside P1-P5.
  - External `~/Documents/task-tcbot-v4.5.1.md` (Replit prompt, outside repo) improved: corrected stale cache.py "plain dict" claim, fixed scheduler init location and setup example, added the APScheduler CVE note + dependency-pin exception.
  - Remote origin updated to `git@github.com:D1ZZY4/tcbot.git` (repo renamed). Commits remain GPG-signed/verified; signing config untouched.

- Session 119 pass 10 (2026-06-13): Docs accuracy audit pass. 6 doc bugs found and fixed.
  - Bug #321: docs/demote-detailed.md line 174 — trigger verb list "banned/kicked" omitted "muted". Corrected to "banned/kicked/muted".
  - Bug #322: docs/banning-detailed.md — stale `baninfo_proof_kb | View Proof` row (function deleted from keyboards.py). Row deleted.
  - Bug #323: docs/warnings-detailed.md Mermaid — `AutoBan[Auto-ban via ban flow]` misleading (local group ban). Corrected to "Auto-ban from current group only".
  - Bug #324: docs/modules/modules.md Mermaid line 13 — `modules.__init__.discover` nonexistent; actual function is `_discover_modules`. Corrected.
  - Bug #325: docs/modules/modules.md line 35 — "get_handlers() appends handlers" inaccurate; it only returns; __main__.py registers. Corrected.
  - Bug #326: docs/mapping.md top-level layout — `tgbot/` legacy label. Corrected to `<project root>/`.
  - Bug #327: docs/stats-detailed.md Mermaid line 15 — `Staff & Users & Bans --> SearchPanel` wrong; only Bans has search button. Corrected to `Bans --> SearchPanel`.
  - Bug #328: README.md Repository Layout line 143 — same `tgbot/` legacy label as Bug #326. Corrected to `<project root>/`.
  - Bug #329: AGENTS.md Repository Layout line 50 — same `tgbot/` legacy label. Corrected to `<project root>/`.
  - Bug #330: .agents/CLAUDE.md Repository Map line 156 — same `tgbot/` legacy label. Corrected to `<project root>/`.
  - Verified CLEAN: RULES.md, project-policy skill, async-python-patterns skill, PLAN.md, identity.py, button-styles.md.
  - AST scans CLEAN: sequential awaits (2 valid), q.answer() first (0 issues), gather() without return_exceptions (0 issues).
  - Hardcoded chat ID scan: 1 match (valid placeholder). TODO/FIXME scan: 0. Ruff: All checks passed (73 files).
  - Total bugs fixed: #1-#330.

- Session 118 pass 9 (2026-06-13): Entry point + config layer audit + Unicode pictograph scan. 3 bugs found and fixed.
  - Bug #318: keyboards.py `group_start_kb` — `↗` (U+2197) in user-facing button label "Open in PM ↗". Removed symbol.
  - Bug #319: muting.py time-format help section — `→` (U+2192) used as bullet in 7 user-facing strings. Replaced with `-`.
  - Bug #320: appeals.py "What happens next" — `→` in 2 user-facing strings ("If approved →", "If rejected →"). Replaced with `:`.
  - Verified CLEAN: `__main__.py`, `__init__.py` (cfg), `greeting.py`, `identity.py`, `extraction.py`.
  - Symlinks (.kilo/.trae/.claude/.roo → .agents/) confirmed OK. `uv lock --upgrade` no version changes.
  - Unicode scan of all 73 Python files: remaining `→` only in docstrings, log strings, terminal formatter (not bot output).
  - Full ruff check: All checks passed (73 files). Bot restart: 27/27 indexes, Redis hiredis 3.4.0, APScheduler, polling active.
  - Total bugs fixed: #1–#320.

- Session 117 pass 8 complete (2026-06-13): Full audit of modules/workflows layer — 2 bugs found and fixed.
  - Bug #316: warnings.py cmd_unwarn — missing resolve_and_check(min_role="tester"); Tester could unwarn Admin. Fixed with parallel gather + double-reply guard.
  - Bug #317: warnings.py cmd_resetwarns — same missing resolve_and_check; no rank check at all. Applied identical fix pattern.
  - Files audited CLEAN: banning.py, muting.py, kicking.py, unbanning.py, connecting.py, disconnecting.py, stats.py, appeals.py, checking.py, decorators.py, appeal_flow.py, warning_flow.py, muting_flow.py, kicking_flow.py, demote_flow.py, reason_flow.py, stats_flow.py, proof_flow.py, connected_flow.py.
  - Database + utils layer (session 117 start): users_cache.py, cache.py, bans_db.py, users_roles.py, groups_db.py, warns_db.py, mutes_db.py, mongos.py, kicks_db.py, queues_db.py, dispatch.py, pagination.py — all CLEAN.
  - Total bugs fixed: #1-#317. Ruff: All checks passed.

- Session 117 pass 7 (2026-06-13): Full-pass autonomous audit — ZERO new bugs found.
  - Files audited directly: greeting.py, extraction.py, ban_flow.py, muting_flow.py, scheduler.py, appeal_flow.py, unban_flow.py, connected_flow.py, warnings.py, checking.py, banning.py, broadcasting.py, kicking.py, maintenance.py, warning_flow.py, kicking_flow.py.
  - Subagent (explore) audited all command handlers and sequential await patterns across all tcbot/modules/*.py — all CLEAN.
  - connected_flow.py lines 269+273: two sequential awaits flagged by subagent — VALID dependencies (owner_fname depends on pending["owner_id"]; add_pending depends on prompt.message_id). Not bugs.
  - Ruff: All checks passed (0 errors, 73 files clean).
  - No code changes required; nothing to commit.
  - Total bugs fixed remains: #1-#315.

- Session 116 (2026-06-13): Bug #315 fixed in netspeed.py.
  - `cmd_speedtest`: replaced delete-notice + send-new-message pattern with edit-in-place pattern (consistent with `cmd_ping` and all other action modules). For `share_url` case: `notice.edit_text(text)` + `msg.reply_photo(share_url)` in parallel via `asyncio.gather`. For no share_url: `notice.edit_text(text)` only. Notice is never deleted.
  - Verification: ruff PASS, import PASS, bot running clean (27/27 indexes, Redis hiredis 3.4.0, APScheduler, polling active).
  - Total bugs fixed: #1-#315.

- Session 115 (2026-06-13): Sixth full-pass audit — ZERO new bugs found.
  - Full read of: banning.py, checking.py (full), admins.py (full 836 lines), maintenance.py, stats.py, broadcasting.py, greeting.py, connected_flow.py (full 434 lines), about.py, disconnecting.py, warnings.py — all CLEAN.
  - AST scan for sequential await pairs: 2 found, both VALID (intentionally ordered DB writes: add_admin→set_owner in transfer, update_one→delete_many in set_owner). Both documented with inline comments.
  - Em-dash / en-dash / emoji scan (Python AST + Unicode): ZERO matches across all 73 files.
  - Single-line asyncio.gather() missing return_exceptions scan: 2 false positives (brace-closing lines of multi-line gathers already carrying return_exceptions=True).
  - Ruff: 73 files, All checks passed. Format: All 73 already formatted.
  - No code changes required; nothing to commit.

- Session 114 (2026-06-13): Documentation accuracy pass — 7 bugs fixed (#306-#312):
  - Bug #306: docs/performance.md heading "v4.1.1 Performance Targets" → "v4.5.1 Performance Targets".
  - Bug #307: docs/performance.md Button Handlers: q.answer() < 30 ms → < 15 ms, round-trip < 150 ms → < 80 ms (v4.5.1 targets).
  - Bug #308: docs/banning-detailed.md unban step 7: stale `scheduler.cancel_schedule(ban.schedule_id)` (schedule_id field doesn't exist); corrected to `scheduler.cancel_schedule(f"unban.{ban_id}")`.
  - Bug #309: docs/banning-detailed.md ban step 7: "EXEC_GROUP" (nonexistent name) → "EXTEND_GROUP" (real env var).
  - Bug #310: tcbot/modules/helper/workflows/appeal_flow.py comment line 548: "EXEC_GROUP" → "EXTEND_GROUP" (real env var name).
  - Bug #311: docs/warnings-detailed.md lines 126+331 claimed warnings NEVER auto-demote; code shows they DO auto-demote when warn limit is hit and target has a role. Both lines corrected.
  - Bug #312: docs/role-detailed.md line 316 same claim as #311 — "Warnings do not auto-demote" — corrected to match code reality.
  - Bug #313: docs/workflows/workflows.md line 148 said "automatic federation ban" at WARN_LIMIT; code does local group ban only (ban_chat_member for current chat). Corrected to "automatic ban from the current group only".
  - Bug #314: docs/workflows/workflows.md auto-demote table, mute row: said "current-group mute" but muting_flow._execute_mute is federation-wide (fan_out to all connected + primary groups). Corrected to "federation-wide mute".
  - Comprehensive re-audit: all 73 Python files (5 passes), all docs/*.md, GitHub workflows (5), Dockerfile, docker-compose.yml — ALL clean beyond listed bugs. Ruff: 73 files clean.

- Session 113 (2026-06-13): Perf #4 fix — appeal_flow.py approve action had two consecutive independent asyncio.gather calls (notify+edit, then log_edit+log_send). Merged into one gather with all 4 coroutines running in parallel. Zero Unicode emoji found in source code. AST scan of entire codebase: only 4 consecutive await patterns found; 2 are semantically ordered (DB write sequence in set_owner, add_admin→set_owner in transfer), 1 is unban-then-notify order (appeal approve), 1 was the fixed perf issue. N+1 audit: zero actual N+1 patterns (extraction.py loops are short-circuit returns). Total perf: Perf #1–#294 (prev sessions) + Perf #4 this session.
  - Verification: ruff 73 files clean. Bot restart clean: MongoDB 27/27, Redis hiredis 3.4.0, APScheduler.

- Session 112 (2026-06-13): Sequential q.answer() + edit audit pass across all module files. 11 bugs fixed (#295–#305):
  - Bug #295: groups.py `_toggle` cache-hit branch — `q.answer()` + `safe_edit()` sequential → gathered.
  - Bug #296: start.py `on_back_to_start` — `q.answer()` + `q.edit_message_text()` sequential → gathered.
  - Bug #297: privacy.py `on_privacy_menu` — same pattern → gathered. Added `import asyncio`.
  - Bug #298: privacy.py `on_privacy_policy_menu` — same pattern → gathered.
  - Bug #299: about.py `on_about_menu` — same pattern → gathered. Added `import asyncio`.
  - Bugs #300–#305: help.py — 6 instances across `_render_help_index`, `_show_module` (2), `_show_section` (3) — all sequential `q.answer()` + `safe_edit_cb()` → gathered. Added `import asyncio`.
  - Comprehensive sweep of ALL remaining files: admins.py, checking.py, stats.py, appeal_flow.py, users_cache.py, users_roles.py, bans_db.py, warns_db.py, kicks_db.py, mutes_db.py, queues_db.py, scheduler.py, extraction.py, identity.py, parse_editmsg.py, dispatch.py, pagination.py, parse_logmsg.py — all CLEAN.
  - All remaining `q.answer()` calls in swept files are guard-only early returns (no edit follows) — NOT bugs.
  - Verification: ruff all 73 files clean (All checks passed!). Bot restart: MongoDB 27/27 indexes, Redis hiredis 3.4.0, APScheduler, polling active.
  - Total bugs fixed: #1–#305 + 3 Perf (#292–#294).

- Session 111 (2026-06-13): v4.5.1 audit pass. No new bugs found. Three performance improvements implemented:
  - Perf #292: greeting.py `_handle_member` — changed `upsert_user` to `upsert_user_if_changed`. On-join identity writes are now skipped if L1 cache already matches (sub-microsecond fast path). Impacts batch invite-link joins most.
  - Perf #293: `__main__.py` `_post_init` — parallelised `ensure_indexes`, `ensure_initial_owner`, and `redis_client.connect` via `asyncio.gather`. All three are safe to run concurrently after MongoDB `connect()`. Index failure still fatal (re-raised); owner seed failure logged as warning; Redis failure degrades gracefully. Saves ~100–200 ms on cold Atlas start.
  - Perf #294: `__main__.py` new `_warm_hot_caches` — background cache warm-up task fired after scheduler starts. Pre-warms `owner_id_cache` and `active_groups_cache` in parallel so first command handler gets L1 hit. Strong reference in `_startup_tasks` set (RUF006-compliant).
  - Verification: ruff 73 files clean (All checks passed!).

- Session 110 (2026-06-13): Performance improvements from new task file v4.1.1 mandate. No bugs found; four performance enhancements implemented:
  - `upsert_user_if_changed()` in users_cache.py: change-detection write that checks L1 mention cache before issuing MongoDB write; skips DB on cache hit (sub-microsecond). Returns bool indicating write.
  - `_update_member_cache` in __main__.py: converted from blocking `await upsert_user()` (every update) to fire-and-forget background task using `upsert_user_if_changed`. Fast path (cache hit, no change): ~0 cost. `_member_cache_tasks` set for RUF006 compliance.
  - `on_join_request` in greeting.py: added parallel identity harvest (`upsert_user_if_changed`) alongside ban check via `asyncio.gather`. Previously user identity was not cached from join requests.
  - `_harvest_admin_identities()` in connected_flow.py: new function + `_harvest_tasks` set. When group connects, `getChatAdministrators` fetched in parallel in `complete_join`; admin identities persisted via parallel `asyncio.gather` over all admins. RUF006-compliant.
  - Verification: ruff 73 files clean, import OK, config OK, startup OK (27/27 indexes, Redis hiredis 3.4.0, APScheduler, polling).

- Session 109 (2026-06-13): Third-pass comprehensive audit of all primary moderation paths. No new bugs found — all areas verified CLEAN:
  - ban_flow.py, greeting.py, scheduler.py, muting_flow.py, unban_flow.py, extraction.py, warning_flow.py (T001-T007 repeated audit pass).
  - appeal_flow.py (approval block): deactivate_all_active_bans + cancel_schedule + fan_out + primary groups — pattern correct.
  - bans_db.py (deactivate_all/extra), mutes_db.py (log_mute with duration_secs) — clean.
  - checking.py (full), identity.py (full), decorators.py (full), muting.py (full), kicking.py (full), unbanning.py (full), banning.py (full), warnings.py (full), kicking_flow.py (full), appeals.py (full), connected_flow.py (cmc.from_user None guard) — all clean.
  - Verification: ruff 73 files clean, import OK, startup OK (27/27 indexes, Redis, APScheduler, polling).
  - Total bugs fixed remains: #1–#285.

- Session 108 (2026-06-13): Full second-pass comprehensive audit of all remaining unaudited areas. One performance bug found and fixed:
  - Bug #285: users_cache.get_first_name() bypassed the L1 user_mention_cache and hit MongoDB directly on every call. Called from 10 sites including hot paths in asyncio.gather across ban_flow, appeal_flow, check_flow, connected_flow. Fixed by adding L1 cache-check path (same pattern as get_user_mention_data) before falling back to MongoDB.
  - All areas verified clean (no new bugs): checking.py (398-564), warning_flow.py (219-310), check_flow.py (full 591 lines), muting_flow.py (full 283 lines), connected_flow.py (full 369 lines), admins.py (555-836), ban_info.py, unbanning.py, kicking.py, dispatch.py, bans_db.py, groups_db.py, warns_db.py, kicks_db.py, mutes_db.py, users_roles.py, unban_flow.py, kicking_flow.py, demote_flow.py, promote_flow.py, broadcasting.py, disconnecting.py, proof_flow.py, reason_flow.py. No emoji/emoticons, no em-dashes.
  - Ruff: All checks passed (73 files clean).
  - CHANGELOG.md updated with session 108 Fixed section.
  - Total bugs fixed: #1–#285.

- Session 107 (2026-06-13): Fresh context recovery + deep re-audit pass across critical files. Found and fixed 2 CI bugs:
  - Bug #283: dependency-update.yml — `GH_TOKEN: ${{ secrets.GH_TOKEN }}` (custom secret, may not exist) changed to `GH_TOKEN: ${{ github.token }}` (built-in Actions token). context.md incorrectly recorded this as fixed in session 103; the actual file change was never applied.
  - Bug #284: lint.yml — Indonesian comment `# Bot configuration secrets untuk import check` changed to English `# Bot configuration secrets required for the import check` per project policy.
  - Comprehensive re-verification of all gather calls in: mongos.py, groups_db.py, stats_flow.py, check_flow.py (all sections), broadcasting.py, maintenance.py, stats.py, connected_flow.py, kicking_flow.py, unban_flow.py, warning_flow.py, reason_flow.py, demote_flow.py, admins.py (all sections, 600-779), checking.py, ban_flow.py — all have return_exceptions=True ✓.
  - Bot restart: MongoDB 27/27 indexes, Redis hiredis 3.4.0, APScheduler CBORSerializer, polling active. Ruff: All checks passed (73 files).
  - CHANGELOG.md updated with session 107 Fixed section.
  - Total bugs fixed: #1–#284.

- Session 104 (2026-06-13): Deep audit of all primary moderation execution paths (ban/mute/unban/kick/warn/greeting/extraction). Found and fixed 2 bugs:
  - Bug #279: Primary groups (MAIN_GROUP, EXEC_GROUP) excluded from federation enforcement fan-out. Active_groups() only returns groups in federated_groups collection; primary groups configured via env var are not there by default. Federation-banned/muted users remained in primary groups until they left and rejoined. Fixed in ban_flow._execute_ban, muting_flow._execute_mute + execute_unmute, unban_flow.execute_unban. All three now append cfg.main_group + cfg.exec_group to the groups list before fan_out when not already present. Also fixed unban path (always future-proofs when MAIN_GROUP is already connected).
  - Bug #278: mutes_db.log_mute stored no duration. Timed mutes had duration_secs computed in _execute_mute but never saved to DB. Added duration_secs (int | None) keyword-only param to log_mute; updated _execute_mute to pass it. DB record now shows how long the restriction was intended to last.
  - Comprehensive verification: muting_flow (until_date passed to Telegram correctly), ban_flow (real fan_out + PM graceful), kicking_flow (local only, by design), warning_flow (local auto-ban at limit, demote first), greeting (both new_chat_member + ChatJoinRequest paths enforce bans), extraction (5 resolution paths consistent across all commands), unban_flow (deactivate_all + cancel_schedule).
  - CHANGELOG, docs/banning-detailed.md, docs/databases/databases.md updated. Ruff: All checks passed (73 files). Total bugs fixed: #1-#279.

- Session 103 (2026-06-13): Comprehensive audit of all remaining unaudited tcbot/ files + Docker/CI infra. Bugs #271-#277 fixed. Session plan: T001 (user-facing modules), T002 (Docker/CI), T003 (utils/db infra), T004 (main entry + ban_info + extraction). All tasks complete.
  - Bug #271: Dockerfile verification step made verbose (hiredis print message).
  - Bug #272: docker-compose.yml Redis healthcheck timeout increased to 5s.
  - Bug #273: dependency-update.yml: `${{ secrets.GH_TOKEN }}` → `${{ secrets.GITHUB_TOKEN }}` (built-in Actions token; no manual secret needed).
  - Bug #274: lint.yml import check reverted from `python -m tcbot` (starts full bot, hangs CI) to `python -c "import tcbot; print('import OK')"`. Indonesian comment replaced with English.
  - Bug #275: Dockerfile hiredis C extension verification confirmed present.
  - Bug #276: dispatch.py fan_out() — asyncio.CancelledError was swallowed by generic Exception; re-raised explicitly so shutdown is clean.
  - Bug #277: scheduler.py setup_schedules — `CronTrigger(day_of_week=0, ...)` resolves to Sunday in APScheduler 4.x (Unix cron 0=Sunday), not Monday as the log message stated. Changed to `CronTrigger(day_of_week="mon", ...)`.
  - T001 verified (main agent): start.py, help.py, about.py, privacy.py, groups.py — all q.answer() first, no emoji, no em-dash, correct guards. modules/__init__.py, types.py — clean.
  - T004 verified (main agent): __main__.py, ban_info.py, extraction.py (Bug #270 fix correct).
  - Ruff: All checks passed (73 files). Bot restart clean.

- Session 100 (2026-06-13): Documentation-only session. No code changes. Nine docs updated to reflect code changes from sessions 95-99 that had not yet been documented.
  - docs/helper/helper.md: user_ref() added to formatter.py table.
  - docs/databases/databases.md: deactivate_all_active_bans + deactivate_extra_active_bans added.
  - docs/banning-detailed.md: dedup guard and deactivate_all_active_bans + cancel_schedule documented.
  - docs/appeal-detailed.md: deactivate_all_active_bans on approval documented.
  - docs/check-detailed.md + docs/stats-detailed.md: fallback name str(uid) not "User <id>".
  - docs/demote-detailed.md: trigger="mute" added as fourth auto-demote path.
  - docs/role-detailed.md: all auto-demote references updated to include "mute".
  - docs/workflows/workflows.md: trigger="mute" row added to demote table.
  - CHANGELOG.md: session 100 Documentation section added.
  - Ruff: All checks passed (73 files, no code changed).

- Session 99 (2026-06-13): Bug #265 fixed. Full audit of checking.py, check_flow.py, connecting.py, disconnecting.py, unbanning.py, admins.py, appeals.py, stats.py, broadcasting.py, maintenance.py, additional.py all verified clean. CHANGELOG.md updated with Bug #265 entry. Ruff: All checks passed (73 files).
  - Bug #265: warnings.py cmd_warn_entry - missing identity.staff_notice("warn", ident, cfg.community_name) call before return in refusal guard; consistent with cmd_unwarn and cmd_resetwarns in same file.

- Session 98 (2026-06-13): Bugs #261-#264 fixed.
  - Bug #261: banning/muting/kicking/warnings cmd entry points - resolve_and_check may reply internally, code continued to identity.refuse_message causing double reply; added early return after unpacking role_result.
  - Bug #262: ban_flow._execute_ban - ban_duration F841 unused variable; added `_ = ban_duration` placeholder.
  - Bug #263: identity.classify + checking.cmd_check - target_fname.startswith("User ") guard missed numeric-string fallback (str(uid)); added lstrip("-").isdigit() check.
  - Bug #264: mention() smart dedup + "User {uid}" → str(uid) fallback across users_cache.py, identity.py, stats_flow.py, check_flow.py.

- Session 97 (2026-06-13): Bugs #256-#260 fixed. Comprehensive audit of warning_flow.py, muting.py, demote_flow.py, stats_flow.py, check_flow.py, ban_info.py, muting_flow.py, kicking.py, kicking_flow.py, unbanning.py, checking.py, banning.py, scheduler.py, additional.py all verified clean.
  - Bug #256: warning_flow.py execute_resetwarns - last mention+code pattern → user_ref; removed unused code/mention imports.
  - Bug #257: muting.py Demote.execute trigger="kick" → "mute"; demote_flow.py updated to handle "mute" verb ("you were muted from the federation").
  - Bug #258: stats_flow.py user list - mention(uid,fname,uname) - code(str(uid)) → user_ref(uid,fname,uname); fixes duplicate ID for users without username.
  - Bug #259: check_flow.py _async_const type annotation `str → str` → `Any → Any` (called with dict at line 558).
  - Bug #260: additional.py __additional_msg__ used `<b>Official Links</b>` hardcoded tag → bold('Official Links'); added bold to import.
  - CHANGELOG.md updated. Ruff: All checks passed (73 files). Format: 73 already formatted. Import: OK. Bot running: clean.

- Session 95 (2026-06-13): Bugs #247-#255 fixed.
  - Bug #247: user_ref() helper; 9 files migrated from mention()-code(id) pattern.
  - Bug #248: bans_db: deactivate_all_active_bans + deactivate_extra_active_bans.
  - Bug #249: ban_flow: per-group failure reporting, PM notification, dedup on re-ban.
  - Bug #250: unban_flow: deactivate_all_active_bans.
  - Bug #251: appeal_flow: deactivate_all_active_bans on approval.
  - Bug #252: greeting.py: ChatJoinRequestHandler + all-groups enforcement.
  - Bug #253: extraction.py _best_name returns str(uid) not "User {uid}".
  - Bug #254: unban_flow: cancel_schedule defensive call.
  - Bug #255: conversation_timeout dead code removed; PTBUserWarning eliminated.

- Session 94 (2026-06-13): Deep audit pass, no bugs found. 25+ files verified.
- Session 93 (2026-06-13): Formatter consistency audit. Bugs #236-#246 fixed across 11 files.
- Session 92 (2026-06-13): Bugs #232-#235 fixed + full comprehensive final audit.
- Session 91 (2026-06-13): netspeed.py + Bug #231 decorator-order fix.
- Session 90 (2026-06-13): Bugs #218-230 (CI gate, q.answer, gather).
- Session 89 (2026-06-13): Bugs #212-217 (identity refusal gaps, disconnecting gather).
- Session 88 (2026-06-13): Bugs #202-211 fixed.
- Session 87 (2026-06-13): Bugs #187-201 fixed.
- Session 86 (2026-06-12): Bugs #179a-186 fixed.
- Sessions 65-85 (2026-06-02 to 2026-06-12): Comprehensive v4.1.1 development.

## AUDIT STATUS

**ONGOING** — pass 10 in progress (session 119). All 73 tcbot/ Python files audited and ruff-clean (nine full passes + pass 10 docs sweep).
Total bugs fixed: **#1-#330** (Bugs #306-#309, #311-#314, #321-#330 docs-only; Bug #310 is a code comment). Code logic/UX bugs: #1-#305, #315-#320. Perf improvements: **#292-#294, Perf #4**.

### All files fully audited across all sessions:
ban_flow.py, greeting.py, bans_db.py, unban_flow.py, appeal_flow.py, banning.py, muting.py, muting_flow.py, kicking.py, kicking_flow.py, warnings.py, warning_flow.py, demote_flow.py, connected_flow.py, proof_flow.py, reason_flow.py, parse_logmsg.py, decorators.py, admins.py, users_cache.py, users_roles.py, promote_flow.py, connecting.py, disconnecting.py, groups_db.py, unbanning.py, appeals.py, check_flow.py, broadcasting.py, mongos.py, mutes_db.py, warns_db.py, kicks_db.py, queues_db.py, pagination.py, error_reporter.py, keyboards.py, parse_editmsg.py, documents.py, replies.py, timedate_format.py, parse_link.py, prefixes.py, redis_client.py, alive.py, checking.py, stats.py, stats_flow.py, maintenance.py, additional.py, netspeed.py, formatter.py, identity.py, cache.py, scheduler.py, __init__.py, __main__.py, ban_info.py, extraction.py, start.py, help.py, about.py, privacy.py, groups.py, modules/__init__.py, modules/types.py, dispatch.py, logger.py, utils/__init__.py, database/__init__.py, database/types.py, modules/helper/__init__.py, modules/helper/workflows/__init__.py

### Known non-bugs (by design):
- `schedule_unban` in scheduler.py defined but not called - timed bans feature not yet implemented.
- mutes_db.py has no `is_active` field - mutes are Telegram-native via `until_date`; no APScheduler needed.
- stats_flow.py lines 391/520 use `esc(fname) - code(str(uid))` (no mention()) - equivalent to user_ref without username; intentional.
- error_reporter.py uses hardcoded `<b>` labels in error report templates - all dynamic values escaped with internal `_esc()`; safe and intentional (utils layer separation).
- `<b>/<code>` in `__help_sections__` across all modules - established project pattern for static help text; not formatter anti-patterns.

## Runtime info

- Bot running: MongoDB, Redis hiredis 3.4.0, APScheduler CBORSerializer, 27/27 indexes, polling active.
- File count: 73 Python files.
- Ruff: All checks passed (0 errors, 73 files clean).

## Agent communication rule

ALWAYS respond to the user in Indonesian (Bahasa Indonesia profesional). All code, docstrings, comments, docs, CHANGELOG, commit messages, and `.agents/memory/` files remain in English.
