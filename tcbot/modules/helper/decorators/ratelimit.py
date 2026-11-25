# © Copyright 2024 - 2026 Transsion Core
# © Copyright 2024 - 2026 Dizzy
# © Copyright 2026 Ave Labs

"""Per-user sliding-window rate limiters for decorated handlers."""

from __future__ import annotations

import asyncio
import functools
import time
from collections import deque
from dataclasses import dataclass
from typing import TYPE_CHECKING, Any

from tcbot.modules.helper.context import Ctx
from tcbot.utils.logger import get_logger

if TYPE_CHECKING:
    from collections.abc import Callable, Coroutine

from tcbot import database as db
from tcbot.modules.helper.locale import locale_for_update
from tcbot.modules.helper.messages import replies, reply_rich
from tcbot.utils.time_and_date import monotonic

log = get_logger(__name__)


# ─────────────────────── Shared throttle presets ─────────────────── #
# * Single owner for the per-handler throttle tiers. Every command module
# * used to declare its own pair of constants, which produced four
# * different spellings for the same values and let a tier drift apart
# * between two modules that meant the same thing.
# *
# * The tiers are named by what they protect, not by their numbers, so a
# * handler reads as "a destructive command" or "a read-only listing"
# * rather than as "limit 8, period 30".


@dataclass(frozen=True)
class Throttle:
    """One named per-handler throttle tier.

    ``limit`` calls are allowed per ``period`` seconds, per user, per
    handler. The Redis key already carries the handler name, so two
    handlers on the same tier keep independent buckets.
    """

    limit: int
    period: float


# * Read-only commands: /help, /stats, /tcgroups, /warns listing.
THROTTLE_READ = Throttle(limit=8, period=30.0)
# * Button presses that only open a view.
THROTTLE_CALLBACK = Throttle(limit=15, period=30.0)
# * Button presses that open a paginated drill-down with more rows.
THROTTLE_CALLBACK_DEEP = Throttle(limit=20, period=30.0)
# * Staff commands that change federation state (promote, demote).
THROTTLE_STAFF = Throttle(limit=10, period=30.0)
# * Destructive moderation commands (ban, kick, mute, warn).
THROTTLE_MODERATION = Throttle(limit=5, period=60.0)
# * Federation-wide commands that fan out over every group.
THROTTLE_FEDERATION = Throttle(limit=3, period=60.0)
# * Bulk commands that run for minutes (cleanup, leave-all).
THROTTLE_BULK = Throttle(limit=3, period=300.0)
# * A single destructive operation per window (leave-all).
THROTTLE_CRITICAL = Throttle(limit=1, period=300.0)


# ────────────── Per-user sliding-window rate limiter ────────────── #


class _RateLimiter:
    """Synchronous in-process sliding-window per-user rate limiter (fallback)."""

    __slots__ = ("_buckets", "max_calls", "window")

    def __init__(self, max_calls: int, window: float) -> None:
        self.max_calls = max_calls
        self.window = window
        self._buckets: dict[int, deque[float]] = {}

    def check(self, uid: int) -> float:
        """Return 0.0 if allowed (call recorded), or seconds to wait if denied."""
        now = monotonic()
        dq = self._buckets.get(uid)

        if dq is None:
            self._buckets[uid] = deque([now])
            # * Periodic cleanup to bound memory; mirrors Redis PEXPIRE behavior.
            # * Only runs when bucket count grows past threshold to avoid O(n) on every call.
            if len(self._buckets) > 10_000:
                cutoff = now - self.window * 2
                self._buckets = {
                    k: v for k, v in self._buckets.items() if v and v[0] > cutoff
                }
            return 0.0

        # * drop timestamps outside the current window
        while dq and now - dq[0] >= self.window:
            dq.popleft()

        if not dq:
            # * bucket fully cleared - recycle slot and allow
            self._buckets[uid] = deque([now])
            return 0.0

        if len(dq) >= self.max_calls:
            # * blocked - tell caller how long until the oldest slot expires
            return round(self.window - (now - dq[0]), 1)

        dq.append(now)
        return 0.0


# * Lua script for atomic sorted-set sliding-window rate limit.
# * KEYS[1] = rate-limit key; ARGV[1] = now (float), ARGV[2] = window (float),
# * ARGV[3] = max_calls (int), ARGV[4] = unique member (nanosecond timestamp).
# * Returns 0 if allowed, or ceil(wait_tenths) (int) if denied (wait = result/10 s).
_RL_LUA = """
local key   = KEYS[1]
local now   = tonumber(ARGV[1])
local win   = tonumber(ARGV[2])
local limit = tonumber(ARGV[3])
local member = ARGV[4]
redis.call('ZREMRANGEBYSCORE', key, '-inf', now - win)
local count = redis.call('ZCARD', key)
if count < limit then
    redis.call('ZADD', key, now, member)
    redis.call('PEXPIRE', key, math.ceil(win * 1000) + 1000)
    return 0
end
local oldest = redis.call('ZRANGE', key, 0, 0, 'WITHSCORES')
if oldest and oldest[2] then
    local wait = win - (now - tonumber(oldest[2]))
    if wait < 0.1 then wait = 0.1 end
    return math.ceil(wait * 10)
end
return math.ceil(win * 10)
"""


