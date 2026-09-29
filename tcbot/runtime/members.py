# © Copyright 2024 - 2026 Transsion Core
# © Copyright 2024 - 2026 Dizzy
# © Copyright 2026 Ave Labs

"""Member cache harvester: caches the effective user of every update."""

from __future__ import annotations

import asyncio

from telegram import Update
from telegram.ext import ContextTypes

from tcbot import database as db
from tcbot.utils.logger import get_logger

log = get_logger(__name__)

# * Strong references to in-flight member-cache background tasks; prevents GC.
_member_cache_tasks: set[asyncio.Task[None]] = set()

# * Strong reference to the one-shot startup cache warm-up task; prevents GC.
_startup_tasks: set[asyncio.Task[None]] = set()


async def _update_member_cache(update: Update, ctx: ContextTypes.DEFAULT_TYPE) -> None:
    """Cache the effective_user from any update; bot-issued events are skipped.

    Uses ``harvest_user_identity`` (live User object: absent fields clear
    stale values) so the L1 mention cache is consulted first. When identity
    data matches the cached entry no DB write is issued, making the fast
    path sub-microsecond.  When a write is needed it is fire-and-forget
    so this handler never blocks the downstream handler chain.
    """
    user = update.effective_user
    if not user or user.is_bot:
        return
    if not user.first_name:
        return

    uid = user.id
    uname = user.username
    fname = user.first_name
    lname = user.last_name

    async def _do_cache() -> None:
        try:
            await db.users_cache.harvest_user_identity(uid, uname, fname, lname)
        except Exception as exc:
            log.debug("Member cache update failed for %d: %s", uid, exc)

    try:
        task = asyncio.get_running_loop().create_task(_do_cache())
        _member_cache_tasks.add(task)
        task.add_done_callback(_member_cache_tasks.discard)
    except RuntimeError:
        log.debug("Member cache warmup skipped: no running event loop.")
