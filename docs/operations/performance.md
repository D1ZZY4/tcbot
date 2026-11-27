# Performance

This page describes the patterns TCF Bot uses to stay responsive while serving
many groups. It focuses on measured, bounded behavior rather than guarantees.
The concurrency and cache mechanics are described in
[runtime mechanics](../architecture/runtime.md).

Related pages: [database layer](../architecture/database.md) and
[statistics](../flows/statistics.md).

## Update processing

Kurigram uses a `KeyedUpdateProcessor` that serializes updates per `(chat, user)`
pair while leaving other conversations concurrent. A ConversationHandler
therefore sees one update at a time for one moderator, but a flood in one group
does not block the rest of the federation.

Rate limits are applied by the per-handler `ratelimiter()` tiers, one bucket
per user and wrapped handler, with the current Owner exempt. Ordinary chat
messages are not throttled by a global handler. Prefix filters are async so
they stay on the event loop instead of being offloaded to the client's thread
pool for every update. See
[bounded dispatch and breakers](../architecture/runtime.md#bounded-dispatch-and-breakers).

Kurigram's dispatcher workers are sized from CPU count and the database pool,
capped at the application's 64-slot handler limit. `KURIGRAM_WORKERS` can
override the count, also capped at 64. More workers improve throughput across
independent chats; they do not reduce the round trip of a single command or
edit, and an unbounded count only creates contention on the 10-connection pool.
The MTProto store keeps a bounded in-process peer cache so each rich edit does
not resolve its peer through PostgreSQL again.

## Bounded fan-out

Federation-wide Telegram work goes through `fan_out(coros, max_concurrent=10)`.
Telegram allows roughly 30 messages per second globally, so ten concurrent
calls are safe. The dispatcher admits slots lazily through a semaphore,
integrates the Telegram circuit breaker, and always propagates cancellation.
`gather_bounded()` provides the same limit for pure database bursts without
touching the breaker.

`count_transient_errors()` and friends turn the result list into operator
counts for moderation. There, benign refusals such as `USER_NOT_PARTICIPANT`
or `CHAT_NOT_FOUND` are not reported as failed groups, because there was
nothing to enforce. `/tcbroadcast` deliberately differs: it promises delivery,
so it counts every failed send, including benign refusals, in its Failed line.

Circuit breakers open after five accumulated transient failures; successes in
CLOSED do not reset that count, and a long healthy streak decays it. They admit
one probe after 60 seconds. Workers pause entirely while the breaker is open so
a slot skipped by the breaker never burns a retry attempt.

## Database access

Every read and write goes through `engine.db_call()` with a 20-second timeout
and the `postgres` circuit breaker. `run_transaction()` keeps multi-statement
units atomic. Connection pool size and overflow come from `DB_POOL_SIZE` and
`DB_MAX_OVERFLOW`; they must fit the connection limit granted by the database,
because an oversized pool fails later as "max clients reached" rather than at
startup.

Prefer batch helpers over per-row queries:

| Instead of | Use |
|---|---|
| One mention lookup per row | `users_cache.get_mention_data_batch(ids)` |
| One first-name lookup per row | `users_cache.get_first_names_batch(ids)` |
| Repeated active-group reads | `groups_db.active_groups()` |

Batch reads capture the cache revision before their database query and skip
publishing a row if an invalidation landed during the read, so a stale batch
cannot undo an erasure or profile update.

## Caching

The two-level cache has an in-process L1 layer and an optional Redis L2 layer.
L1 is always present, so a Redis outage does not block handlers. Keys use the
`v2` namespace with the configured database schema as the tenant boundary,
and tagged JSON values keep the wire format compatible with existing entries.

| Cache | L1 TTL | L2 TTL |
|---|---|---|
| Effective role | 60 s | 90 s |
| Connected state | 120 s | 180 s |
| Active groups | 30 s | 45 s |
| Owner id | 300 s | 360 s |
| Mentions and locales | 300 s | 600 s |

A per-key single-flight lock means concurrent misses for one key run one source
read. Generation counters and a cache-wide epoch discard results fetched
across an invalidation. Redis mutations are chained FIFO per prefix and event
loop and bounded by depth, so a slow write cannot complete after a newer
delete. Revocation prefixes use non-droppable deletes.

Enforcement reads pass `fresh=True` to bypass caches. This keeps a demotion or
transfer in another process from hiding behind a TTL.

## Workers and schedulers

The enforcement worker claims at most 10 runs per tick and at most 100 targets
per run, delivering through `fan_out()` with a 20-second per-action timeout.
Each target has three attempts with a five-minute retry deadline. The
notification worker claims at most 10 due card edits per tick with five
attempts and the same retry interval. Both pause on an open circuit and admit
one probe in half-open state.

APScheduler runs maintenance jobs with a SQLAlchemy job store. pg_cron can own
the pure-database expiry, role-expiry, and reconciliation jobs when
`PG_CRON_ENABLED` is set and the extension exists; Telegram-dependent jobs
stay with APScheduler. The handoff removes all owned pg_cron jobs on a partial
failure so two owners never run the same sweep.

## Avoiding blocking work

Handlers and database helpers never use `time.sleep()`, synchronous HTTP
clients, or long CPU loops on the event loop. If unavoidable, isolate the work
with `asyncio.to_thread()`. Background refresh tasks are supervised by
`TaskTracker` and drained during shutdown.

## Measurement

The project ships `py-spy` as a development dependency for profiling, and an
optional `prometheus-client` endpoint at `/metrics`. Run
`uv run python scripts/benchmark_hotpath.py` for an in-process baseline of the
database-call boundary, the cache on hit and miss, and the bounded fan-out. It
needs no external service; use the numbers as a relative baseline, not a latency
promise. The `/health` response
reports database, Redis, scheduler, polling, and Telegram circuit state. Relevant
counts in logs include enforcement attempt outcomes, member-cache drops, and
rate-limit waits. Use these signals to decide whether to tune a pool size, a TTL, or a
fan-out bound; do not change them speculatively.

## Validation hints

- `tests/test_dispatch.py` and `tests/test_circuit_breaker.py` cover concurrency.
- `tests/test_cache_*.py` covers invalidation and outage behavior.
- `tests/test_scheduler_budgets.py` and `tests/test_moderation_enforcement.py`
  cover worker limits.

Run a focused check with:

```bash
uv run pytest tests/ -q -k "dispatch or cache or enforcement"
```
