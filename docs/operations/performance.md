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
  bounded by the client's 2 s socket timeout, so a stalled Redis falls through
  to the DB fetch instead of holding the hot path, and L2 writes are
  fire-and-forget FIFO mutations that can never fail the fetch (a
  payload-encode failure degrades to L1-only);
- `COUNT(*)` on the narrowest index for count-only views;
- callback acknowledgement alongside independent callback work where safe;
- `fan_out()` from `tcbot/utils/dispatch.py` to bound concurrent work across
  groups (batch joins use a local semaphore with the same bound);
  `gather_bounded()` from the same module bounds pure database bursts
  (for example bulk deactivations during cleanup) without touching the
  Telegram circuit breaker;
- bounded identity resolution: a fresh stored profile is used when available,
  and an unknown user is resolved with a bounded probe set (see below);
- cached rate-limit reads (`_is_exempt` and the command-bucket tier read the
  owner and effective-role caches) while authorization gates for commands and
  enforcement read the role tables directly (`fresh=True`), so a demotion or
  transfer in another process is never hidden behind a TTL;
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

Unknown-user resolution (`extraction/refresh._fetch_live_identity`) tries one
bounded `get_chat`, then probes connected groups with `get_chat_member`. Probes
run concurrently under a semaphore (10, matching the `fan_out` Telegram cap)
with an overall 15 s deadline; the first hit in group order wins. Probes never
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
- `clear_all()` is required when the entire Redis prefix must be invalidated. It
  advances a cache-wide epoch on both sides of the sweep and clears L1 again
  when the sweep ends, so a read that overlapped it cannot republish old state.
- `invalidate(key)` is preferred when the changed record identifies one key.
- Redis is optional. Without `REDIS_URL`, the cache remains in-process.
- Revocation prefixes (`role`, `conn`, `groups`, `owner`) write a
  short-lived tombstone before the Redis delete. A reader in another
  process that misses L1 pays one extra EXISTS on the tombstone, and skips
  the old L2 value while the delete is in flight.
- `tcbot_cache_hits_total{layer}`, `tcbot_cache_misses_total`,
  `tcbot_cache_invalidations_total`, `tcbot_cache_invalidation_drops_total{prefix}`,
  `tcbot_cache_queue_evictions_total{prefix}`, `tcbot_cache_queue_depth{prefix}`,
  and `tcbot_redis_available` are exposed on `/metrics` when the observability
  extra is installed. The same counters are available in-process through
  `tcbot.utils.metrics.snapshot()` for tests and diagnostics.

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
pool 15 s) are applied by `__main__.py` for both webhook and polling transport.
Polling mode adds a dedicated getUpdates connection pool of 4
(`_UPDATES_POOL_SIZE`, defined in `tcbot/__main__.py`). On top of the pool,
`fan_out()` caps in-flight Telegram calls at 10 via its semaphore, so the
connection count stays bounded regardless of how many groups are connected.

## Connection pool and per-call budget

Database calls are asynchronous: the driver awaits the server on the event
loop, so no worker thread is involved and no default-executor slot can be
starved by a slow query. The pool is sized from configuration
(`DB_POOL_SIZE`, default 5, plus `DB_MAX_OVERFLOW`, default 5) in
`tcbot/database/engine.py`, with a 10 s pool timeout and a 30-minute recycle
so a proxy never hands out a dropped connection. Keep the total within the
connection limit the database grants this user; a pool larger than that limit
fails later as a refused connection, which the circuit breaker reads as an
outage.

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

The daily stale-record sweep passes `timeout=None` for its two bulk deletes
(membership cache and erasure queue), because a delete over a large history
can run long; the run as a whole is bounded by a 60 s deadline. The expiry
sweep moves the due decisions and role assignments and queues the revoke runs
in one transaction with the same 60 s budget, so a decision can never expire
without the job that lifts the restriction. Both sweeps take a transaction
advisory lock, so overlapping bot instances cannot duplicate the work. The
five-minute enforcement worker consumes the queue and applies the decision on
Telegram; ban and mute application, manual unbans, approved appeals, and kick
unban repair use the same ledger. A retryable delivery failure is recorded as `failed` with a due
deadline (the only transition the target trigger accepts), and the run is
re-queued when that deadline arrives; a target is tried at most three times.

A warning does not maintain a counter row. The per-group and federation counts
are read from the `warn_counts` view over the decision history, so the count
cannot fall behind the warnings that produced it and there is no repair path.
The count that the threshold reads filters on the decision status and its
expiry, so a revoked or lapsed warning stops counting without rewriting
history.

## Redis reconnect

A Redis outage during boot used to disable the shared cache for the rest of
the process lifetime, so cross-process role and connection state diverged
until the key TTL expired. The client is now re-established lazily: the first
cache operation after a failure asks for a reconnect, rate-limited to one
attempt per 30 s. The shared cache is optional, so a dead Redis still degrades
to the in-memory layer without delaying a request.

The mutation queue is bounded at three levels. Droppable operations (the
display-name hints) are dropped past 200 queued mutations. At the 1000-deep
hard ceiling a critical mutation first evicts the oldest queued droppable
mutation that has not started, so a pending revocation is not lost in favour
of a display hint. Only the 2000-deep absolute ceiling, where every queued
mutation is critical, drops a revocation with an error-level warning: a
dropped revocation leaves the revoked state visible until the key TTL, while
an unbounded queue exhausts the process memory. Evictions, drops, and queue
depth are exported as cache counters.

The Redis client belongs to the event loop that created it: its sockets are
bound to that loop. A client that is handed to another running loop would
wait for an answer that can never arrive, so the cache treats it as absent
and the reconnect path replaces it. The bot runs one loop for the whole
process, so the client stays valid there. The guard exists for the case
where the loop is replaced under a live client.

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
