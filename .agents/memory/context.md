---
name: Project context
description: Current state of TCF Bot project - what is done, in progress, and pending. Update before every commit.
---

# TCF Bot - Current Context

**Last updated:** 2026-06-13 (session 88 waves 1-2)

## What is done

- Session 88 wave 2 (2026-06-13): Autonomous audit loop continuation.
  - Bug #207: connected_flow.py `on_join_decision` - `update.effective_message.reply_text(...)` passed as gather arg without None check. Fixed with local variable + conditional coroutine append.
  - Bug #208: connected_flow.py `on_join_decision` - `q.message.message_id` without None check. Fixed: `prompt_msg_id = q.message.message_id if q.message else 0`.
  - Bug #209: admins.py `on_promo_decision` - `q.message.text` as gather arg without `q.message` None check (x2: approve + reject). Fixed: `(q.message.text if q.message else "")`.
  - Bug #210: kicking_flow.py `execute_kick` - results[0] (unban_chat_member) not checked; failure left user banned with no log. Fixed: added log.warning for BaseException.
  - Bug #211: mongos.py `ensure_indexes` - dead `bans(chat_id)` index; BanDoc has no chat_id field. Removed.
  - Performance: connected_flow.py cancel action - 2 sequential gathers merged into 1 (4 independent ops).
  - Docs sub-agent: no drift. PLAN.md all Resolved items correctly so. File naming as expected (detailed files).
  - promote_flow.py/demote_flow.py: ALL sub-agent findings false positives - all gathers already have return_exceptions=True.
  - warns_db.py remove_last_warn: sub-agent finding false positive - already has return_exceptions=True at line 179.
  - Ruff: 72 files, all checks passed.
  - Bot running: MongoDB, Redis hiredis 3.4.0, APScheduler CBORSerializer, 27/27 indexes (removed dead bans.chat_id), polling active.

- Session 88 wave 1 (2026-06-13): Bugs #202-206 fixed. See progress.md.

- Session 87 waves 1-6 (2026-06-13): Bugs #187-201 fixed. See progress.md.

- Session 86 (2026-06-12): Bugs #179a-186 fixed.

- Sessions 65-85 (2026-06-02 to 2026-06-12): Comprehensive v4.1.1 development and hardening.

## AUDIT STATUS

**FULLY COMPLETE** for session 88 waves 1-2 - ALL tcbot/ files audited across 15+ sub-agent waves.
Bugs fixed session 88: #202-211 (10 bugs). Total session 86-88: #179-211 (33 bugs).
No remaining known bugs. warns_db.py atomicity is a design-level note, not a crash bug.

## Runtime info

- Bot running: MongoDB, Redis hiredis 3.4.0, APScheduler CBORSerializer, 27/27 indexes, polling active.
- File count: 72 Python files.
- Ruff: All checks passed (0 errors).
