# Rate limiting and flood control

Purpose: describe the per-handler throttle tiers, the Redis-backed sliding
window with its in-process fallback, and how rate limits cooperate with the
Telegram circuit breaker. The concurrency contract is shared with
[Persistence](persistence.md) and [Cache](cache.md).

## Where throttling is applied

Throttling is applied only by the `ratelimiter(throttle)` decorator on command
and callback handlers. There is no globally registered flood handler in the
Kurigram runtime: ordinary chat messages never pass a rate-limit gate, and a
handler without the decorator has no quota. One bucket is kept per `(user,
wrapped function)`, so two handlers on the same tier stay independent.

```mermaid
flowchart TD
    U([Decorated update]) --> D[ratelimiter wrapper]
    D --> UID{Update has a user id?}
    UID -->|no| PASS[Run the handler]
    UID -->|yes| OWN{_is_exempt: current Owner?}
    OWN -->|yes| PASS
    OWN -->|no| CHK[_limiter.check: Redis window or local fallback]
    CHK -->|allowed| PASS
    CHK -->|wait| KIND{update type}
    KIND -->|callback_query| CBSTOP[answer with alert, stop]
    KIND -->|message| STOP[Reply with wait seconds, stop]
    KIND -->|no surface| BLOCK[Block without a reply]
```

## Shared throttle tiers

`@dataclass(frozen=True) class Throttle(limit, period)` gives `limit` calls per
`period` seconds, per user, per handler. The Redis key includes the wrapped
function name, so two handlers on the same tier keep independent buckets.
`decorators/__init__.py` re-exports all tiers.

| Constant | Limit | Period | Typical use |
|---|---|---|---|
| `THROTTLE_READ` | 8 | 30 s | Read-only commands such as help, stats, group and warn listings |
| `THROTTLE_CALLBACK` | 15 | 30 s | Buttons that only open a view |
| `THROTTLE_CALLBACK_DEEP` | 20 | 30 s | Buttons that open a paginated drill-down |
| `THROTTLE_STAFF` | 10 | 30 s | Staff state changes and approval callbacks |
| `THROTTLE_MODERATION` | 5 | 60 s | Destructive moderation: ban, kick, mute, warn, promote, demote |
| `THROTTLE_FEDERATION` | 3 | 60 s | Commands that fan out across every group |
| `THROTTLE_BULK` | 3 | 300 s | Long cleanup and leave-all operations, transfer, promotion requests |
| `THROTTLE_CRITICAL` | 1 | 300 s | A single destructive operation per window |

`admins.py` uses `THROTTLE_MODERATION` on promote and demote commands,
`THROTTLE_BULK` on transfer and promotion-request submission, and
`THROTTLE_STAFF` on the role-picker, confirmation, and decision callbacks. See
[Roles](roles.md) for those flows.

## The `ratelimiter` decorator

`ratelimiter(throttle)` wraps a handler and constructs an `_AsyncRateLimiter`
with `max_calls=throttle.limit`, `window=throttle.period`, and
`prefix=f"h:{func.__module__}.{func.__name__}"`. Each call:

- resolves the invoking user id; without one it calls the handler directly;
- calls `_is_exempt(uid)` and skips the quota entirely for the current Owner;
- calls `_limiter.check(uid)`, and if it returns a wait time, answers a callback
  with an alert or replies to the message with the wait text, then returns
  without calling the handler;
- otherwise awaits the handler.

A throttle reply uses `replies.rate_limit_text(wait, locale, plain=True)`.
Cancellation propagates through `_is_exempt()` and the limiter check.

## Owner bypass

`_is_exempt(uid)` resolves the current Owner from the cached owner id (300 s L1
TTL, invalidated on transfer) and skips every per-handler quota for that one
user. It fails closed: a lookup error or a missing owner row means not exempt,
so an outage never disables throttling. Cancellation propagates. A synchronous
compare against the configured initial owner is deliberately avoided, because
after a transfer that account is no longer the Owner and would stay exempt
forever.

## Redis sorted-set window and in-process fallback

```mermaid
sequenceDiagram
    participant Handler
    participant Async as _AsyncRateLimiter.check
    participant Redis as Redis sorted set
    participant Local as _RateLimiter in-process
    Handler->>Async: check(uid)
    alt Client missing or not usable on this loop
        Async->>Local: check(uid)
    else Client available
        Async->>Redis: EVALSHA (fallback EVAL) _RL_LUA key=rl:prefix:uid
        Note over Redis: ZREMRANGEBYSCORE old, ZCARD, ZADD now/member, PEXPIRE
        alt count < limit
            Redis-->>Async: 0 (allowed)
        else at limit
            Redis-->>Async: ceil(wait * 10)
        end
    end
    alt Redis command raised, not CancelledError
        Async->>Local: fall back and check(uid)
    end
    Async-->>Handler: 0.0 or seconds to wait
```

