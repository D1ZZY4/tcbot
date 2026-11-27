# Runtime mechanics

This page documents the cross-cutting runtime layer: i18n, bounded dispatch and
breakers, transport budgets, logging and error reporting, supervised tasks,
update processing, workers, scheduling, and cache mechanics. Domain rules live
in [Security](security.md); flows and diagrams live under [Flows](../flows/system.md).

## Internationalization

`utils/i18n.py` loads every `i18n/<locale>/*.toml` catalog and flattens it into
dotted keys. `en-US` is the source of truth; missing keys fall back per key. The
`id` alias resolves to `id-ID` for stored preferences and in-flight callbacks.

`t(key, locale, **values)` substitutes keyword placeholders only. In rich mode
literal text is HTML-escaped and the backtick code, asterisk bold, and tilde
italic mini-markup spans become `<code>`, `<b>`, and `<i>`. `plain=True` keeps raw text for callback alerts
that Telegram never parses. `Safe` marks preformatted fragments from helpers
such as `user_ref()`, `code()`, and `bold()` so they pass through verbatim.
Placeholders must be bare names with no format specifications or conversions,
and mini-markup spans must be balanced, unnested, and free of braces.

`locale_for_update(ctx)` resolves once per handler: private chats use the
sender, groups use the group locale, direct messages use `locale_for_user`, and
updateless paths use `locale_for_chat`. These resolvers live in
`modules/helper/locale.py`; `resolve_locale()` applies explicit precedence, then
the chat-appropriate locale (the sender's in private chats, the group's in
groups), then the community default, then `en-US`. Resolution never raises. See
[Language](../features/language.md).

## Bounded dispatch and breakers

`fan_out(coros, max_concurrent=10)` runs Telegram calls concurrently under a
semaphore and integrates the Telegram breaker. While the circuit is `OPEN`, a
slot is skipped with `CircuitOpenError` instead of firing a call that would time
out; the unused coroutine is closed. `BadRequest` is an API refusal and does not
count as a failure, while Kurigram's `Timedout` and `Timeout`, `OSError`, and
builtin `TimeoutError` do. Cancellation always propagates.
`gather_bounded()` provides the same
concurrency bound for pure database bursts without breaker interaction.

Both breakers use `failure_threshold = 5` and `recovery_timeout = 60` seconds.
`HALF_OPEN` admits a single probe. A probe that reaches the service closes the
circuit; only a transient transport failure sends it back to `OPEN`. The
`admission_headroom` property reports how many calls a closed circuit can still
admit, which the enforcement worker uses to size its claims. See
[Performance](../operations/performance.md).

## Time and transport budgets

`time_and_date.py` owns `utc_now()`, `to_utc()`, `fmt_date()`, `fmt_time()`,
`date_or_unknown()`, `time_or_unknown()`, `parse_duration()`, `fmt_duration()`,
and monotonic measurement. All database timestamps are stored
in UTC, and naive values are assumed UTC before arithmetic. `parse_duration()`
accepts `s`, `m`, `h`, `d`, `w`, `mo`, and `ye` suffixes with a 366-day cap,
which stays inside Telegram's finite restriction limit.

`utils/transport.py` owns the two application-level deadlines
`TELEGRAM_LOOKUP_TIMEOUT = 3.0` and `TELEGRAM_ACTION_TIMEOUT = 20.0`. The
Kurigram client controls its own HTTP timeouts and connection pool, so those
values are not tuned here.

`prefixes.py` builds Kurigram filters for every configured prefix, handles
longest-prefix-first matching and optional `@botname` suffixes.
`ALL_PREFIXES_CMD_FILTER` is used in conversation escape filters.

## Logging and error reporting

`logger.py` installs a Loguru-backed shim bridged to the standard library, so
caplog and the Telegram error handler see records. Use a module logger rather
than `print()`. `log_execution` binds `update_id`, `user_id`, and `chat_id` to
each line until the handler returns.

