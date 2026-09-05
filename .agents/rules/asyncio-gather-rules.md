# Asyncio Gather and Fan-Out Rules

This file defines async patterns for TCF Bot: handler structure,
`asyncio.gather()` use, bounded multi-group fan-out, timeouts, cancellation,
background jobs, and async database access. Handler authorization lives in
[`security-rules.md`](security-rules.md), Python style and module boundaries
live in [`code-style.md`](code-style.md), and validation commands live in
[`tooling-validation.md`](tooling-validation.md).

---

## Pattern Selection

| Situation | Preferred pattern |
|---|---|
| One Telegram API call | Direct `await` |
| A few independent DB/API reads | `asyncio.gather()` |
| Federation-wide Telegram actions | `tcbot.utils.dispatch.fan_out()` |
| User-driven multi-step input | `ConversationHandler` flow in `*_flow.py` |
| Scheduled expiration or cleanup | APScheduler via `tcbot/database/scheduler.py` |
| Blocking file or CPU-heavy work | Avoid; if necessary, `asyncio.to_thread()` |

## Async Handlers

Handlers are small orchestration functions. Put persistence in
`tcbot/database/*_db.py`, shared formatting in helpers, and reusable workflow
logic in `tcbot/modules/helper/workflows/*_flow.py`.

```python
async def cmd_example(update: Update, ctx: ContextTypes.DEFAULT_TYPE) -> None:
    msg = update.effective_message
    user = update.effective_user
    if msg is None or user is None:
        return

    record = await db.users_cache.get_user(user.id)
    label = esc(record.get("first_name", user.first_name) if record else user.first_name)

    await msg.reply_text(
        f"User: {label}\nID: {code(str(user.id))}",
        parse_mode="HTML",
    )
```

Rules:

- Guard `effective_message`, `effective_user`, and `effective_chat` when they
  can be absent.
- Keep handler call paths async end-to-end.
- Always `await` Telegram API calls and Motor calls.
- Do not call `asyncio.run()` inside handlers; the application already owns
  the event loop.

## Parallel Work with `asyncio.gather()`

Use `asyncio.gather()` when independent async operations can safely run in
parallel and failure behavior is clear.

```python
executor_role, target = await asyncio.gather(
    db.users_roles.get_effective_role(executor_id),
    extraction.extract_target(update, args, ctx.bot),
)
```

Rules:

- Only gather operations that do not depend on each other.
- Prefer normal `gather()` when any failure should abort the operation.
- Use `return_exceptions=True` only when each result is inspected explicitly;
  never treat the result list as if every element succeeded.
- Do not create unbounded task lists for large group or user sets; use
  `fan_out()` or a semaphore.
- Preserve sequential awaits when a later operation depends on an earlier
  result, ordering is part of the contract, or side effects must be
  serialized.

## Multi-Group Telegram Fan-Out

For moderation actions across connected groups, use the project helper instead
of raw `gather()`.

```python
from tcbot.utils.dispatch import count_transient_errors, fan_out

active_groups = await db.groups_db.active_groups()
results = await fan_out(
    [ctx.bot.ban_chat_member(group["chat_id"], target_id) for group in active_groups]
)
failed = count_transient_errors(results)
```

Rules:

- Use `fan_out()` for bounded multi-group operations; it bounds concurrency,
  returns results in order, and keeps one failed group from aborting the rest.
- Count operator-facing failures with `count_transient_errors()` so benign
  Telegram refusals do not look like failed groups.
- Report partial failures in staff-facing summaries and audit logs when the
  action is federation-wide.

## Timeouts and Cancellation

Use `asyncio.timeout()` for local async operation bounds. Use `cfg` values
such as `cfg.proof_timeout` and `cfg.appeal_timeout` for workflow deadlines,
never hardcoded literals.

```python
async def fetch_with_timeout(user_id: int) -> dict[str, object] | None:
    try:
        async with asyncio.timeout(3):
            return await db.users_cache.get_user(user_id)
    except TimeoutError:
        log.warning("Timed out loading user %s", user_id)
        return None
```

Rules:

- Wrap external Telegram lookups in `asyncio.wait_for(timeout=...)`.
- Preserve cancellation semantics: catch `asyncio.CancelledError` only to
  clean up, then re-raise.
- Never hide cancellation with broad exception handlers.
- Supervise background tasks and log or report their errors.

```python
async def worker() -> None:
    try:
        await do_work()
    except asyncio.CancelledError:
        await cleanup()
        raise
```

## Background Jobs

Scheduled work runs on APScheduler 3.11.3 `AsyncIOScheduler` with
`MongoDBJobStore` via `tcbot/database/scheduler.py` (`schedule_unban()` /
`cancel_schedule()`). This project does not use the PTB `[job-queue]` extra.

Rules:

- Store only primitive IDs or small serializable payloads in job data.
- Re-load current state from the database inside the job.
- Make jobs idempotent; they may run after state changed elsewhere.
- Log unexpected exceptions with enough IDs to diagnose without exposing
  secrets.

## Motor Access from Async Code

Database helpers are async, typed, and domain-focused. Handlers call database
helper modules; helpers call Motor collections.

Rules:

- Module boundaries and collection ownership follow `code-style.md`; the rules
  below cover async behavior only.
- Avoid returning Motor cursors to handlers; convert to plain lists inside
  helpers when practical.
- Use projection when large documents do not need every field.
- Add indexes in `mongos.ensure_indexes()` when adding indexed queries.
- Pre-resolve per-item lookups for paginated views before formatting.

## Blocking Work to Avoid

Avoid these in async handlers and database helpers:

- `time.sleep()`; use `await asyncio.sleep()`.
- Synchronous HTTP clients; use an async client only if the project already
  depends on one, or justify a new dependency.
- Long CPU loops, image processing, compression, or parsing large files on
  the event loop.
- Synchronous database drivers.
- Raw subprocess calls from handlers.
- Blocking work on Flask keep-alive routes.

If unavoidable, isolate the work:

```python
result = await asyncio.to_thread(sync_cpu_or_file_work, arg)
```

Use this sparingly; do not hide heavy product behavior in a thread without
considering capacity and observability.

## Callback Queries

Always answer callback queries before doing visible work.

```python
query = update.callback_query
if query is None:
    return

await query.answer()
await query.edit_message_text("Processing complete.", parse_mode="HTML")
```

This avoids Telegram client spinners and keeps UX responsive.

## Review Checklist

Before finishing async work, verify:

- Every coroutine is awaited or deliberately scheduled and tracked.
- No blocking call was added to a handler, callback, job, or Motor helper.
- Parallel work is bounded.
- Callback queries call `await query.answer()` first.
- Multi-group Telegram operations use `fan_out()`.
- Exceptions are logged or reported where they affect moderation outcomes.
- Cancellation is not swallowed.
