# Performance and Scaling Notes

For database helpers and indexes, see
[`../architecture/database.md`](../architecture/database.md). For the check
command, see
[`../features/moderation/check.md`](../features/moderation/check.md).

This guide documents the performance techniques present in the code and the
checks to use when extending them. It does not promise fixed latency:
PostgreSQL, Redis, Telegram, network distance, workload, and the hosting platform
all affect response time.

## Current design

The bot currently uses:

- batch queries in list and detail views to avoid repeated user and group reads;
- PostgreSQL projections and indexes for frequently accessed fields;
- `asyncio.gather()` for independent database and Telegram operations;
- `TwoLevelCache` with an in-process L1 and optional Redis L2: L2 reads are
  bounded (1 s cap) so a stalled Redis falls through to the DB fetch instead
  of holding the hot path, and L2 writes are fire-and-forget FIFO mutations
  that can never fail the fetch (a payload-encode failure degrades to
  L1-only);
- `COUNT(*)` on the narrowest index for count-only views;
- callback acknowledgement alongside independent callback work where safe;
- `fan_out()` from `tcbot/utils/dispatch.py` to bound concurrent work across
  groups (batch joins use a local semaphore with the same bound);
  `gather_bounded()` from the same module bounds pure database bursts
  (for example bulk deactivations during cleanup) without touching the
  Telegram circuit breaker;
- cached auth reads (`owner_only` via the cached owner ID, `staff_only` via
  the cached effective role) so repeated permission checks cost no database
  round trip on cache hits;
- circuit breakers around PostgreSQL and Telegram operations.

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

Batch helpers check the in-memory mention cache first: cached IDs are served
without I/O and repeat IDs are dropped, so only the uncached remainder hits
one database query. Users absent from the database get a not-found sentinel
cached so repeat renders skip the round-trip.

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

The index definitions live in `tcbot/database/base/` and are created by
the Alembic migration. Current examples:

```text
telegram_users: (username_lower, user_id) and (first_name_lower, user_id) with text_pattern_ops, for the name search
telegram_users: (username_lower, user_id) and (first_name_lower, user_id) with the default opclass, for the paged sort
moderation_actions: unique partial (target_user_id) where the action is an active ban, for get_active_ban
moderation_actions: (target_user_id, created_at desc) for the per-user decision history
moderation_actions: (action_type, status) for the active-ban, active-mute, and warn filters
```

One column often needs two indexes. `text_pattern_ops` provides the
pattern comparison operators, which is what makes a `LIKE 'prefix%'` scan
work under a non-C collation, but it provides no ordering operators, so
the index cannot serve an `ORDER BY` on the same column. The paged users
list sorts on the lowercase mirrors, so it needs the default-opclass
indexes as well. Without them the planner sorts the whole identity table on
every page turn: on 50,000 rows the page query drops from about 9.7 ms
to about 1.5 ms, and the statement itself from 8.97 ms to 0.09 ms.

When adding a query with a new filter or sort order:

1. inspect the existing indexes;
2. add the index in `base.py` when needed and generate the matching Alembic revision;
3. keep the database helper and its row typing in sync;
4. use PostgreSQL `EXPLAIN (ANALYZE, BUFFERS)` or production metrics to verify the change.

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
FIFO queue, moderation actions should use `fan_out()` rather than an
unbounded `gather()` across groups, and pure database bursts across groups
should use `gather_bounded()` for the same reason without involving the
Telegram circuit breaker.

For callback handlers, acknowledge the callback before doing dependent work.
When the database read is independent, existing handlers may run the
acknowledgement and read together, but errors must still be handled explicitly.

### Bounded identity resolution

Unknown-user resolution (`extraction._fetch_live_identity`) tries one bounded
`get_chat`, then probes connected groups with `get_chat_member`. Probes run
concurrently under a semaphore (10, matching the `fan_out` Telegram cap) with
an overall 15 s deadline; the first hit in group order wins. Probes never
touch the Telegram circuit breaker: a timeout is only an identity miss, not
congestion evidence. Callers that can tolerate staleness should render from
cache first and refresh in the background via `launch_identity_refresh`.

### Stable-ID detail lookups

List buttons carry a stable entity ID so detail views can verify the record
instead of trusting its position. `Stats.ban_detail` with a stable ban ID
fetches the record directly via `bans_db.get_ban` (one indexed read) rather
than re-reading the whole active-ban list, which also makes the view immune
to list shifts between render and tap.

## Caches

Use the cache layer already associated with the database helper:

- L1-only `clear()` is appropriate when only the current process needs
  invalidation.
- `clear_all()` is required when the entire Redis prefix must be invalidated.
- `invalidate(key)` is preferred when the changed record identifies one key.
- Redis is optional. Without `REDIS_URL`, the cache remains in-process.

Do not add a second cache namespace or bypass the cache with a direct Redis
operation. An L2 write can never fail the fetch it follows: after a database
fetch succeeds the value is already serving from L1, and a payload-encode
failure or a slow Redis write degrades to L1-only instead of raising. See
[`../architecture/database.md`](../architecture/database.md) for TTL,
serialization, and invalidation details.

## Telegram transport pool