`_RL_LUA` is an atomic sorted-set sliding window executed via `register_script`
(`EVALSHA` with `EVAL` fallback) using a single `time.time_ns()` syscall. Its
arguments are the key, current time, window, limit, and a unique member
(`time.time_ns()` string). It returns `0` when allowed, or `ceil(wait * 10)` when
denied; the caller converts that back to seconds rounded to one decimal.
`_AsyncRateLimiter` uses `key = f"rl:{prefix}:{uid}"` and `PEXPIRE` of
`ceil(window * 1000) + 1000` ms.

When Redis is unavailable (no client, a client bound to another event loop, or
a command error), the call falls through to the synchronous `_RateLimiter`,
which keeps per-user `deque` timestamps, resets expired buckets in O(1) in place,
and prunes entries outside the window. Memory is bounded by window-throttled
cleanup once the bucket count exceeds `10_000`. Rate limiting is never silently
disabled.

A deliberate constraint: the Redis call is bounded by the client's socket
timeout, not by `asyncio.wait_for()`. Cancelling a waiter would abandon an
in-flight Redis command with its reply unread on the pooled connection,
desyncing the next cache operation that reuses it. The same rule governs the
two-level cache in `database/cache/twolevel.py`.

## Flood wait and retry storm avoidance

- A throttled command answers once with the computed wait and stops, so the user
  gets no duplicate work.
- A throttled callback answers with `show_alert=True` so the client spinner
  clears immediately.
- The wait is derived from the oldest timestamp in the window, so a user sees
  a real countdown rather than a generic refusal.
- The decorator bypasses quotas for the current Owner and fails closed when
  the owner lookup is unavailable.
- Telegram `RetryAfter` from the rate limiter is waited out with a bounded
  retry budget: the request is retried after the requested delay while the
  other requests are paused, which is the behaviour Telegram asks for.

## Telegram circuit breaker and bounded fan-out

Rate limiting is per user; the circuit breaker protects the Telegram transport
as a whole. Federation-wide enforcement uses `utils.dispatch.fan_out()`, which
bounds concurrency and integrates the breaker.

| Item | Value |
|---|---|
| `fan_out` default `_MAX_CONCURRENT` | 10 concurrent Telegram calls (Telegram allows roughly 30 messages per second globally) |
| `gather_bounded` | Same bounded contract for pure database bursts, with no circuit interaction |
| `telegram` breaker | `failure_threshold = 5`, `recovery_timeout = 60.0` s |
| `postgres` breaker | `failure_threshold = 5`, `recovery_timeout = 60.0` s |
| Breaker states | `CLOSED`, `OPEN`, `HALF_OPEN` (one probe in flight) |

```mermaid
flowchart TD
    F["fan_out(coros, max_concurrent=10)"] --> SEM{Semaphore slot and circuit state}
    SEM -->|OPEN| SKIP[Return CircuitOpenError, close unused coroutine]
    SEM -->|CLOSED or HALF_OPEN| CALL[Await Telegram call]
    CALL -->|success| REC[record_success, return result]
    CALL -->|Timedout / Timeout / TimeoutError / OSError| FAIL[record_failure, may trip to OPEN]
    CALL -->|BadRequest refusal| BENIGN["release_probe reached_service=True, no failure counted"]
    CALL -->|CancelledError| CANCEL[Release probe and re-raise]
    REC --> R[count_transient_errors excludes benign refusals]
    FAIL --> R
    BENIGN --> R
    SKIP --> R
```

`fan_out` admits slots lazily through a semaphore. While the circuit is `OPEN`,
a slot is skipped immediately with `CircuitOpenError` instead of firing a call
that would time out, and the unused coroutine is closed. Successes call
`record_success()`. Kurigram's `Timedout` and `Timeout`, builtin `TimeoutError`,
and `OSError` call `record_failure()`. A `BadRequest` is an API refusal,
not congestion, so it
calls `release_probe(reached_service=True)` and does not count against the
breaker. `CancelledError` always propagates so shutdown is never coerced into
per-group failure data. The breaker's `admission_headroom` property reports how
many calls a closed circuit can still admit; the enforcement worker sizes its
claims with it.

`count_transient_errors()`, `transient_groups()`, and `summarize_fanout()` turn
the result list into operator-facing counts. Benign refusals such as
`USER_NOT_PARTICIPANT` or `CHAT_NOT_FOUND` count as applied, because there was
nothing to enforce in that group; only transient failures are reported as
failed groups. This combination of per-user throttles, bounded concurrency, and
circuit gating prevents one flood of commands or one stalled Telegram endpoint
from turning into a retry storm.

Related reading: [Permissions](permissions.md), [Roles](roles.md),
[Extraction and user data](extraction-user-data.md).
