# © Copyright 2024 - 2026 Transsion Core
# © Copyright 2024 - 2026 Dizzy
# © Copyright 2026 Aveum Apps

"""Auth decorators, execution tracer, and per-user rate limiter for all command handlers."""

from __future__ import annotations

import functools
import logging
import time
from collections import deque
from collections.abc import Callable

from telegram import Update
from telegram.ext import ApplicationHandlerStop, ContextTypes

from tcbot import cfg
from tcbot import database as db
from tcbot.database.roles_db import get_effective_role, role_rank

log = logging.getLogger(__name__)


# ── Per-user sliding-window rate limiter ───────────────────────────────────


class _RateLimiter:
    """
    Sliding-window per-user rate limiter.

    ``check(uid)`` records the call and returns ``0.0`` when allowed.
    Returns the remaining seconds in the window (> 0) when the limit is hit
    *without* recording the blocked call.

    Memory is proportional to currently-active users - stale buckets are
    pruned eagerly so the dict never accumulates all-time unique users.
    """

    __slots__ = ("max_calls", "window", "_buckets")

    def __init__(self, max_calls: int, window: float) -> None:
        self.max_calls = max_calls
        self.window = window
        self._buckets: dict[int, deque[float]] = {}

    def check(self, uid: int) -> float:
        """Return ``0.0`` if allowed (call recorded), or seconds to wait if denied."""
        now = time.monotonic()
        dq = self._buckets.get(uid)

        if dq is None:
            self._buckets[uid] = deque([now])
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


# * Commands : 8 calls per 30 s - comfortable for regular moderation
_cmd_limiter = _RateLimiter(max_calls=8, window=30.0)

# * Buttons  : 20 presses per 10 s - allows snappy navigation
_cbq_limiter = _RateLimiter(max_calls=20, window=10.0)


