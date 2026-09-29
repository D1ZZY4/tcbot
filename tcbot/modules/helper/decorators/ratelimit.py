# © Copyright 2024 - 2026 Transsion Core
# © Copyright 2024 - 2026 Dizzy
# © Copyright 2026 Ave Labs

"""Per-user sliding-window rate limiters and the global flood handler."""

from __future__ import annotations

import asyncio
import functools
import time
from collections import deque
from typing import TYPE_CHECKING, Any

from telegram.ext import ApplicationHandlerStop, ContextTypes

from tcbot.utils.logger import get_logger

if TYPE_CHECKING:
    from collections.abc import Callable, Coroutine

from tcbot import cfg
from tcbot import database as db
from tcbot.modules.helper import replies
from tcbot.modules.helper.locale import locale_for_update
from tcbot.modules.helper.parse_editmsg import safe_reply
from tcbot.utils.time_and_date import monotonic

if TYPE_CHECKING:
    from telegram import Update

log = get_logger(__name__)


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
        if r is None:
            return self._local.check(uid)

        key = f"rl:{self._prefix}:{uid}"
        now = time.time()
        # * nanosecond timestamp string as unique member - avoids ZADD collision
        member = str(time.time_ns())

        try:
            result = await asyncio.wait_for(
                r.eval(
                    _RL_LUA,
                    1,
                    key,
                    str(now),
                    str(self.window),
                    str(self.max_calls),
                    member,
                ),
                timeout=_RL_REDIS_TIMEOUT_S,
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


# * Upper bound for one Redis rate-limit round trip. The socket default is
# * far higher; without this cap a stalled Redis would hold every command
# * and callback for seconds before the local fallback runs. A timeout
# * falls through to the in-process bucket, so limiting is never disabled.
_RL_REDIS_TIMEOUT_S: float = 1.5

# * Commands : 8 calls per 30 s - comfortable for regular moderation
_cmd_limiter = _AsyncRateLimiter(max_calls=8, window=30.0, prefix="cmd")

# * Staff commands: 16 calls per 30 s - incident response mixes several
# * different commands (check, warn, kick, ...) in one burst, so the global
# * flood ceiling sits roomier for authenticated staff. Per-handler quotas
# * below still pace each destructive command, so this never loosens those.
_cmd_staff_limiter = _AsyncRateLimiter(max_calls=16, window=30.0, prefix="cmd_staff")

# * Buttons  : 20 presses per 10 s - allows snappy navigation
_cbq_limiter = _AsyncRateLimiter(max_calls=20, window=10.0, prefix="cbq")


async def _is_exempt(uid: int) -> bool:
    """Return True when ``uid`` is the current Founder (exempt from rate limits).

    Served from the cached owner ID (300 s TTL, invalidated on transfer),
    so hot paths pay zero MongoDB round trips on cache hits. A sync compare
    against the configured initial owner is deliberately NOT used as a fast
    path: after an ownership transfer the initial owner is no longer Founder,
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


async def _throttle_tier(uid: int) -> str:
    """Return the global command-bucket tier for ``uid`` in one cached read.

    ``"exempt"`` for the Founder (no global throttle), ``"staff"`` for
    Tester rank and above (roomier flood ceiling), ``"regular"`` for
    everyone else. ``get_effective_role`` resolves the owner to
    ``"founder"`` itself, so this single read covers all three tiers with
    zero MongoDB round trips on cache hits. Fail-closed: any lookup
    failure lands on ``"regular"`` (the strictest bucket), so an outage
    never loosens throttling. Cancellation propagates.
    """
    try:
        role = await db.users_roles.get_effective_role(uid)
    except asyncio.CancelledError:
        raise
    except Exception as exc:
        log.debug("Throttle-tier lookup failed for %d: %s", uid, exc)
        return "regular"
    if role == "founder":
        return "exempt"
    # * role_rank is a pure mapping lookup (unknown roles rank 0), so no
    # * failure path here; DB failures already returned "regular" above.
    if db.users_roles.role_rank(role) >= db.users_roles.role_rank("tester"):
        return "staff"
    return "regular"


async def global_rate_limit_handler(
    update: Update, ctx: ContextTypes.DEFAULT_TYPE
) -> None:
    """Universal per-user rate limiter - registered at group -1."""
    uid = update.effective_user.id if update.effective_user else None
    if not uid:
        return

    # * ── button press ─────────────────────────────────────────────────────────
    if update.callback_query:
        if await _is_exempt(uid):
            return
        wait = await _cbq_limiter.check(uid)
        if wait:
            try:
                await update.callback_query.answer(
                    replies.rate_limit_text(
                        wait, await locale_for_update(update), plain=True
                    ),
                    show_alert=True,
                )
            except Exception as exc:
                log.debug("CBQ rate-limit answer failed: %s", exc)
            raise ApplicationHandlerStop
        return

    # * ── command message ──────────────────────────────────────────────────────
    msg = update.effective_message
    text = (msg.text or "") if msg else ""
    if not text:
        return

    if not any(text.startswith(p) for p in cfg.prefixes if p):
        return  # * plain chat message - never rate-limit

    # * One cached read decides the flood ceiling: Founder skips it, staff
    # * get the roomier bucket, everyone else the strict one. Per-handler
    # * quotas below still pace each command individually.
    tier = await _throttle_tier(uid)
    if tier == "exempt":
        return
    limiter = _cmd_staff_limiter if tier == "staff" else _cmd_limiter
    wait = await limiter.check(uid)
    if wait:
        if msg:
            await safe_reply(
                msg,
                replies.rate_limit_text(
                    wait, await locale_for_update(update), plain=True
                ),
                log_label="Command rate-limit",
                parse_mode=None,
            )
        raise ApplicationHandlerStop


# ──────────────────── Per-handler rate limiter factory ──────────────────── #


def ratelimiter[R](
    limit: int = 5, period: float = 60.0
) -> Callable[
    [Callable[..., Coroutine[Any, Any, R]]],
    Callable[..., Coroutine[Any, Any, R | None]],
]:
    """Per-handler sliding-window rate limiter factory.

    Backed by Redis when available; falls through to in-process sliding window
    otherwise.  The Redis key prefix includes the wrapped function name so each
    handler gets an independent quota bucket per user.
    """

    def decorator(
        func: Callable[..., Coroutine[Any, Any, R]],
    ) -> Callable[..., Coroutine[Any, Any, R | None]]:
        """Wrap ``func`` with a sliding-window per-user rate check."""
        _limiter = _AsyncRateLimiter(
            max_calls=limit,
            window=period,
            prefix=f"h:{func.__module__}.{func.__name__}",
        )

        @functools.wraps(func)
        async def _wrapper(update: Update, ctx: ContextTypes.DEFAULT_TYPE) -> R | None:
            """Block the call and notify the user if the rate limit is exceeded."""
            uid = update.effective_user.id if update.effective_user else None
            if uid:
                # * The Founder bypasses per-handler quotas (incident response
                # * must never stall on a throttle); everyone else shares the
                # * same bucket. Fail-closed via _is_exempt, cancellation
                # * propagates.
                if await _is_exempt(uid):
                    return await func(update, ctx)
                wait = await _limiter.check(uid)
                if wait:
                    if update.callback_query:
                        try:
                            await update.callback_query.answer(
                                replies.rate_limit_text(
                                    wait, await locale_for_update(update), plain=True
                                ),
                                show_alert=True,
                            )
                        except Exception as exc:
                            log.debug("Callback rate-limit answer failed: %s", exc)
                        return None
                    if update.effective_message:
                        await safe_reply(
                            update.effective_message,
                            replies.rate_limit_text(
                                wait, await locale_for_update(update), plain=True
                            ),
                            log_label="Message rate-limit",
                            parse_mode=None,
                        )
                        return None
            return await func(update, ctx)

        return _wrapper

    return decorator
