# © Copyright 2024 - 2026 Transsion Core
# © Copyright 2024 - 2026 Dizzy
# © Copyright 2026 Aveum Apps
"""Auth decorators and global per-user rate limiter for all handlers."""
from __future__ import annotations

import functools
import logging
import time
from collections import defaultdict, deque

from telegram import Update
from telegram.ext import ApplicationHandlerStop, ContextTypes

from tcbot import cfg
from tcbot import database as db
from tcbot.database.roles_db import get_effective_role, role_rank

log = logging.getLogger(__name__)

## ---------------------------------------------------------------------------
## Per-user sliding-window rate limiter
## ---------------------------------------------------------------------------

_BUCKETS: dict[tuple[int, str], deque[float]] = defaultdict(deque)

## Callback query: 20 presses per 10 seconds (≈ 2 / s) — fast navigation allowed
_CBQ_MAX  = 20
_CBQ_WIN  = 10.0

## Commands: 5 per 30 seconds — generous for normal moderation work
_CMD_MAX  = 5
_CMD_WIN  = 30.0


def _allow(uid: int, bucket: str, max_calls: int, window: float) -> bool:
    """Return True if the call is within the rate limit, False if it should be dropped."""
    key = (uid, bucket)
    now = time.monotonic()
    dq  = _BUCKETS[key]
    while dq and now - dq[0] >= window:
        dq.popleft()
    if len(dq) >= max_calls:
        return False
    dq.append(now)
    return True


async def global_rate_limit_handler(update: Update, ctx: ContextTypes.DEFAULT_TYPE) -> None:
    """Universal per-user rate limiter — registered at group -1 so it runs before every handler.

    * CallbackQuery  → 20 per 10 s   (button navigation)
    * Command text   → 5  per 30 s   (mod commands)
    * Other messages → always pass   (member cache, conversation text, etc.)

    When rate-limited: silently acknowledges callback queries and raises
    ApplicationHandlerStop to cancel ALL subsequent handler groups.
    """
    uid = update.effective_user.id if update.effective_user else None
    if not uid:
        return

    if update.callback_query:
        if not _allow(uid, "cbq", _CBQ_MAX, _CBQ_WIN):
            try:
                await update.callback_query.answer(
                    "Upss, slow down.", show_alert=True
                )
            except Exception:
                pass
            raise ApplicationHandlerStop
        return

    msg  = update.effective_message
    text = (msg.text or "") if msg else ""
    if not text:
        return

    if not any(text.startswith(p) for p in cfg.prefixes):
        return  ## plain message — do not rate limit

    if not _allow(uid, "cmd", _CMD_MAX, _CMD_WIN):
        if msg:
            try:
                await msg.reply_text(
                    "Slow down — please wait a moment before running another command."
                )
            except Exception:
                pass
        raise ApplicationHandlerStop


## ---------------------------------------------------------------------------
## Auth decorators
## ---------------------------------------------------------------------------

def owner_only(func):
    @functools.wraps(func)
    async def wrapper(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
        uid = update.effective_user.id if update.effective_user else None
        if uid and await db.admins_db.is_owner(uid):
            return await func(update, ctx)
        if update.effective_message:
            await update.effective_message.reply_text(
                "This command is reserved for the Founder — you're not authorized. 🔒"
            )
    return wrapper


def staff_only(func):
    """Founder and Admin."""
    @functools.wraps(func)
    async def wrapper(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
        uid = update.effective_user.id if update.effective_user else None
        if uid and await db.admins_db.is_staff(uid):
            return await func(update, ctx)
        if update.effective_message:
            await update.effective_message.reply_text(
                "Staff and Founder only for this one — you don't have the rank. 🚫"
            )
    return wrapper


def mod_only(func):
    """Founder, Admin, Developer — for ban/unban."""
    @functools.wraps(func)
    async def wrapper(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
        uid = update.effective_user.id if update.effective_user else None
        if uid and role_rank(await get_effective_role(uid)) >= role_rank("developer"):
            return await func(update, ctx)
        if update.effective_message:
            await update.effective_message.reply_text(
                "You need Developer rank or above for this — not your call. 🚫"
            )
    return wrapper


def basic_mod_only(func):
    """Founder, Admin, Developer, Tester — for kick/mute/warn."""
    @functools.wraps(func)
    async def wrapper(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
        uid = update.effective_user.id if update.effective_user else None
        if uid and role_rank(await get_effective_role(uid)) >= role_rank("tester"):
            return await func(update, ctx)
        if update.effective_message:
            await update.effective_message.reply_text(
                "You need at least a Tester role for this — not your call. 🚫"
            )
    return wrapper