async def global_rate_limit_handler(
    update: Update, ctx: ContextTypes.DEFAULT_TYPE
) -> None:
    """Universal per-user rate limiter - registered at group -1.

    Runs before every handler group so the check is always first.

    * **CallbackQuery** - 20 per 10 s.
      Denied presses get a brief *toast* (``show_alert=True``) so the UI
      never freezes with a blocking popup.

    * **Command text** - 8 per 30 s.
      Denied commands get a reply showing exactly how many seconds to wait,
      then ``ApplicationHandlerStop`` drops the update from all other groups.

    * **Everything else** - always passes (member cache, conversation text, …).
    """
    uid = update.effective_user.id if update.effective_user else None
    if not uid:
        return

    # * ── button press ─────────────────────────────────────────────────────────
    if update.callback_query:
        wait = _cbq_limiter.check(uid)
        if wait:
            try:
                await update.callback_query.answer(
                    f"⏳ Upss, slow down.. try again in {wait:.0f} seconds.",
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

    if not any(text.startswith(p) for p in cfg.prefixes):
        return  # * plain chat message - never rate-limit

    wait = _cmd_limiter.check(uid)
    if wait:
        if msg:
            try:
                await msg.reply_text(f"⏳ Slow down! try again in {wait:.0f} seconds.")
            except Exception:
                pass
        raise ApplicationHandlerStop


# ── Per-handler rate limiter factory ───────────────────────────────────────


def ratelimiter(limit: int = 5, period: float = 60.0) -> Callable:
    """Per-handler sliding-window rate limiter factory.

    Returns a decorator that applies a per-user rate limit to a specific
    handler. Complements the global rate limiter (group -1) with fine-grained
    per-command control.

    The limiter is non-blocking: allowed requests pass through with zero
    added latency. Denied requests receive an immediate reply and return
    without executing the handler body.

    Args:
        limit:  Maximum number of calls allowed within ``period`` seconds.
        period: Sliding window duration in seconds.

    Usage::

        @decorators.ratelimiter(limit=3, period=60)
        @decorators.staff_only
        @decorators.log_execution
        async def cmd_broadcast(update, ctx):
            ...
    """
    _limiter = _RateLimiter(max_calls=limit, window=period)

    def decorator(func: Callable) -> Callable:
        @functools.wraps(func)
        async def wrapper(update: Update, ctx: ContextTypes.DEFAULT_TYPE) -> None:
            uid = update.effective_user.id if update.effective_user else None
            if uid:
                wait = _limiter.check(uid)
                if wait:
                    if update.callback_query:
                        try:
                            await update.callback_query.answer(
                                f"⏳ Slow down - try again in {wait:.0f}s.",
                                show_alert=True,
                            )
                        except Exception:
                            pass
                        return
                    if update.effective_message:
                        try:
                            await update.effective_message.reply_text(
                                f"⏳ Slow down! Try again in {wait:.0f} seconds."
                            )
                        except Exception:
                            pass
                        return
            return await func(update, ctx)

        return wrapper

    return decorator


# ── Execution tracer ───────────────────────────────────────────────────────


def log_execution(func: Callable) -> Callable:
    """Wrap a handler to emit entry / exit / exception traces at DEBUG level.

    Logs the handler name and effective user ID on entry.
    On success logs elapsed milliseconds.  On exception logs at ERROR level
    (with full traceback) and re-raises so PTB error handling stays intact.

    Opt-in: apply to any command or callback handler you want to trace.
    Has zero overhead when the root logger is above DEBUG.
    """

    @functools.wraps(func)
    async def wrapper(update: Update, ctx: ContextTypes.DEFAULT_TYPE) -> None:
        uid = update.effective_user.id if update.effective_user else "?"
        name = func.__name__
        t0 = time.monotonic()
        log.debug("[%s] uid=%s enter", name, uid)
        try:
            result = await func(update, ctx)
        except Exception:
            elapsed = (time.monotonic() - t0) * 1_000
            log.exception("[%s] uid=%s raised after %.1fms", name, uid, elapsed)
            raise
        log.debug("[%s] uid=%s ok (%.1fms)", name, uid, (time.monotonic() - t0) * 1_000)
        return result  # type: ignore[return-value]

    return wrapper


# ── Auth decorators ────────────────────────────────────────────────────────


def owner_only(func: Callable) -> Callable:
    """Restrict handler to the Founder only."""

    @functools.wraps(func)
    async def wrapper(update: Update, ctx: ContextTypes.DEFAULT_TYPE) -> None:
        uid = update.effective_user.id if update.effective_user else None
        if uid and await db.admins_db.is_owner(uid):
            return await func(update, ctx)
        if update.effective_message:
            await update.effective_message.reply_text(
                "This command is reserved for the Founder - you're not authorized. 🔒"
            )

    return wrapper


def staff_only(func: Callable) -> Callable:
    """Restrict handler to Founder and Admin."""

    @functools.wraps(func)
    async def wrapper(update: Update, ctx: ContextTypes.DEFAULT_TYPE) -> None:
        uid = update.effective_user.id if update.effective_user else None
        if uid and await db.admins_db.is_staff(uid):
            return await func(update, ctx)
        if update.effective_message:
            await update.effective_message.reply_text(
                "Staff and Founder only for this one - you don't have the rank. 🚫"
            )

    return wrapper


def mod_only(func: Callable) -> Callable:
    """Restrict handler to Founder, Admin, Developer (ban/unban level)."""

    @functools.wraps(func)
    async def wrapper(update: Update, ctx: ContextTypes.DEFAULT_TYPE) -> None:
        uid = update.effective_user.id if update.effective_user else None
        if uid and role_rank(await get_effective_role(uid)) >= role_rank("developer"):
            return await func(update, ctx)
        if update.effective_message:
            await update.effective_message.reply_text(
                "You need Developer rank or above for this - not your call. 🚫"
            )

    return wrapper


def basic_mod_only(func: Callable) -> Callable:
    """Restrict handler to Founder, Admin, Developer, Tester (kick/mute/warn level)."""

    @functools.wraps(func)
    async def wrapper(update: Update, ctx: ContextTypes.DEFAULT_TYPE) -> None:
        uid = update.effective_user.id if update.effective_user else None
        if uid and role_rank(await get_effective_role(uid)) >= role_rank("tester"):
            return await func(update, ctx)
        if update.effective_message:
            await update.effective_message.reply_text(
                "You need at least a Tester role for this - not your call. 🚫"
            )

    return wrapper
