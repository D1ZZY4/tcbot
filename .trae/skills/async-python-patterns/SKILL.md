---
name: async-python-patterns
description: Use when designing, reviewing, or debugging async Python code in TCBot, especially python-telegram-bot handlers, Motor/MongoDB helpers, bounded fan-out, cancellation, timeouts, and pytest-asyncio tests.
---
Last updated: 2026-05-29


# Async Python Patterns for TCBot

Before invoking this skill, confirm the read/update rules in [`.agents/CLAUDE.md`](../../CLAUDE.md#mandatory-read-these-files-before-any-work). After any async-code change, update [`CHANGELOG.md`](../../../CHANGELOG.md) and the matching `docs/*.md` whose behavior changed in the same turn.

Use this skill for asynchronous Python work in the TCF Bot codebase. The project runs on Python 3.12 with `python-telegram-bot[job-queue] == 22.5`, Motor/MongoDB, Flask keepalive, `uv`, Ruff, and offline `pytest` + `pytest-asyncio` tests.

This skill is intentionally project-specific. Prefer the conventions below over generic asyncio examples.

## When to Use This Skill

Use this skill when the task involves:

- `async def` Telegram command handlers, event handlers, callbacks, or conversation states.
- Motor/MongoDB helper functions in `tcbot/database/`.
- Parallel Telegram API calls across connected groups.
- Background jobs through `python-telegram-bot` job queue.
- Conversation timeouts, cancellation, album debounce logic, or appeal/proof workflows.
- Async unit tests using `pytest-asyncio`.
- Debugging slow handlers, blocked polling, leaked tasks, or unawaited coroutine warnings.

Do not use this skill for CPU-bound optimization unless the async code is directly affected. CPU-heavy work should be isolated or offloaded instead of running on the bot event loop.

## Project Baseline

- Python target: `>=3.12`.
- Telegram framework: `python-telegram-bot` 22.5, async-first API.
- Database driver: Motor (`motor >= 3.7.1`).
- Runtime entry point: `python -m tcbot` on Windows, `python3 -m tcbot` elsewhere.
- Keepalive: Flask runs alongside the bot; do not add blocking work to keepalive routes.
- Dependency workflow: `uv sync`, `uv run ...`.
- Tests: offline `pytest` with `asyncio_mode = "auto"`.

## Core Rules

1. Keep handler call paths async end-to-end.
2. Never call blocking network, database, file, or sleep operations in the event loop.
3. Always `await` Telegram API calls and Motor calls.
4. Use project database helpers instead of calling Mongo collections directly from handlers.
5. Use `tcbot.utils.dispatch.fan_out()` for multi-group Telegram API operations.
6. Preserve cancellation semantics: catch `asyncio.CancelledError` only to clean up, then re-raise.
7. Use configured timeout values from `cfg` for workflows; do not hardcode proof or appeal timeouts.
8. Test async behavior offline with fakes/mocks; never require a real bot token or MongoDB connection.

## Async Handler Pattern

Handlers should be small orchestration functions. Put persistence in `tcbot/database/*_db.py`, shared formatting in helpers, and reusable workflow logic in `tcbot/modules/helper/workflows/*_flow.py`.

```python
from __future__ import annotations

import logging

from telegram import Update
from telegram.ext import ContextTypes

from tcbot import database as db
from tcbot.modules.helper.formatter import code, esc

log = logging.getLogger(__name__)


async def cmd_example(update: Update, ctx: ContextTypes.DEFAULT_TYPE) -> None:
    msg = update.effective_message
    user = update.effective_user
    if msg is None or user is None:
        return

    record = await db.users_db.get_user(user.id)
    label = esc(record.get("first_name", user.first_name) if record else user.first_name)

    await msg.reply_text(
        f"User: {label}\nID: {code(str(user.id))}",
        parse_mode="HTML",
    )
```

Checklist:

- Guard `effective_message`, `effective_user`, and `effective_chat` when they can be absent.
- Keep user-visible messages HTML-only and escape user-provided text.
- Do not store `Update`, `Message`, or `CallbackQuery` objects beyond the handler lifetime.
- Do not use `asyncio.run()` inside handlers; the application already owns the event loop.

## Parallel Work with `asyncio.gather()`

Use `asyncio.gather()` when independent async operations can safely run in parallel and failure behavior is clear.

```python
executor_role, target = await asyncio.gather(
    db.users_db.get_effective_role(executor_id),
    extraction.extract_target(update, args, ctx.bot),
)
```

Guidelines:

- Only gather operations that do not depend on each other.
- Prefer normal `gather()` when any failure should abort the operation.
- Use `return_exceptions=True` only when each result is inspected explicitly.
- Do not create unbounded task lists for large group or user sets; use `fan_out()` or a semaphore.

## Multi-Group Telegram Fan-Out

For moderation actions across connected groups, use the project helper instead of raw `gather()`.

```python
from tcbot.utils.dispatch import fan_out

active_groups = await db.groups_db.active_groups()
results = await fan_out(
    [
        ctx.bot.ban_chat_member(group["chat_id"], target_id)
        for group in active_groups
    ]
)

failures = [result for result in results if isinstance(result, BaseException)]
```

Why:

- `fan_out()` bounds concurrency.
- It returns results in order.
- It prevents one group failure from cancelling every other group action.
- It makes partial failures reportable in moderation logs.

## Motor/MongoDB Patterns

Database helpers should be async, typed, and domain-focused.

```python
from __future__ import annotations

from tcbot.database import mongos


async def get_group(chat_id: int) -> dict[str, object] | None:
    return await mongos.groups().find_one({"chat_id": chat_id})
```

Project expectations:

- Handlers call database helper modules; helpers call Motor collections.
- Add indexes in the central index setup when adding indexed queries.
- Keep Mongo document field changes backward-compatible unless a migration plan exists.
- Avoid returning Motor cursors to handlers; convert to plain lists inside helpers when practical.
- Use projection when large documents do not need every field.

## Timeouts and Cancellation

Use `asyncio.timeout()` for local async operation bounds in Python 3.12. Use `ConversationHandler` timeouts and project config for workflow deadlines.

```python
import asyncio


async def fetch_with_timeout(user_id: int) -> dict[str, object] | None:
    try:
        async with asyncio.timeout(3):
            return await db.users_db.get_user(user_id)
    except TimeoutError:
        log.warning("Timed out loading user %s", user_id)
        return None
```

Cancellation rules:

```python
async def worker() -> None:
    try:
        await do_work()
    except asyncio.CancelledError:
        await cleanup()
        raise
```

Do not swallow `CancelledError`; the bot must be able to shut down cleanly.

## Background Jobs

Use PTB's job queue for scheduled or delayed work. Keep job callbacks short, async, and observable.

```python
from telegram.ext import ContextTypes


async def expire_pending_appeal(ctx: ContextTypes.DEFAULT_TYPE) -> None:
    job_data = ctx.job.data if ctx.job else {}
    appeal_id = job_data.get("appeal_id")
    if not appeal_id:
        return

    await db.appeals_db.mark_expired(str(appeal_id))
```

Guidelines:

- Store only primitive IDs or small serializable payloads in job data.
- Re-load current state from the database inside the job.
- Make jobs idempotent; they may run after state changed elsewhere.
- Log unexpected exceptions with enough IDs to diagnose without exposing secrets.

## Blocking Work to Avoid

Avoid these in async handlers and database helpers:

- `time.sleep()`; use `await asyncio.sleep()`.
- Synchronous HTTP clients; use an async client only if the project already depends on one, or justify a new dependency.
- Long CPU loops, image processing, compression, or parsing large files on the event loop.
- Synchronous database drivers.
- Raw subprocess calls from handlers.

If unavoidable, isolate the work:

```python
result = await asyncio.to_thread(sync_cpu_or_file_work, arg)
```

Use this sparingly; do not hide heavy product behavior in a thread without considering capacity and observability.

## Callback Query Pattern

Always answer callback queries before doing visible work.

```python
query = update.callback_query
if query is None:
    return

await query.answer()
await query.edit_message_text("Processing complete.", parse_mode="HTML")
```

This avoids Telegram client spinners and keeps UX responsive.

## Async Testing

The project config enables `pytest-asyncio` auto mode, so async tests can be plain `async def` tests.

```python
async def test_get_group_returns_document(fake_groups_collection) -> None:
    await fake_groups_collection.insert_one({"chat_id": -100123, "active": True})

    group = await groups_db.get_group(-100123)

    assert group is not None
    assert group["active"] is True
```

Testing rules:

- Keep tests offline: no real Telegram token, no real MongoDB, no network calls.
- Fake PTB objects or call helper functions directly when possible.
- Assert side effects and sent messages through mocks/fakes.
- Include cancellation, timeout, or partial-failure cases when the change depends on them.

Validation commands:

```bash
uv run --extra test pytest tests/ -v
uv run ruff format .
uv run ruff check --fix .
```

For focused changes, run the nearest test file first, then broaden.

## Review Checklist

Before finishing async work, verify:

- Every coroutine is awaited or deliberately scheduled and tracked.
- No blocking call was added to a handler, callback, job, or Motor helper.
- Parallel work is bounded.
- Callback queries call `await query.answer()` first.
- Multi-group Telegram operations use `fan_out()`.
- Exceptions are logged or reported where they affect moderation outcomes.
- Cancellation is not swallowed.
- Tests remain offline and deterministic.

## References

- Project policy: `tgbot/.agents/skills/project-policy/SKILL.md`.
- Detailed async examples: `tgbot/.agents/skills/async-python-patterns/references/details.md`.
- Python asyncio documentation: https://docs.python.org/3/library/asyncio.html
- python-telegram-bot docs: https://docs.python-telegram-bot.org/
- Motor docs: https://motor.readthedocs.io/
