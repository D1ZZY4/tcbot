# © Copyright 2024 - 2026 Transsion Core
# © Copyright 2024 - 2026 Dizzy
# © Copyright 2026 Ave Labs

"""Cleanup maintenance command for pruning stale connected groups."""

from __future__ import annotations

import asyncio
from typing import TYPE_CHECKING

from telegram.ext import ContextTypes

from tcbot import cfg
from tcbot import database as db
from tcbot.database.documents import GroupDoc
from tcbot.modules.helper import decorators, replies
from tcbot.modules.helper.locale import locale_for_update
from tcbot.modules.helper.parse_editmsg import safe_reply
from tcbot.utils.dispatch import fan_out, gather_bounded
from tcbot.utils.formatter import code
from tcbot.utils.i18n import Safe, t
from tcbot.utils.logger import get_logger
from tcbot.utils.time_and_date import TELEGRAM_LOOKUP_TIMEOUT

if TYPE_CHECKING:
    from telegram import Bot, Update

log = get_logger(__name__)

# ─────────────────────── Rate-limiter constants ──────────────────── #
_RL_PERIOD_LONG_S: int = 60
_RL_CLEANUP_LIMIT: int = 3

# * Bound for one membership probe; single owner in time_and_date.
_MEMBERSHIP_CHECK_TIMEOUT = TELEGRAM_LOOKUP_TIMEOUT


# ──────────────────────── Helper Functions ──────────────────────── #


async def _should_remove(bot: Bot, grp: GroupDoc) -> bool:
    """Return True if the bot has left or been kicked from the group.

    Primary groups are never "removable" -- they are managed separately
    and must never be deactivated by cleanup. If ``_should_remove``
    is called for a primary group, it short-circuits to ``False`` so
    ``cmd_cleanup`` skips it.
    """
    chat_id = grp.get("chat_id")
    if chat_id is None:
        return True
    if cfg.is_primary_group(chat_id):
        return False
    try:
        member = await asyncio.wait_for(
            bot.get_chat_member(chat_id, bot.id),
            timeout=_MEMBERSHIP_CHECK_TIMEOUT,
        )
        return member.status in ("left", "kicked")
    except Exception as exc:
        # ! CRITICAL: fail closed. A transient Telegram/DB error must not look
        # ! like "bot has left" or cleanup mass-deactivates healthy groups.
        log.warning(
            "Could not verify membership for %d, keeping group: %s", chat_id, exc
        )
        return False


# ─────────────────── Command CleanUp </cleanup> ─────────────────── #


@decorators.ratelimiter(limit=_RL_CLEANUP_LIMIT, period=_RL_PERIOD_LONG_S)
@decorators.staff_only
@decorators.log_execution
async def cmd_cleanup(update: Update, ctx: ContextTypes.DEFAULT_TYPE) -> None:
    """Prune inaccessible groups from the active federation list.

    Checks all groups concurrently via ``_should_remove`` (which excludes
    primary groups), deactivates the identified stale records in parallel,
    then replies with the count of removed groups.
    """
    reply_msg = update.effective_message
    if reply_msg is None:
        return
    locale = await locale_for_update(update)
    try:
        groups = await db.groups_db.active_groups()
    except Exception:
        log.exception("active_groups failed during cleanup")
        await safe_reply(
            reply_msg,
            replies.err_groups_load_failed(locale, plain=False),
            log_label="cleanup groups-failed",
        )
        return

    # * Semaphore-bounded to respect Telegram rate limits on large federations.
    checks = await fan_out([_should_remove(ctx.bot, g) for g in groups])

    to_remove = [g for g, remove in zip(groups, checks, strict=False) if remove is True]

    if to_remove:
        # * Pure database writes: bounded gather, not fan_out. fan_out wraps
        # * the Telegram circuit breaker, which must not gate DB work.
        deact_results = await gather_bounded(
            [db.groups_db.deactivate_group(g.get("chat_id", 0)) for g in to_remove]
        )
        deactivated = sum(1 for r in deact_results if r is True)
        for grp, result in zip(to_remove, deact_results, strict=False):
            if isinstance(result, BaseException):
                log.error(
                    "cleanup deactivate failed for chat=%s: %s",
                    grp.get("chat_id", 0),
                    result,
                )
            elif result is not True:
                log.warning(
                    "cleanup deactivate no-op for chat=%s (record already gone?)",
                    grp.get("chat_id", 0),
                )
    else:
        deactivated = 0

    await safe_reply(
        reply_msg,
        t(
            "maintenance.cleanup.done",
            locale,
            n=Safe(code(str(deactivated))),
        ),
        log_label="cleanup",
    )
