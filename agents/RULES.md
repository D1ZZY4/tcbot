# Project Rules — TCF Bot

## General

1. This is a production federation bot. Every change must be backward-compatible with existing MongoDB data.
2. Never delete or rename MongoDB collection fields without a migration plan.
3. Bot responses must be in English. Log messages may use short technical English.
4. User-facing responses use a friendly-formal tone — clear and direct, but warm. Use 1–3 emojis per message where it feels natural. No filler, no padding.

## Code Quality

1. No dead code. If a function, import, or variable is unused, remove it.
2. No duplicate logic. If the same render/format pattern appears in two modules, extract it.
3. No silent fallbacks. If an operation fails, log it explicitly. Do not swallow errors quietly.
4. No inline imports inside function bodies. All imports go at the top of the file.
5. Type annotations are required on all public functions and class methods.
6. Use `from __future__ import annotations` in every module file.

## Async

1. All database operations are async. Never call motor in a sync context.
2. Never use `asyncio.run()` inside a handler. All handlers are already in an async context.
3. Use `asyncio.gather()` or `asyncio.as_completed()` for concurrent operations, not sequential awaits in a loop where parallelism is possible.

## Telegram

1. Always `await q.answer()` before any further action in a `CallbackQueryHandler`.
2. Wrap every `bot.send_message` / `bot.ban_chat_member` / etc. in try/except when iterating over groups — one failure must not abort the loop.
3. Never store `Update` or `Message` objects beyond the lifetime of a handler call.
4. Use `parse_mode="HTML"` consistently. Do not mix with Markdown.

## Database

1. All write operations (insert, update, delete) must be in the database layer (`tcbot/database/`), not in module handlers.
2. Read-only helpers go in the same db file. No raw `col()` calls in module handlers.
3. Index-sensitive queries (e.g. `find_one` by user_id) must match existing collection indexes.

## Bans

1. A federation ban is federation-wide. Banning one user must propagate to all affiliated groups.
2. `bans_db.active_bans()` is the canonical source of truth for enforcement sweeps.
3. Ban IDs are pre-generated with `bans_db.make_ban_id()` so they can be embedded in log keyboards before the DB write.

## Security

1. Staff-only commands must use the `@decorators.staff_only` decorator or an explicit `is_staff()` check.
2. Owner-only commands must use `@decorators.owner_only` or an explicit `is_owner()` check.
3. Moderation commands (ban/unban) must use `@decorators.mod_only` (Founder/Admin/Developer) or an explicit rank check.
4. Basic moderation commands (kick/mute/warn) must use `@decorators.basic_mod_only` (all roles) or an explicit rank check.
5. Never expose internal user IDs in public group messages beyond what is necessary.
6. Appeal links are single-use and tied to a specific `ban_id`. Validate `banned_user_id == update.effective_user.id` before proceeding.

## Roles

1. The canonical role resolver is `roles_db.get_effective_role(user_id)` — always use this, never chain individual `is_owner` / `is_admin` / `get_role` calls.
2. `can_act_on(executor_id, target_id)` is the canonical check for whether one user may take action against another. Never compare ranks inline.
3. Auto-demote (`role_guard.auto_demote`) must be called whenever a ban or kick is executed against a user who holds any role.
4. Developer and Tester roles live in the `tc_roles` MongoDB collection. Admin promotion to Developer/Tester is direct; Admin promotion to Admin goes through the request queue.
