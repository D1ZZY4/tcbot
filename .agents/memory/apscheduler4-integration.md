---
name: APScheduler 4 integration
description: Critical constraints when integrating APScheduler 4.x AsyncScheduler with a PTB bot — serializer choice and AnyIO cancel-scope task ownership
---

## Rule 1: Use CBORSerializer, not the default PickleSerializer

APScheduler 4.0.0a6 (and likely later alphas) ships with a `PickleSerializer` as default for `MongoDBDataStore`. Pickle **cannot serialize** `ZoneInfo` objects loaded from file streams (raised as `_pickle.PicklingError: Cannot pickle a ZoneInfo file from a file stream`). This affects `CronTrigger`, `IntervalTrigger`, and any trigger that stores timezone state.

**Fix:** always pass `serializer=CBORSerializer()` to `MongoDBDataStore`. Requires `cbor2` in `pyproject.toml`.

```python
from apscheduler.serializers.cbor import CBORSerializer
from apscheduler.datastores.mongodb import MongoDBDataStore

data_store = MongoDBDataStore(mongodb_uri, database=db_name, serializer=CBORSerializer())
```

**Why:** `cbor2` handles `ZoneInfo` and other Python types that pickle cannot. The `cbor` serializer module is bundled with apscheduler; only `cbor2` (the underlying library) needs to be added separately.

**How to apply:** Whenever `MongoDBDataStore` (or any APScheduler data store using the default serializer) is instantiated.

---

## Rule 2: Keep `async with AsyncScheduler()` in a single dedicated asyncio task

AnyIO cancel scopes must be **entered and exited in the same asyncio task**. PTB's `run_polling()` calls `_post_init` and `_post_shutdown` in different coroutine contexts. If `async with AsyncScheduler()` spans `__aenter__` in one PTB hook and `__aexit__` in another, AnyIO raises:

```
RuntimeError: Attempted to exit cancel scope in a different task than it was entered in
```

**Fix:** Run the entire `async with AsyncScheduler()` block inside a dedicated `asyncio.create_task(...)`. Use `asyncio.Event` objects to synchronise lifecycle:

- `_sched_ready`: set after the scheduler enters `async with` and is ready for schedule operations.
- `_sched_stop`: set by `stop()` to trigger graceful exit of `async with`.

The `start()` function creates the task and awaits `_sched_ready`. The `stop()` function sets `_sched_stop` and awaits the task.

**Why:** The background task owns the cancel scope for its entire lifetime. PTB hooks only signal the task (via Events) — they never enter or exit the scope themselves.

**How to apply:** Any time APScheduler 4 `AsyncScheduler` is used in a long-running application where startup and shutdown happen in different coroutine contexts (e.g., PTB `post_init` / `post_shutdown`).

---

## Additional notes

- `IntervalTrigger` does **not** accept a `timezone` parameter — passing one raises `TypeError`.
- `uv sync --prerelease=allow` is required for APScheduler 4.0.0a6 (pre-release); the normal `uv sync` resolves to the pre-release if the lockfile already pins it.
- PTB `[job-queue]` extra requires APScheduler ~3.x and conflicts with APScheduler 4.x — use plain `python-telegram-bot` (no extra) when APScheduler 4 is in the stack.
