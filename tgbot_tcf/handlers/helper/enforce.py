# © Copyright 2024 - 2026 Transsion Core
# © Copyright 2024 - 2026 Dizzy
# © Copyright 2026 Aveum Apps
"""Automatic cross-group ban / unban enforcement (PROMPT Features 5, 6, 8).

Used after every Transsion Core ban, unban, and approved appeal — there is no
manual sync command in TCF. Each routine fans out across active federated
groups in parallel under a bounded concurrency limit and only acts where the
bot has ``can_restrict_members``.
"""
from __future__ import annotations

import asyncio
import logging
from collections.abc import Awaitable, Callable
from typing import Any

from telegram.error import TelegramError
from telegram.ext import ContextTypes

from ...database import federated_groups

logger = logging.getLogger(__name__)

_MAX_CONCURRENCY = 10


async def _fan_out(
    context: ContextTypes.DEFAULT_TYPE,
    user_id: int,
    *,
    label: str,
    apply: Callable[[int, int], Awaitable[Any]],
) -> tuple[int, int]:
    sem = asyncio.Semaphore(_MAX_CONCURRENCY)

    async def worker(chat_id: int) -> bool:
        async with sem:
            try:
                me = await context.bot.get_chat_member(chat_id, context.bot.id)
                if not getattr(me, "can_restrict_members", False):
                    return False
                await apply(chat_id, user_id)
                return True
            except TelegramError as exc:
                logger.warning("Cross-group %s in %s failed: %s", label, chat_id, exc)
                return False

    chat_ids = [
        grp["chat_id"] async for grp in federated_groups.find({"is_active": True})
    ]
    if not chat_ids:
        return 0, 0
    results = await asyncio.gather(*(worker(cid) for cid in chat_ids))
    success = sum(1 for ok in results if ok)
    return success, len(results) - success


async def enforce_ban_across_groups(
    context: ContextTypes.DEFAULT_TYPE, user_id: int
) -> tuple[int, int]:
    """Ban ``user_id`` across every active federated group (parallel)."""

    async def apply(chat_id: int, uid: int) -> None:
        await context.bot.ban_chat_member(chat_id=chat_id, user_id=uid)

    return await _fan_out(context, user_id, label="ban", apply=apply)


async def enforce_unban_across_groups(
    context: ContextTypes.DEFAULT_TYPE, user_id: int
) -> tuple[int, int]:
    """Unban ``user_id`` across every active federated group (parallel)."""

    async def apply(chat_id: int, uid: int) -> None:
        await context.bot.unban_chat_member(
            chat_id=chat_id, user_id=uid, only_if_banned=True
        )

    return await _fan_out(context, user_id, label="unban", apply=apply)
