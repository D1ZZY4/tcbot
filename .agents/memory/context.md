---
name: Project context
description: Current state of TCF Bot project - what is done, in progress, and pending. Update before every commit.
---

# TCF Bot - Current Context

**Last updated:** 2026-06-13 (session 87)

## What is done

- Session 87 (2026-06-13): Autonomous audit loop, 12+ parallel sub-agent waves. All tcbot/ files audited.
  - Bugs #187-188: appeal_flow.py _on_message remaining stale user_data paths (user is None + successful submission).
  - Bug #189: reason_flow.py _on_skip_reason invisible-state (WAITING_PROOF returned when edit failed, user had no visible UI).
  - Dead code removed: `utc_now_str` (timedate_format.py), `register_command`/`dispatch_alt_prefix`/_REGISTRY/_UpdateLike/_ContextLike (prefixes.py). Ruff fixed 3 unused-import errors.
  - Bugs #190-193: user_data cleanup on prompt failure in banning.py/muting.py/kicking.py/warnings.py entry handlers (same stale-key pattern after ConversationHandler.END without clearing user_data).
  - Bug #194: ban_flow.py _execute_ban unguarded `await _old_admin_fname_task` - crash aborted silent ban. Fixed with try/except fallback "Admin".
  - Bug #195: ban_flow.py _execute_ban else-branch `upsert_user` unguarded. Fixed with try/except log.exception.
  - Bug #196: identity.py classify() asyncio.gather without return_exceptions=True - DB error crashed ALL moderation commands. Fixed.
  - Bug #197: identity.py classify() target_fname None fallback missing after gather fix - would TypeError in mention(). Fixed.
  - Bug #198: ban_flow.py on_proof_received success path didn't clear _BAN_USER_DATA_KEYS. Fixed.
  - Bug #199: ban_flow.py _flush_album _execute_ban not in try/finally - crash skipped user_data cleanup. Fixed with try/except/finally.
  - Config validation: ALL env vars from replit.md confirmed loaded/validated in __init__.py (sub-agent green).
  - Dead code verification: most sub-agent "dead code" claims were FALSE POSITIVES (make_short_id, chat_id_to_link_id, group_bot_removed_log, to_utc, Demote imports - all ARE used). Only genuine dead code removed.
  - Startup sequence: CLEAN (post_init complete before polling, Flask daemonized, SIGTERM handled).
  - decorators.py + formatter.py: CLEAN.
  - maintenance.py + connected_flow.py: CLEAN (all gathers guarded).
  - database layer: CLEAN (get_mention_data_batch has fallback for all IDs).
  - parse_logmsg.py: CLEAN (str() conversion handles None).
  - cache.py TwoLevelCache: CLEAN (maxsize TTLCache + proper task tracking).
  - kicking_flow.py, muting_flow.py, warning_flow.py, pagination.py, logger.py, warns_db.py, queues_db.py: ALL CLEAN.
  - admins.py/promote_flow.py/demote_flow.py: CLEAN (stateless callback pattern, all gathers guarded).
  - unbanning.py/unban_flow.py: CLEAN.
  - stats.py/stats_flow.py: CLEAN (mention_data_map has guaranteed entries for all IDs).
  - Ruff: 72 files clean throughout.
  - Bot running: MongoDB, Redis hiredis 3.4.0, APScheduler CBORSerializer, 28/28 indexes, polling active.

- Session 86 (2026-06-12): Autonomous audit loop, wave 1-3.
  - Bugs #179a-d: appeal_flow.py _start (4 unguarded reply_text).
  - Bugs #180a-e: checking.py cmd_checkme (5 unguarded reply_text).
  - Bug #181: checking.py cmd_check (1 unguarded reply_text).
  - Bug #182: ban_flow.py on_cancel_proof album flush race (clear album state on cancel).
  - Bug #183: ban_flow.py on_proof_timeout album flush race (same fix).
  - Bug #184: reason_flow.py _on_reason_text END without _clear_user_data.
  - Bug #185: appeal_flow.py _end fallback handler END without clearing user_data.
  - Bug #186: appeal_flow.py _start instruction-failure stale keys.
  - CHANGELOG em-dash: 14 chars replaced throughout.
  - Config loading: confirmed complete (all env vars present, required ones fail-fast).
  - MongoDB queries: no injection vectors (Motor parameterization).
  - Rate limiters: all primary moderation commands have them.
  - Emoji audit: 0 emoji in user-facing strings.

- Session 85c (2026-06-12): Final DRY confirmation. No new bugs. All audited CLEAN.
- Session 85b (2026-06-12): Bugs #176-178 fixed (ban_info, warning_flow, muting_flow).
- Sessions 65-85 (2026-06-02 to 2026-06-12): Comprehensive v4.1.1 development and hardening.

## AUDIT STATUS

**FULLY COMPLETE** for session 87 - all tcbot/ files audited across 12+ sub-agent waves.
Bugs fixed this session: #187-199 (13 bugs in session 87). Total session 86+87: #179-199 (21 bugs).

## Runtime info

- Bot running: MongoDB, Redis hiredis 3.4.0, APScheduler CBORSerializer, 28/28 indexes.
- File count: 72 Python files.
- Ruff: All checks passed.
