---
name: Project context
description: Current state of TCF Bot project - what is done, in progress, and pending. Update before every commit.
---

# TCF Bot - Current Context

**Last updated:** 2026-06-13 (session 104)

## What is done

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

**COMPLETE** as of session 103. All 73 tcbot/ Python files audited and ruff-clean.
Total bugs fixed: **#1-#277**.

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
