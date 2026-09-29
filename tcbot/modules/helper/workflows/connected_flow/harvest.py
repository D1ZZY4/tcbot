# © Copyright 2024 - 2026 Transsion Core
# © Copyright 2024 - 2026 Dizzy
# © Copyright 2026 Ave Labs

"""Background admin-identity harvest for newly connected groups."""

from __future__ import annotations

import asyncio

from telegram import ChatMember

from tcbot import database as db
from tcbot.utils.dispatch import drain_tasks
from tcbot.utils.logger import get_logger

log = get_logger(__name__)


# ────────────────── Admin Identity Harvest ──────────────────────── #
# * Called as fire-and-forget task when the bot gains access to a new group.
# * Caches every admin's identity so name lookups are available without extra
# * MongoDB or Telegram API round-trips later.

# * Strong references to in-flight admin-harvest background tasks; prevents GC
# * before the coroutine completes (RUF006 compliance).
_harvest_tasks: set[asyncio.Task[None]] = set()


async def drain_harvest_tasks() -> None:
    """Await in-flight admin-harvest tasks at shutdown (bounded, never raises)."""
    await drain_tasks(_harvest_tasks, label="admin harvest")


async def _harvest_admin_identities(
    chat_id: int,
    admins: list[ChatMember],
) -> None:
    """Persist identity data for every admin using change-detection writes.

    Uses ``harvest_user_identity`` (live User objects: absent fields clear
    stale values) so the DB write is skipped when the cached identity
    already matches, keeping the harvest nearly free on subsequent runs.
    """
    coros = []
    for member in admins:
        user = getattr(member, "user", None)
        if user is None or user.is_bot or not user.first_name:
            continue
        coros.append(
            db.users_cache.harvest_user_identity(
                user.id,
                user.username,
                user.first_name,
                user.last_name,
            )
        )
    if not coros:
        return
    results = await asyncio.gather(*coros, return_exceptions=True)
    errors = sum(1 for r in results if isinstance(r, BaseException))
    if errors:
        log.debug(
            "Admin identity harvest for chat=%d: %d/%d writes failed",
            chat_id,
            errors,
            len(coros),
        )
    else:
        log.debug(
            "Admin identity harvest for chat=%d: %d identities cached",
            chat_id,
            len(coros),
        )
