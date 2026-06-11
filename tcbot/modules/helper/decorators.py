# © Copyright 2024 - 2026 Transsion Core
# © Copyright 2024 - 2026 Dizzy
# © Copyright 2026 Ave Studio

"""Auth decorators, execution tracer, per-user rate limiter, and shared permission helpers."""

from __future__ import annotations

import asyncio
import functools
import logging
import time
from collections import deque
from typing import TYPE_CHECKING, TypeVar

from telegram.ext import ApplicationHandlerStop, ContextTypes

from tcbot import cfg
from tcbot import database as db

if TYPE_CHECKING:
    from collections.abc import Awaitable, Callable

    from telegram import Message, Update

log = logging.getLogger(__name__)
R = TypeVar("R")


# ────────────── Per-user sliding-window rate limiter ────────────── #


class _RateLimiter:
    """Sliding-window per-user rate limiter."""

    __slots__ = ("_buckets", "max_calls", "window")

    def __init__(self, max_calls: int, window: float) -> None:
        self.max_calls = max_calls
        self.window = window
        self._buckets: dict[int, deque[float]] = {}

    def check(self, uid: int) -> float:
        """Return 0.0 if allowed (call recorded), or seconds to wait if denied."""
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
    """Universal per-user rate limiter - registered at group -1."""
    uid = update.effective_user.id if update.effective_user else None
    if not uid:
        return

    # * ── button press ─────────────────────────────────────────────────────────
    if update.callback_query:
        wait = _cbq_limiter.check(uid)
        if wait:
            try:
                await update.callback_query.answer(
                    f"Slow down - try again in {wait:.0f} seconds.",
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
                await msg.reply_text(f"Slow down - try again in {wait:.0f} seconds.")
            except Exception as exc:
                log.debug("Command rate-limit reply failed: %s", exc)
        raise ApplicationHandlerStop


# ──────────────── Per-handler rate limiter factory ──────────────── #


def ratelimiter(limit: int = 5, period: float = 60.0) -> Callable:
    """Per-handler sliding-window rate limiter factory."""
    _limiter = _RateLimiter(max_calls=limit, window=period)

    def decorator(
        func: Callable[[Update, ContextTypes.DEFAULT_TYPE], Awaitable[R]],
    ) -> Callable[[Update, ContextTypes.DEFAULT_TYPE], Awaitable[R | None]]:
        """Wrap ``func`` with a sliding-window per-user rate check."""

        @functools.wraps(func)
        async def _wrapper(update: Update, ctx: ContextTypes.DEFAULT_TYPE) -> R | None:
            """Block the call and notify the user if the rate limit is exceeded."""
            uid = update.effective_user.id if update.effective_user else None
            if uid:
                wait = _limiter.check(uid)
                if wait:
                    if update.callback_query:
                        try:
                            await update.callback_query.answer(
                                f"Slow down - try again in {wait:.0f}s.",
                                show_alert=True,
                            )
                        except Exception as exc:
                            log.debug("Callback rate-limit answer failed: %s", exc)
                        return None
                    if update.effective_message:
                        try:
                            await update.effective_message.reply_text(
                                f"Slow down - try again in {wait:.0f} seconds."
                            )
                        except Exception as exc:
                            log.debug("Message rate-limit reply failed: %s", exc)
                        return None
            return await func(update, ctx)

        return _wrapper

    return decorator


# ──────────────────────── Execution tracer ──────────────────────── #


def log_execution(
    func: Callable[[Update, ContextTypes.DEFAULT_TYPE], Awaitable[R]],
) -> Callable[[Update, ContextTypes.DEFAULT_TYPE], Awaitable[R]]:
    """Wrap a handler to emit entry / exit / exception traces at DEBUG level."""

    @functools.wraps(func)
    async def _wrapper(update: Update, ctx: ContextTypes.DEFAULT_TYPE) -> R:
        """Emit entry, exit, and exception traces at DEBUG level around ``func``."""
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
        return result

    return _wrapper


# ───────────────────────── Auth decorators ──────────────────────── #

# * User-facing refusal messages for each auth tier. Centralised here so voice
# * changes and translations only need to happen in one place.
_ERR_OWNER_ONLY = "This command is reserved for the Founder - you're not authorized."
_ERR_STAFF_ONLY = "Staff and Founder only for this one - you don't have the rank."
_ERR_MOD_ONLY = "You need Developer rank or above for this - not your call."
_ERR_BASIC_MOD_ONLY = "You need at least a Tester role for this - not your call."
_ERR_RANK_INSUFFICIENT = "You don't have the rank for this one."


def owner_only(func: Callable) -> Callable:
    """Restrict handler to the Founder only."""

    @functools.wraps(func)
    async def _wrapper(update: Update, ctx: ContextTypes.DEFAULT_TYPE) -> None:
        """Allow the call only when the invoking user is the Founder."""
        uid = update.effective_user.id if update.effective_user else None
        if uid and await db.users_roles.is_owner(uid):
            return await func(update, ctx)
        if update.effective_message:
            await update.effective_message.reply_text(_ERR_OWNER_ONLY)
        return None

    return _wrapper


def staff_only(func: Callable) -> Callable:
    """Restrict handler to Founder and Admin."""

    @functools.wraps(func)
    async def _wrapper(update: Update, ctx: ContextTypes.DEFAULT_TYPE) -> None:
        """Allow the call only when the invoking user is Founder or Admin."""
        uid = update.effective_user.id if update.effective_user else None
        if uid and await db.users_roles.is_staff(uid):
            return await func(update, ctx)
        if update.effective_message:
            await update.effective_message.reply_text(_ERR_STAFF_ONLY)
        return None

    return _wrapper


def mod_only(func: Callable) -> Callable:
    """Restrict handler to Founder, Admin, Developer (ban/unban level)."""

    @functools.wraps(func)
    async def _wrapper(update: Update, ctx: ContextTypes.DEFAULT_TYPE) -> None:
        """Allow the call only when the invoking user holds Developer rank or above."""
        uid = update.effective_user.id if update.effective_user else None
        if uid and db.users_roles.role_rank(
            await db.users_roles.get_effective_role(uid)
        ) >= db.users_roles.role_rank("developer"):
            return await func(update, ctx)
        if update.effective_message:
            await update.effective_message.reply_text(_ERR_MOD_ONLY)
        return None

    return _wrapper


def basic_mod_only(func: Callable) -> Callable:
    """Restrict handler to Founder, Admin, Developer, Tester (kick/mute/warn level)."""

    @functools.wraps(func)
    async def _wrapper(update: Update, ctx: ContextTypes.DEFAULT_TYPE) -> None:
        """Allow the call only when the invoking user holds Tester rank or above."""
        uid = update.effective_user.id if update.effective_user else None
        if uid and db.users_roles.role_rank(
            await db.users_roles.get_effective_role(uid)
        ) >= db.users_roles.role_rank("tester"):
            return await func(update, ctx)
        if update.effective_message:
            await update.effective_message.reply_text(_ERR_BASIC_MOD_ONLY)
        return None

    return _wrapper


# ────────────────── Shared executor-vs-target check ─────────────── #


async def resolve_and_check(
    msg: Message,
    executor_id: int,
    target_id: int,
    *,
    min_role: str,
) -> tuple[str | None, str | None]:
    """Validate executor permission and target eligibility for moderation actions.

    Replies on the message itself when the executor lacks rank or the target
    outranks the executor, then returns ``(None, None)``.

    On success, returns ``(executor_role, target_role)``.
    """
    executor_role, target_role = await asyncio.gather(
        db.users_roles.get_effective_role(executor_id),
        db.users_roles.get_effective_role(target_id),
    )
    if db.users_roles.role_rank(executor_role) < db.users_roles.role_rank(min_role):
        await msg.reply_text(_ERR_RANK_INSUFFICIENT)
        return None, None

    if target_role and db.users_roles.role_rank(
        executor_role
    ) <= db.users_roles.role_rank(target_role):
        label = db.users_roles.ROLE_LABEL.get(target_role, target_role.capitalize())
        await msg.reply_text(
            f"That's a {label} - they outrank you here, can't take action on them."
        )
        return None, None

    return executor_role, target_role
