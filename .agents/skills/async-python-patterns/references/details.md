# Async Python Patterns: TCBot Reference

For the parent skill instructions, see [`../SKILL.md`](../SKILL.md). For the canonical project async/fan-out rules, see [`../../../CLAUDE.md`](../../../CLAUDE.md). For database patterns referenced here, see [`../../mongodb-query-optimizer/SKILL.md`](../../mongodb-query-optimizer/SKILL.md).

Updated: 2026-05-29

This reference expands the `async-python-patterns` skill with practical examples for TCBot's Python 3.12, `python-telegram-bot` 22.5, and Motor/MongoDB stack.

## Choosing the Right Async Pattern

| Situation | Preferred pattern |
|---|---|
| One Telegram API call | Direct `await` |
| A few independent DB/API reads | `asyncio.gather()` |
| Federation-wide Telegram actions | `tcbot.utils.dispatch.fan_out()` |
| User-driven multi-step input | `ConversationHandler` flow in `*_flow.py` |
| Scheduled expiration or cleanup | PTB job queue |
| Blocking file or CPU-heavy work | Avoid; if necessary, `asyncio.to_thread()` |

## Direct Await

Use direct `await` when an operation is sequential or the next step depends on the result.

```python
user_doc = await db.users_cache.get_user(user_id)
if user_doc is None:
    await msg.reply_text("User is not known yet.", parse_mode="HTML")
    return

await msg.reply_text("User found.", parse_mode="HTML")
```

## Parallel Independent Reads

Use `asyncio.gather()` when operations are independent and all are required before continuing.

```python
import asyncio

executor_role, target_role, group = await asyncio.gather(
    db.users_roles.get_effective_role(executor_id),
    db.users_roles.get_effective_role(target_id),
    db.groups_db.get_group(chat_id),
)
```

Avoid gathering operations when one result determines whether the others should run. In those cases, sequence the calls for clearer control flow and fewer unnecessary database requests.

## Handling Partial Failures

When partial success is acceptable, inspect every result explicitly.

```python
results = await asyncio.gather(
    db.users_cache.get_user(user_id),
    db.groups_db.get_group(chat_id),
    return_exceptions=True,
)

for result in results:
    if isinstance(result, BaseException):
        log.warning("Lookup failed", exc_info=result)
```

Do not use `return_exceptions=True` and then treat the result list as if every element succeeded.

## Bounded Telegram Fan-Out

Use `fan_out()` for connected-group moderation because it bounds concurrency and keeps ordered results.

```python
from tcbot.utils.dispatch import fan_out

active_groups = await db.groups_db.active_groups()
results = await fan_out(
    [
        ctx.bot.restrict_chat_member(group["chat_id"], target_id, permissions)
        for group in active_groups
    ]
)

success_count = sum(1 for result in results if not isinstance(result, BaseException))
failure_count = len(results) - success_count
```

Report partial failures in staff-facing summaries and audit logs when the action is federation-wide.

## Cancellation-Safe Cleanup

Cancellation is part of normal shutdown and timeout behavior. Clean up, then re-raise.

```python
async def run_cleanup_job() -> None:
    try:
        await expire_old_records()
    except asyncio.CancelledError:
        log.debug("Cleanup job cancelled")
        raise
```

Never hide cancellation with broad exception handlers.

```python
try:
    await do_work()
except asyncio.CancelledError:
    raise
except Exception:
    log.exception("Work failed")
```

## Timeouts

Use Python 3.12 `asyncio.timeout()` for local bounds around an operation.

```python
async def safe_lookup(user_id: int) -> dict[str, object] | None:
    try:
        async with asyncio.timeout(3):
            return await db.users_cache.get_user(user_id)
    except TimeoutError:
        log.warning("Timed out loading user %s", user_id)
        return None
```

For conversation flows, use project configuration such as `cfg.proof_timeout` or `cfg.appeal_timeout` instead of local magic numbers.

## PTB Job Queue

Use the job queue for delayed state changes. Persist durable state in MongoDB and pass small IDs through job data.

```python
from telegram.ext import ContextTypes


async def expire_proof_request(ctx: ContextTypes.DEFAULT_TYPE) -> None:
    proof_id = (ctx.job.data or {}).get("proof_id") if ctx.job else None
    if proof_id is None:
        return

    await db.proofs_db.mark_expired(str(proof_id))
```

Job callbacks should be idempotent: if a record was already resolved, they should return cleanly.

## Motor Cursor Handling

Prefer turning cursors into concrete values inside database helpers.

```python
async def active_groups() -> list[dict[str, object]]:
    cursor = mongos.groups().find({"active": True})
    return await cursor.to_list(length=None)
```

Use projections for large documents or list views.

```python
cursor = mongos.groups().find(
    {"active": True},
    {"chat_id": 1, "title": 1, "_id": 0},
)
```

## Avoid Blocking the Event Loop

Do not use:

```python
time.sleep(1)
requests.get(url)
subprocess.run(args)
```

Inside handlers, callbacks, jobs, or database helpers. If blocking work is unavoidable and small, isolate it:

```python
result = await asyncio.to_thread(render_report_sync, report_data)
```

For recurring heavy work, design a bounded worker or external process instead of using unbounded threads.

## Review Prompts

When reviewing async code, ask:

1. Can this handler block polling?
2. Are all coroutines awaited?
3. Is concurrency bounded for potentially large lists?
4. Are partial Telegram failures visible to staff?
5. Can shutdown cancel this task cleanly?
6. Is durable state in MongoDB instead of only context memory?
