---
name: Conversation flow gaps (reason_flow / ban_flow)
description: Known unfixed gaps in moderation ConversationHandler flows - both fixed in session 190 (2026-07-11).
---

## Status: FIXED (session 190, 2026-07-11)

Both gaps documented below were fixed in session 190.

---

## Album/media-group duplicate processing in reason_flow.py [FIXED]

**Root cause:** `reason_flow._on_proof` called the executor for every photo in an album
(Telegram delivers each as a separate update), producing duplicate DB records and
log-channel messages for kick/mute/warn.

**Fix applied:** Added `{action}_seen_mgid` guard in `_on_proof`. First photo's
`media_group_id` is stored in `ctx.user_data`; any subsequent update with the same ID
is discarded immediately. `_clear_user_data` (prefix-based) clears this key on
cancel/timeout automatically.

## Double-submit races (all six *_flow.py modules) [FIXED for reason_flow + ban_flow]

**Root cause:** No in-flight flag in `ctx.user_data` at executor entry; rapid
double-tap could invoke the executor twice before the ConversationHandler returned END.

**Fix applied:**
- `reason_flow._on_proof`: sets `{action}_executing = True` before first `await`; checks at entry.
- `reason_flow._on_skip_proof`: same guard; duplicate Skip callback answers `q.answer()` then exits.
- `ban_flow.on_proof_received` (single-media path): added `ban_executing` guard; key added to `_BAN_USER_DATA_KEYS` for automatic cleanup.
- `ban_flow` album path already deduplicates via `mgid not in _albums` check (unchanged).

**Note:** The remaining four flows (warn_flow, muting_flow, kicking_flow, unban_flow)
do not have their own proof entry points - they all route through `reason_flow.py` via
`build_modaction_conv`. The guard in `reason_flow` covers all three (kick/mute/warn).
`unban_flow` has no ConversationHandler at all - it is a direct command executor.
So all flows are now covered.