class _AsyncRateLimiter:
    """Sliding-window rate limiter: Redis sorted-set backend with in-process fallback.

    When Redis is available the sliding window state persists across bot restarts.
    When Redis is unavailable (or errors), the call falls through to the in-process
    ``_RateLimiter``, so rate limiting is never silently disabled.
    """

    __slots__ = ("_local", "_prefix", "max_calls", "window")

    def __init__(self, max_calls: int, window: float, prefix: str) -> None:
        self.max_calls = max_calls
        self.window = window
        self._prefix = prefix
        self._local = _RateLimiter(max_calls=max_calls, window=window)

    async def check(self, uid: int) -> float:
        """Return 0.0 if allowed, or seconds to wait if denied."""
        r = db.redis_client.client()
        if r is None or not db.redis_client.client_is_usable():
            return self._local.check(uid)

        key = f"rl:{self._prefix}:{uid}"
        now = time.time()
        # * nanosecond timestamp string as unique member - avoids ZADD collision
        member = str(time.time_ns())

        try:
            # * The client's socket timeout bounds the call. Wrapping it in
            # * asyncio.wait_for would cancel an in-flight Redis command and
            # * leave its reply unread on the pooled connection, desyncing the
            # * next cache operation that reuses it.
            result = await r.eval(
                _RL_LUA,
                1,
                key,
                str(now),
                str(self.window),
                str(self.max_calls),
                member,
            )
            if result == 0:
                return 0.0
            # * result = ceil(wait * 10) - convert back to seconds
            return round(int(result) / 10.0, 1)
        except asyncio.CancelledError:
            raise
        except Exception as exc:
            log.debug("Redis rate limiter error, using local fallback: %s", exc)
            return self._local.check(uid)


async def _is_exempt(uid: int) -> bool:
    """Return True when ``uid`` is the current Owner (exempt from rate limits).

    Served from the cached owner ID (300 s TTL, invalidated on transfer),
    so hot paths pay zero database round trips on cache hits. A sync compare
    against the configured initial owner is deliberately NOT used as a fast
    path: after an ownership transfer the initial owner is no longer the Owner,
    and a stale compare would exempt them from throttling forever. The
    cached read is the single source of truth. Fail-closed: any lookup
    failure (including no owner row yet) means not exempt, so an outage
    never silently disables throttling. Cancellation propagates.
    """
    try:
        owner_id = await db.users_roles.get_owner_id()
    except asyncio.CancelledError:
        raise
    except Exception as exc:
        log.debug("Rate-limit exemption lookup failed for %d: %s", uid, exc)
        return False
    return owner_id is not None and owner_id == uid


# ──────────────────── Per-handler rate limiter factory ──────────────────── #


def ratelimiter[R](
    throttle: Throttle,
) -> Callable[
    [Callable[..., Coroutine[Any, Any, R]]],
    Callable[..., Coroutine[Any, Any, R | None]],
]:
    """Per-handler sliding-window rate limiter factory.

    Backed by Redis when available; falls through to in-process sliding window
    otherwise.  The Redis key prefix includes the wrapped function name so each
    handler gets an independent quota bucket per user.

    Takes one of the shared :class:`Throttle` tiers so every handler draws
    its budget from the same table.
    """

    def decorator(
        func: Callable[..., Coroutine[Any, Any, R]],
    ) -> Callable[..., Coroutine[Any, Any, R | None]]:
        """Wrap ``func`` with a sliding-window per-user rate check."""
        _limiter = _AsyncRateLimiter(
            max_calls=throttle.limit,
            window=throttle.period,
            prefix=f"h:{func.__module__}.{func.__name__}",
        )

        @functools.wraps(func)
        async def _wrapper(ctx: Ctx) -> R | None:
            """Block the call and notify the user if the rate limit is exceeded."""
            uid = ctx.effective_user.id if ctx.effective_user else None
            if uid:
                # * The Owner bypasses per-handler quotas (incident response
                # * must never stall on a throttle); everyone else shares the
                # * same bucket. Fail-closed via _is_exempt, cancellation
                # * propagates.
                if await _is_exempt(uid):
                    return await func(ctx)
                wait = await _limiter.check(uid)
                if wait:
                    if ctx.callback_query:
                        try:
                            await ctx.callback_query.answer(
                                replies.rate_limit_text(
                                    wait, await locale_for_update(ctx), plain=True
                                ),
                                show_alert=True,
                            )
                        except Exception as exc:
                            log.debug("Callback rate-limit answer failed: %s", exc)
                        return None
                    if ctx.effective_message:
                        await reply_rich(
                            ctx.effective_message,
                            replies.rate_limit_text(
                                wait, await locale_for_update(ctx), plain=True
                            ),
                            log_label="Message rate-limit",
                            parse_mode=None,
                        )
                        return None
                    # * No surface exists to tell the user why, so block the
                    # * call instead of running it past its quota.
                    return None
            return await func(ctx)

        return _wrapper

    return decorator
