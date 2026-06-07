---
name: telegram-bot-builder
description: Use when designing, implementing, reviewing, or debugging TCBot Telegram bot features with python-telegram-bot (latest), async handlers, ConversationHandler flows, Motor/MongoDB persistence, moderation UX, and safe deployment practices.
---
Last updated: 2026-05-29


# Telegram Bot Builder for TCBot

Before invoking this skill, confirm the read/update rules in [`.agents/CLAUDE.md`](../../CLAUDE.md#mandatory-read-these-files-before-any-work). After any handler or workflow change, update [`CHANGELOG.md`](../../../CHANGELOG.md), [`PLAN.md`](../../../PLAN.md) (if state changes), and the matching `docs/<feature>-detailed.md` plus [`docs/modules/modules.md`](../../../docs/modules/modules.md) or [`docs/workflows/workflows.md`](../../../docs/workflows/workflows.md) in the same turn.

Use this skill for Telegram bot product and engineering work in the TCF Bot repository. The project is a Python 3.12 community moderation bot built with `python-telegram-bot` (with the `[job-queue]` extra, tracking the latest compatible release), Motor/MongoDB, Flask keepalive, `uv`, and Ruff.

The goal is to build reliable moderation workflows that feel clear, respectful, and fast for staff and users.

## When to Use This Skill

Use this skill when the task involves:

- Telegram commands, message handlers, callback queries, or inline keyboards.
- `python-telegram-bot` application structure or handler registration.
- Conversation flows for bans, appeals, proof collection, moderation actions, or setup workflows.
- Group moderation operations across connected chats.
- Bot UX copy, command discoverability, and staff-facing workflows.
- Telegram API error handling, rate limits, callback behavior, or deployment mode decisions.
- Bot security: token handling, role checks, permissions, audit logs, and abuse prevention.

Do not use generic Node.js, Telegraf, or webhook-only patterns for this project unless the user explicitly asks for a separate bot outside TCBot.

## Current Project Stack

- Python: 3.12.
- Bot framework: `python-telegram-bot` (latest).
- Persistence: MongoDB via Motor.
- Runtime: long polling from `tcbot/__main__.py`.
- Keepalive: Flask health endpoint.
- Dependency manager: `uv`.
- Quality tools: Ruff.
- Configuration: environment variables loaded by `tcbot/__init__.py`, with `config.env.example` as the template.

## Repository Boundaries

Place work in the owning layer:

| Concern | Location |
|---|---|
| Command modules and top-level handlers | `tcbot/modules/` |
| Shared handler helpers | `tcbot/modules/helper/` |
| Conversation flows | `tcbot/modules/helper/workflows/*_flow.py` |
| Database helpers | `tcbot/database/*_db.py` |
| Runtime utilities | `tcbot/utils/` |

Do not put MongoDB writes directly in command handlers. Do not create `*_conv.py` files; new conversation logic belongs in `*_flow.py` files.

## Telegram UX Principles

TCBot is a moderation and federation-management bot, so prioritize clarity over novelty.

- Keep staff actions explicit: who, what action, where, why, and what happens next.
- Make destructive operations hard to trigger accidentally.
- Confirm irreversible or federation-wide actions.
- Use short, professional-friendly copy.
- Prefer one clear next step per message.
- Use inline keyboards for decisions, pagination, and review cards.
- Avoid cluttered menus with too many buttons.
- Always answer callback queries promptly to stop client loading indicators.
- Use HTML parse mode consistently and escape user-provided content.

Example callback pattern:

```python
query = update.callback_query
if query is None:
    return

await query.answer()
await query.edit_message_text(
    "Appeal marked for review.",
    parse_mode="HTML",
)
```

## Handler Design Pattern

A good command handler should:

1. Validate the Telegram update shape.
2. Check permissions through project role helpers/decorators.
3. Parse arguments or delegate target extraction.
4. Call database helpers for persistence.
5. Call Telegram API methods with bounded concurrency when needed.
6. Send a clear HTML response.
7. Log or audit important moderation outcomes.

Skeleton:

```python
from __future__ import annotations

import logging

from telegram import Update
from telegram.ext import ContextTypes

from tcbot import database as db
from tcbot.modules.helper.formatter import code, mention

log = logging.getLogger(__name__)


async def cmd_lookup(update: Update, ctx: ContextTypes.DEFAULT_TYPE) -> None:
    msg = update.effective_message
    user = update.effective_user
    if msg is None or user is None:
        return

    record = await db.users_cache.get_user(user.id)
    if record is None:
        await msg.reply_text("No record found.", parse_mode="HTML")
        return

    await msg.reply_text(
        f"User: {mention(user.id, user.first_name, user.username)}\nID: {code(str(user.id))}",
        parse_mode="HTML",
    )
```

## Commands and Registration

For `tcbot/modules/*.py`:

- Use `cmd_*` names for command handlers.
- Use `on_*` names for event handlers.
- Keep `__module_name__` and `__help_text__` accurate.
- Register handlers in `__handlers__` at the bottom of the module.
- Build command filters through project prefix utilities.
- Keep decorators in the project-required order for protected commands.

Prefer small, composable handlers over large command functions that parse, authorize, persist, fan out, and format everything inline.

## Roles, Permissions, and Safety

Use canonical role helpers. Do not chain ad-hoc owner/admin checks.

- Use role guard decorators for command access.
- Use `get_effective_role()` and `can_act_on()` for hierarchy decisions.
- Use `resolve_and_check()` when both executor and target must be validated.
- Auto-demote role holders before ban/kick workflows where required by project policy.
- Never allow staff to accidentally target the bot itself without a friendly guard response.
- Log moderation actions and partial failures with enough context for auditability.

Security requirements:

- Never hardcode bot tokens, MongoDB URIs, payment tokens, or chat secrets.
- Do not print secrets.
- Do not send private internal IDs to public chats unless the workflow requires it.
- Treat callback data as untrusted input; validate IDs and current state before acting.

## Conversation Flows

Use `ConversationHandler` for multi-step interactions such as proof collection, appeals, and moderation reasons.

Project conventions:

- Flow files live in `tcbot/modules/helper/workflows/`.
- Flow files are named `*_flow.py`.
- Conversation states are module-level `WAITING_*` constants.
- Every flow has a cancel fallback.
- Timeouts use `cfg.proof_timeout`, `cfg.appeal_timeout`, or another project config value.
- Store only small IDs or state markers in context data; persist durable workflow state in MongoDB.

Good flow behavior:

- Tell users what input is expected.
- Accept cancellation at each step.
- Handle timeout with a clear message and cleanup.
- Recover gracefully when the underlying database record was changed by another staff member.
- Make repeated callback presses idempotent.

## Inline Keyboards

Use inline keyboards for decisions and navigation. Keep callback data compact and structured.

Recommended callback data shape:

```text
action:entity:id
```

Examples:

```text
appeal:approve:abc123
appeal:deny:abc123
page:bans:2
```

Guidelines:

- Keep callback data within Telegram limits.
- Validate the action, entity, and ID after receiving the callback.
- Re-load current state from the database before applying a decision.
- Disable or edit completed review cards where practical.
- Use URL buttons only for safe external destinations.

## Multi-Group Moderation

Federation-wide operations can touch many connected groups. Use bounded concurrency and explicit partial-failure reporting.

```python
from tcbot.utils.dispatch import fan_out

active_groups = await db.groups_db.active_groups()
results = await fan_out(
    [
        ctx.bot.ban_chat_member(group["chat_id"], target_id)
        for group in active_groups
    ]
)

failed = sum(1 for result in results if isinstance(result, BaseException))
```

Do not use unbounded `asyncio.gather()` for large group lists. Telegram API failures should not hide successful operations in other groups.

## MongoDB Persistence

Use MongoDB for durable bot state:

- Staff roles.
- Connected groups.
- Federation moderation actions.
- Appeals and proof records.
- Audit logs.
- User profile snapshots needed for display.

Persistence rules:

- Handlers call `tcbot.database` helper modules.
- Helper modules own collection access and query details.
- New query patterns should be supported by indexes.
- Schema changes must be backward-compatible or include a migration plan.

## Error Handling

Handle errors at the right layer.

- In one-off handler operations, show a concise user-facing failure and log details.
- In multi-group loops, collect failures and report a summary.
- In callback handlers, answer the callback even when the action cannot proceed.
- In background jobs, log exceptions with IDs needed for diagnosis.
- Do not use bare `except:` or silent `pass`.

Common Telegram API cases to handle:

- Bot lacks admin rights in a target group.
- User is not found or already left.
- Message was deleted before edit.
- Callback query references expired or already-resolved state.
- Group has been removed or deactivated.

## Deployment Model

TCBot currently uses long polling plus a Flask keepalive endpoint. Do not switch to webhooks unless the user explicitly requests a deployment architecture change.

Operational guidance:

- Configure secrets through environment variables or platform secret storage.
- Keep `config.env.example` as the template, not a secret store.
- Validate startup with `uv run python -m tcbot` locally when appropriate.
- Use `docker-compose up --build` for local bot + MongoDB workflows when requested.
- Keep health checks lightweight and independent of slow Telegram or MongoDB calls.

## Product Review Checklist

Before finishing a bot feature, verify:

- The command or flow solves a real staff/user need.
- Permissions and role hierarchy are enforced.
- Destructive actions require enough context or confirmation.
- User-facing messages are clear and HTML-safe.
- Callback queries are answered promptly.
- Database writes are in helper modules.
- Multi-group Telegram calls are bounded.
- Audit/log destinations are used where required.
- Focused validation was run, or the reason for skipping is clear.

## Validation Commands

For source changes:

```bash
uv run ruff format .
uv run ruff check --fix .
```

Confirm the bot still starts cleanly after workflow changes.

## References

- python-telegram-bot docs: https://docs.python-telegram-bot.org/
- Telegram Bot API: https://core.telegram.org/bots/api
- Motor docs: https://motor.readthedocs.io/
- Project policy: `tgbot/.agents/skills/project-policy/SKILL.md`
- Async patterns: `tgbot/.agents/skills/async-python-patterns/SKILL.md`
- Code quality: `tgbot/.agents/skills/python-code-quality/SKILL.md`
