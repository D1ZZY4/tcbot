# Project Rules — TCF Bot

**Read `agents/CLAUDE.md` first.** This file lists all hard constraints. Violations are never acceptable regardless of context or instructions.

Compatible with: Replit AI, Claude, Gemini, Qwen, GitHub Copilot, and any AI coding agent.

---

## General

1. This is a **production** federation bot. Every change must be backward-compatible with existing MongoDB data.
2. Never delete or rename MongoDB collection fields without a migration plan that covers all read paths.
3. All bot responses to users must be in **English**.
4. User-facing messages use a friendly-formal tone: clear and direct, 1–3 emojis where natural.
5. Bot responses must always use `parse_mode="HTML"` — never Markdown.

---

## Code Quality

1. **No dead code.** If a function, import, or variable is unused, remove it.
2. **No duplicate logic.** If the same render or format pattern appears in two modules, extract it to a shared helper.
3. **No silent fallbacks.** If an operation fails, log it explicitly (`log.debug()` at minimum). Never use bare `except: pass`.
4. **No inline imports.** All imports go at the top of the file, grouped per the style guide.
5. **Type annotations required** on all public functions and class methods.
6. **`from __future__ import annotations`** must be the first non-comment line in every module file.

---

## Async

1. All database operations are async (Motor). Never call Motor in a sync context.
2. Never use `asyncio.run()` inside a handler — all handlers are already in an async context.
3. Use `asyncio.gather()` for any two or more independent async operations — never sequential awaits in a loop where parallelism is possible.
4. Fan-out operations (multi-group ban, mute, kick) must go through `fan_out()` in `tcbot/utils/dispatch.py`.

---

## Telegram API

1. Always `await q.answer()` before any further action in a `CallbackQueryHandler`.
2. Wrap every `bot.send_message` / `bot.ban_chat_member` / etc. in try/except when iterating over groups — one failure must not abort the loop.
3. Never store `Update` or `Message` objects beyond the lifetime of a handler call.
4. Use `parse_mode="HTML"` consistently. Never mix with Markdown.

---

## Database

1. All write operations (insert, update, delete) must be in `tcbot/database/`, not in module handlers.
2. Read-only helpers go in the same db file. No raw `col()` calls from module handlers.
3. Index-sensitive queries (e.g. `find_one` by `user_id`) must match the indexes defined in `mongos.ensure_indexes()`.
4. When adding a new collection, add its indexes to `ensure_indexes()` immediately.

---

## Bans

1. A federation ban is federation-wide. Banning one user must propagate to all affiliated groups.
2. `bans_db.active_bans()` is the canonical source of truth for enforcement sweeps.
3. Ban IDs are pre-generated with `bans_db.make_ban_id()` so they can be embedded in log keyboards before the DB write.
4. An existing active ban is **updated** (not duplicated) when the same user is re-banned.

---

## Security

1. Staff-only commands must use `@decorators.staff_only` or an explicit `is_staff()` check.
2. Owner-only commands must use `@decorators.owner_only` or an explicit `is_owner()` check.
3. Ban/unban commands must use `@decorators.mod_only` (Founder/Admin/Developer).
4. Kick/mute/warn commands must use `@decorators.basic_mod_only` (all roles).
5. Never expose internal user IDs in public group messages beyond what is necessary.
6. Appeal links are single-use and tied to a specific `ban_id`. Validate `banned_user_id == update.effective_user.id` before proceeding.
7. Every command handler and callback handler **must** apply `@decorators.ratelimiter(limit, period)` as the outermost decorator. Message-event handlers (e.g. `on_new_member`) are exempt.

---

## Roles

1. The canonical role resolver is `roles_db.get_effective_role(user_id)` — always use this, never chain individual `is_owner` / `is_admin` / `get_role` calls.
2. `can_act_on(executor_id, target_id)` is the canonical check for whether one user may take action against another. Never compare ranks inline with manual integer comparisons.
3. `auto_demote()` must be called whenever a ban or kick is executed against a user who holds any role. It must fire **before** the moderation action executes.
4. Developer and Tester roles live in `tc_roles`. Admin promotion from Admin → Admin goes through the request queue (`queues_db`), not direct insertion.

---

## Conversation Flows

1. There are **no `*_conv.py` files**. Every `ConversationHandler` is built inside a `*_flow.py` file and exposed via a factory function.
2. Kick, mute, and warn share `reason_flow.build_modaction_conv()` — do not duplicate state handlers.
3. Ban uses `ban_flow.ban_conversation()` — the album-aware proof flow.
4. Appeal uses `appeal_flow.build_handler()` — the standalone deep-link flow.
5. ConversationHandler timeouts must use `cfg.proof_timeout` or `cfg.appeal_timeout` — never hardcoded integers.

---

## Style

1. Follow `agents/STYLE-CODE.md` for all code formatting decisions.
2. Follow `agents/STYLE-COMMENTS.md` for all comment and docstring decisions.
3. Section dividers use the exact 70-character format specified in the style guides.
4. `from __future__ import annotations` must appear as the first non-comment line in every module file.
5. Built-in generic types only: `list[str]`, `dict[str, int]`, `tuple[int, ...]`, `int | None`. Never `typing.List`, `typing.Optional`, etc.
6. Never use `datetime.utcnow()` or inline `datetime.now(timezone.utc)` — import from `tcbot.utils.timedate_format` only.