Outbound Telegram HTTP tuning lives in one owner, `tcbot/utils/transport.py`
(see [`../architecture/utilities.md`](../architecture/utilities.md)):
`API_POOL_SIZE` (16) and the timeouts (read 60 s, write 30 s, connect 30 s,
pool 15 s) are applied identically by `__main__.py` and `serverless.py`.
Polling mode adds a dedicated getUpdates connection pool of 4
(`_UPDATES_POOL_SIZE`, defined in `tcbot/__main__.py`). On top of the pool,
`fan_out()` caps in-flight Telegram calls at 10 via its semaphore, so the
connection count stays bounded regardless of how many groups are connected.

## Connection pool and per-call budget

Database calls are asynchronous: the driver awaits the server on the event
loop, so no worker thread is involved and no default-executor slot can be
starved by a slow query. The pool is sized explicitly in
`tcbot/database/engine.py`: 20 pooled connections plus 10 overflow, a 10 s
pool timeout, and a 30-minute recycle so a proxy never hands out a dropped
connection.

Every call is also bounded by default. `db_call(op, timeout=...)` defaults to
20 s and raises `TimeoutError` when the operation does not answer in time. A
timeout counts as a transient failure and therefore opens the PostgreSQL
circuit like any other connection error. The operations listed below are the
only ones that opt out, and each one states why.

Reads do not open a transaction. `fetch_all`, `fetch_one`, `fetch_value`,
`fetch_count`, and `count_rows` run on an autocommit connection, so a read
is one round trip instead of one plus the `COMMIT` that would close the
transaction. The isolation level is reverted when the connection returns
to the pool, so a write that follows still runs in a normal transaction.

The pool validates a connection before handing it out (`pool_pre_ping`), so
a read costs two round trips: the validation and the statement. The
autocommit saving removes the `COMMIT` round trip and the pre-ping adds
one back, so the net gain over a transactional read is the difference
between the two, not the whole transaction overhead. Measured against the
deployment schema over a network link, a single-row lookup costs about
0.86 ms without the pre-ping and about 1.08 ms with it, against 1.08 ms
for the transactional form.

Operations that are legitimately long carry their own budget. The
warn-history and counter deletes pass `timeout=None`, because a
federation-wide clear removes every warning row of one user across every
group. The daily warn-expiry sweep runs its two bulk deletes in one
transaction with a 60 s budget, because a bulk delete over a large
history can run long and the sweep reports the deadline it used.

A warning is written without a scan of the history. The counter row
normally exists and the upsert increments it, so the history count is
only needed when the row is missing. The statement makes the database
evaluate just the branch it needs, so the common path never counts the
history and the slow path only runs on a counter that was lost.

## Redis reconnect

A Redis outage during boot used to disable the shared cache for the rest of
the process lifetime, so cross-process role and connection state diverged
until the key TTL expired. The client is now re-established lazily: the first
cache operation after a failure asks for a reconnect, rate-limited to one
attempt per 30 s. The shared cache is optional, so a dead Redis still degrades
to the in-memory layer without delaying a request.

The mutation queue is bounded at two levels. Droppable operations (the
display-name hints) are dropped past 200 queued mutations, and even a
revocation operation is dropped past 1000, with an error-level warning: a
dropped revocation leaves the revoked state visible until the key TTL, while
an unbounded queue exhausts the process memory.

The Redis client belongs to the event loop that created it: its sockets are
bound to that loop. A client that is handed to another running loop would
wait for an answer that can never arrive, so the cache treats it as absent
and the reconnect path replaces it. The long-lived transports run one loop
for the whole process, and the serverless path keeps one shared loop across
warm invocations, so the client stays valid there. The guard exists for the
case where the loop is replaced under a live client.

## Measuring a suspected bottleneck

Measure a real workload before and after a change. A lightweight development
timing log can identify the slow section without turning a timing claim into a
project-wide promise:

py-spy profiles the running process without modifying code:

```bash
uv run py-spy record --pid <PID> --duration 60 --rate 20 --format speedscope --output profile.svg
```

The in-process micro-benchmark measures the primitives every request pays for
(the database call transport, the two-level cache, and the bounded fan-out).
It needs no PostgreSQL, Redis, or Telegram connection, so it runs anywhere:

```bash
uv run python scripts/benchmark_hotpath.py
```

It reports the median and p95 per scenario and prints the observed fan-out
concurrency, which must stay at the cap of 10. Treat the numbers as a
relative baseline for one machine: the absolute values depend on the host and
its load.

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
- [ ] Multi-group work uses bounded `fan_out()` (Telegram) or
      `gather_bounded()` (pure database).
- [ ] Cache writes invalidate the relevant key or prefix.
- [ ] Callback queries are acknowledged and callback errors are handled.
- [ ] The change was measured against a representative workload when a latency
      issue motivated it.

## Related documentation

- [`../architecture/database.md`](../architecture/database.md): tables,
  indexes, caches, and scheduler storage.
- [`../architecture/helpers.md`](../architecture/helpers.md): batch helpers,
  target resolution, and rate limiting.
- [`../architecture/utilities.md`](../architecture/utilities.md): circuit
  breakers and bounded dispatch.
