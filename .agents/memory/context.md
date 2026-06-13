---
name: Project context
description: Current state of TCF Bot project - what is done, in progress, and pending. Update before every commit.
---

# TCF Bot - Current Context

**Last updated:** 2026-06-13 (session 87 waves 5-6)

## What is done

- Session 87 waves 5-6 (2026-06-13): Continuation of autonomous audit loop.
  - Bug #200: keyboards.py dead code removed: `help_modules`, `stats_main_kb`, `stats_back_kb` (zero callers confirmed; stats menus use local `main_kb`/`back_kb` in stats_flow.py). Updated docs/helper/helper.md table.
  - Bug #201: appeal_flow.py `_start`: `db.bans_db.get_ban(ban_id)` was unprotected; DB error during appeal deep-link validation crashed handler without user notification. Fixed with try/except + contextlib.suppress + log.exception.
  - CBORSerializer: CONFIRMED CLEAN - no `packages` parameter exists in installed APScheduler 4 (signature: `type_tag, dump_options, load_options`). Sub-agent suggestion was stale.
  - stats.py / stats_flow.py: CLEAN - all gathers guarded, q.answer() correct, pagination uses shared helper, no N+1 queries, no emoji.
  - banning_flow/muting_flow/kicking_flow/warning_flow/reason_flow: ALL CLEAN - all gathers have return_exceptions=True (re-verified).
  - admins.py/promote_flow.py/demote_flow.py: CLEAN - all gathers guarded, role validation correct, tester blocked from promote.
  - bans_db/mutes_db/groups_db/kicks_db/users_roles: ALL CLEAN.
  - cache.py TwoLevelCache: CLEAN - thundering herd is acceptable, task guard set correct.
  - users_cache.py: CLEAN - batch queries prevent N+1.
  - warns_db.py: DESIGN-LEVEL atomicity risk noted (add_warn + counter not atomic, remove_last_warn non-atomic find+delete). Acceptable - MongoDB single-document atomicity used where possible, _sync_warn_count provides recovery.
  - dispatch.py (fan_out): CLEAN - try/except in slot wrapper.
  - pagination.py: CLEAN - edge case (page_size=0 ZeroDivisionError) noted but page_size is always a constant.
  - extraction.py: CLEAN - anonymous bot (1087968824) skipped at L103, from_user None guarded.
  - decorators.py: CLEAN - staff_only correctly rejects testers (is_staff returns True only for owner/admin).
  - replies.py: CLEAN (static constants).
  - parse_logmsg.py: CLEAN - all inputs are primitives/stringified.
  - __main__.py: CLEAN - asyncio exception handler registered in post_init, graceful shutdown correct, motor client OK on exit.
  - config/__init__.py: DESIGN NOTE - optional chat IDs (MAIN_GROUP, LOGS etc.) default to "" and validate as (0, None) at runtime; intentional design for optional-feature support.
  - mongos.py: CLEAN - all 28 indexes cover query patterns, no duplicates, TTL handled by scheduler.
  - Voice/UX: CLEAN for all modules (no emoji, no em-dash, descriptive errors).
  - Ruff: 72 files, all checks passed.
  - Bot running: MongoDB, Redis hiredis 3.4.0, APScheduler CBORSerializer, 28/28 indexes, polling active.

- Session 87 waves 1-4 (2026-06-13): see progress.md for Bug #187-199.

- Session 86 (2026-06-12): Bugs #179a-186 fixed.

- Sessions 65-85 (2026-06-02 to 2026-06-12): Comprehensive v4.1.1 development and hardening.

## AUDIT STATUS

**FULLY COMPLETE** for session 87 waves 1-6 - ALL tcbot/ files audited across 15+ sub-agent waves.
Bugs fixed session 87: #187-201 (15 bugs). Total session 86+87: #179-201 (23 bugs).
No remaining known bugs. warns_db.py atomicity is a design-level note, not a crash bug.

## Runtime info

- Bot running: MongoDB, Redis hiredis 3.4.0, APScheduler CBORSerializer, 28/28 indexes, polling active.
- File count: 72 Python files.
- Ruff: All checks passed (0 errors).
