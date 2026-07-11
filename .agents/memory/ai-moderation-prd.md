---
name: AI moderation PRD architecture decisions
description: Finalized answers to the 7 open questions for the AI moderation PRD (PRD.md) — reference before implementing tcbot/modules/ai_moderation/
---

## Decisions (all confirmed, no blockers remain)

- **Context source (10 last messages)**: in-memory `deque(maxlen=10)` per `chat_id` (pattern like `_albums` in `ban_flow.py`), mirrored async to Redis (short TTL) as restart safety net. No new MongoDB collection for raw message history — was explicitly rejected for write-load reasons.
- **Mute scope**: AI mute is network-wide across all connected groups, reusing existing `muting_flow._execute_mute` / `ActiveMuteDoc` as-is. No single-group mute capability is being built.
- **Ban execution**: `ban_flow._execute_ban` is NOT modified or called by AI moderation — `upload_proof()` only handles photo/video, not text. AI ban uses a new isolated `action_executor.execute_ai_ban()` that writes directly to `bans_db.create_ban()` and calls `fan_out()` itself.
- **Undo Ban button**: active for 24h after an AI ban, then must use manual `/tcunban`.
- **`/admin_set_ai on|off` role**: `staff_only` (same pattern as `cmd_cleanup`), no per-group local-admin check.
- **MyMemory translation rate limit**: no `MYMEMORY_EMAIL` configured; mitigate via staggered/jittered Redis TTL per rule (7 days + random 0-24h) instead of identical TTL for all 27 rules, to avoid mass re-translation on the same day.
- **`ai_evaluations` retention**: TTL index 90 days (like `member_cache`), and ALL verdicts (including `clean` and low-confidence) are persisted for audit — not just flagged ones.
- **Permission validation on toggle**: none — toggling `/admin_set_ai on` does not pre-check bot ban/delete permissions; failures during actual AI-triggered actions fail silently into standard error logging (same as other `fan_out` failures).

**Why:** these were explicitly asked to the user (AskQuestion) to avoid PRD drift from actual codebase behavior; PRD.md v1.1 Section 21 has full detail and rationale.

**How to apply:** treat these as settled before writing any `tcbot/modules/ai_moderation/` code — do not re-litigate or assume PRD v1.0 defaults, which were corrected in v1.1.
