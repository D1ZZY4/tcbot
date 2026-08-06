# Performance and Scaling Notes

For database helpers and indexes, see
[`../architecture/database.md`](../architecture/database.md). For the check
command, see
[`../features/moderation/check.md`](../features/moderation/check.md).

This guide documents the performance techniques present in the code and the
checks to use when extending them. It does not promise fixed latency:
MongoDB, Redis, Telegram, network distance, workload, and the hosting platform
all affect response time.

## Current design

The bot currently uses:

- batch queries in list and detail views to avoid repeated user and group reads;
- MongoDB projections and indexes for frequently accessed fields;
- `asyncio.gather()` for independent database and Telegram operations;
- `TwoLevelCache` with an in-process L1 and optional Redis L2;
- `estimated_document_count()` for count-only views where an exact count is not
  required;
- callback acknowledgement alongside independent callback work where safe;
- `fan_out()` from `tcbot/utils/dispatch.py` to bound concurrent work across
  groups;
- circuit breakers around MongoDB and Telegram operations.

The webhook receiver and polling fallback affect transport latency, but neither
removes the network time required by Telegram API calls.

## Database access

### Prefer batch helpers

Avoid a database call inside a loop when a helper can fetch the same data in
one operation:

```python
user_ids = [item["user_id"] for item in items]
name_map = await db.users_cache.get_first_names_batch(user_ids)

for item in items:
    name = name_map[item["user_id"]]
    # Format the item using the already-fetched name.
```

Available batch helpers include:

- `users_cache.get_first_names_batch(user_ids)`
- `users_cache.get_mention_data_batch(user_ids)`
- `groups_db.get_group_titles(chat_ids)`

For partial-name target resolution, use
`users_cache.search_by_name(needle, limit)` instead of loading every cached
user.

### Use projections through database helpers

Choose the narrowest existing helper for the data you need. For example,
`get_user_mention_data()` returns only the fields needed to build a mention,
while `get_user()` returns the complete cached profile. New query shapes belong
in the relevant `tcbot/database/*_db.py` module so the query and its index can
be reviewed together.

### Keep indexes aligned with query shapes

Startup index creation lives in `tcbot/database/mongos.py`. Current examples
include:

```text
member_cache: user_id, first_name, username
bans: banned_user_id + is_active
warns: user_id + chat_id + timestamp
warn_counts: unique user_id + chat_id
```

When adding a query with a new filter or sort order:

1. inspect the existing indexes;
2. add the index in `ensure_indexes()` when needed;
3. keep the database helper and its document typing in sync;
4. use MongoDB `explain()` or production metrics to verify the change.

## Async concurrency

Use `asyncio.gather()` only for operations that do not depend on one another:

```python
user_data, role, ban = await asyncio.gather(
    db.users_cache.get_user(user_id),
    db.users_roles.get_effective_role(user_id),
    db.bans_db.get_active_ban(user_id),
)
```

Do not parallelize operations when ordering is part of correctness. Redis
cache mutations sharing a prefix are deliberately serialized through their
FIFO queue, and moderation actions should use `fan_out()` rather than an
unbounded `gather()` across groups.

For callback handlers, acknowledge the callback before doing dependent work.
When the database read is independent, existing handlers may run the
acknowledgement and read together, but errors must still be handled explicitly.

## Caches

Use the cache layer already associated with the database helper:

- L1-only `clear()` is appropriate when only the current process needs
  invalidation.
- `clear_all()` is required when the entire Redis prefix must be invalidated.
- `invalidate(key)` is preferred when the changed record identifies one key.
- Redis is optional. Without `REDIS_URL`, the cache remains in-process.

Do not add a second cache namespace or bypass the cache with a direct Redis
operation. See
[`../architecture/database.md`](../architecture/database.md) for TTL,
serialization, and invalidation details.

## Measuring a suspected bottleneck

Measure a real workload before and after a change. A lightweight development
timing log can identify the slow section without turning a timing claim into a
project-wide promise:

```python
import time

started = time.perf_counter()
result = await slow_operation()
elapsed = time.perf_counter() - started
log.debug("Operation took %.3f seconds", elapsed)
```

Investigate:

1. repeated awaits inside loops;
2. sequential independent reads;
3. queries that fetch full documents unnecessarily;
4. missing indexes for filters and sort orders;
5. unbounded Telegram fan-out;
6. cache misses caused by inconsistent keys or invalidation.

## Review checklist

Before merging a performance-sensitive change, verify:

- [ ] List views use batch helpers where available.
- [ ] Independent async operations are concurrent and dependent operations
      remain ordered.
- [ ] Database reads use an existing projection or add one in the helper.
- [ ] New query patterns have a matching index or a documented reason not to
      add one.
- [ ] Multi-group work uses bounded `fan_out()`.
- [ ] Cache writes invalidate the relevant key or prefix.
- [ ] Callback queries are acknowledged and callback errors are handled.
- [ ] The change was measured against a representative workload when a latency
      issue motivated it.

## Related documentation

- [`../architecture/database.md`](../architecture/database.md): collections,
  indexes, caches, and scheduler storage.
- [`../architecture/helpers.md`](../architecture/helpers.md): batch helpers,
  target resolution, and rate limiting.
- [`../architecture/utilities.md`](../architecture/utilities.md): circuit
  breakers and bounded dispatch.