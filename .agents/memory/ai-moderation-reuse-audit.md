---
name: AI moderation reuse-vs-reinvent audit findings
description: Confirmed DB/helper function names and reuse decisions for ai_moderation/ — check before assuming a bans_db/mutes_db/parse_logmsg signature
---

## Confirmed existing helpers (do not re-verify, but do re-check if these files have since changed)

- `bans_db.get_ban(ban_id)`, `bans_db.deactivate_ban(ban_id)` (NOT `revoke_ban`), `bans_db.set_log_message_id(ban_id, log_msg_id)` all exist as-is.
- `bans_db.create_ban()` needs a small additive diff (`ai_confidence`, `ai_eval_id` kwargs) — not reusable unmodified.
- `mutes_db.log_mute(user_id, chat_id, reason, admin_id, *, duration_secs=None)` — 4th param is positional `admin_id`, not a `ctx_bot_id` kwarg.
- `parse_logmsg.kick_log(...)` requires a `chat_title` parameter that's easy to forget when adapting call sites.
- `parse_logmsg.ban_log(...)` is NOT reusable for AI bans — its positional slot order (`ban_id` in the 6th slot) doesn't fit the AI use case; a new `ai_autoban_log()` was designed instead of misusing it.
- Reuse for AI moderation: `muting_flow.parse_duration()`/`fmt_duration()` for duration strings, `dispatch.count_errors()` for fan-out error tallying, `extraction._ANONYMOUS_BOT_ID` constant (but not `extraction.extract_target()` itself — it's built for interactive `/ban @user` resolution, not for reading `message.from_user` directly).
- Global + per-group AI rate limiting reuses `decorators._AsyncRateLimiter` (two separate instances/prefixes: `ai_mod_cooldown` per-chat, `ai_mod_global` with a constant dummy key) instead of raw Redis `exists`/`setex`.

**Why:** an earlier PRD skeleton draft invented plausible-sounding-but-wrong signatures (`ctx_bot_id`, `revoke_ban`, missing `chat_title`, misusing `ban_log`) that would have caused real bugs (e.g. `chat_id` landing in a `ban_id` slot) if implemented without cross-checking.

**How to apply:** before implementing `action_executor.py`, grep the actual current signatures in `bans_db.py`/`mutes_db.py`/`parse_logmsg.py` again — this file records what was true when checked, not a permanent guarantee those files haven't changed since.