`errors/classify.py` classifies exceptions and suppresses benign and transient
ones. `errors/report.py` owns dedupe, throttling, and delivery: it scrubs
credential-shaped text and exact configured secrets, fingerprints and
deduplicates incidents, and ships reports as rich payloads to the configured
error destination or the Owner DM. Shipping is capped at 20 reports per 60
seconds and the suppressed count is folded into a summary. The console
formatter applies the same credential-shape redaction to every line and
traceback, plus exact configured values once the reporter attaches. Sentry is
opt-in through `SENTRY_DSN` and uses the same redaction hook.

## Supervised tasks and update processing

`TaskTracker` owns the schedule, track, and release steps for fire-and-forget
tasks. The startup, member-cache, identity-refresh, admin-harvest, and
asyncio-report sets are drained during shutdown.

`KeyedUpdateProcessor` serializes updates per `(chat, user)` so a
ConversationHandler sees one update at a time without blocking the rest of the
federation. It takes the conversation lock before the global cap, so a burst on
one conversation does not hold every slot. Cancelled queued updates close their
coroutines.

## Workers

The enforcement worker claims queued runs, delivers each target through
`fan_out()` with a 20-second per-action timeout, and records an attempt row.
Each target has three attempts with a five-minute retry deadline. Claims are
sized by the breaker's admission headroom and delivered in bounded chunks, so a
circuit that opens mid-batch cannot leave later targets skipped without a call.
The immediate delivery path leaves a run queued while the circuit is open.

The notification worker claims due review-card edits, reserves a breaker slot
before each edit, and completes only the claim it observed, including the card
message id, so a re-queued card cannot be settled by an older worker. Both
workers pause on an open circuit and admit one probe in half-open state.

## Scheduler and pg_cron

APScheduler 3.11.3 runs an `AsyncIOScheduler` with a `SQLAlchemyJobStore` table
`apscheduler_jobs` in the configured schema. Schedules are reconciled on startup
by reading stored jobs in bulk and sweeping unknown ids with a second read, and
UTC is explicit.

| Job ID | Cadence | Purpose |
|---|---|---|
| `tcbot.expiry_daily` | 24 h | Expire decisions and queue revokes; removed when pg_cron owns this. |
| `tcbot.promotion_expiry_hourly` | 1 h | Mark stale promotion requests `expired`. |
| `tcbot.enforcement_worker` | 5 min | Drain the enforcement run queue once. Stable persisted ID; the callable is registered directly from `moderation_enforcement.py`. |
| `tcbot.notification_worker` | 5 min | Retry due review-card edits once. |
| `tcbot.erasure_every_10m` | 10 min | Drain up to 25 queued account erasures. |
| `tcbot.retention_daily` | 24 h | Apply schema retention policies. |
| `tcbot.stale_cleanup_daily` | 24 h | Delete stale memberships and drain erasures. |

pg_cron is opt-in through `PG_CRON_ENABLED` and only used when the extension
exists. Its job names match the `scheduled_jobs` registry keys. When pg_cron owns
the expiry work, the scheduled-job registry claim is the duplicate guard; the
APScheduler expiry job is removed on a successful hand-off. A partial failure
removes all owned pg_cron jobs so the two owners never run the same sweep.

## Cache mechanics

`TwoLevelCache[T]` owns L1, L2, and the per-key single-flight lock. `get_or_fetch`
captures the key generation and the cache-wide epoch before reading L2 or the
source, and publishes only when neither changed, so a read that overlapped an
invalidation cannot republish an old value. `peek()` and `peek_many()` are
display hints only.

`invalidate(key)` removes L1, advances the generation, and enqueues a Redis
delete. For revocation prefixes it first writes a short-lived tombstone that
other processes check before trusting an L2 hit. `clear_all()` sweeps the prefix
with `SCAN` and `UNLINK`, bumping the epoch on both sides.

Redis mutations are chained FIFO per `(prefix, event loop)` with a shielded
predecessor. The queue is bounded: droppable operations drop past 200 queued,
critical operations evict the oldest droppable operation past 1000, and an
absolute ceiling of 2000 drops even critical work with an error log. Revocation
prefixes and locale deletions take the non-droppable path. Operations rely on
the 2-second socket timeout rather than `asyncio.wait_for`, because cancelling a
Redis command leaves its reply unread on the pooled connection. With no Redis
client the cache behaves as a plain in-memory TTL cache.
