# © Copyright 2024 - 2026 Transsion Core
# © Copyright 2024 - 2026 Dizzy
# © Copyright 2026 Ave Studio

"""leaveall and cleanup maintenance commands for managing the connected-group list."""

from __future__ import annotations

import asyncio
import logging
from typing import TYPE_CHECKING

from telegram.ext import ContextTypes, MessageHandler

from tcbot import cfg
from tcbot import database as db
from tcbot.database.documents import GroupDoc
from tcbot.modules.helper import decorators, parse_logmsg, replies
from tcbot.modules.helper.formatter import code
from tcbot.utils.prefixes import build_prefixed_filters

if TYPE_CHECKING:
    from telegram import Bot, Update

log = logging.getLogger(__name__)

# ─────────────────────── Rate-limiter constants ──────────────────── #
_RL_PERIOD_LONG_S: int = 60
_RL_PERIOD_BULK_S: int = 300
_RL_CLEANUP_LIMIT: int = 3
_RL_LEAVEALL_LIMIT: int = 1

_MEMBERSHIP_CHECK_TIMEOUT = 3.0


# ────────────────────── Module & Help Message ───────────────────── #

__module_name__ = "Cleanup"
__help_text__ = (
    "Maintenance commands for managing connected groups: clean up inaccessible ones "
    "or leave all in an emergency."
)

__help_sections__: list[tuple[str, str]] = [
    (
        replies.SEC_COMMANDS,
        "<code>/leaveall</code> (aliases: <code>/exitall</code>, <code>/tcleave</code>)\n"
        "<code>/cleanup</code> (aliases: <code>/tcclean</code>, <code>/tcc</code>)",
    ),
    (
        replies.SEC_WHO,
        f"<b>/leaveall</b>: {replies.PERM_FOUNDER_ONLY}\n"
        f"<b>/cleanup</b>: {replies.PERM_STAFF_ONLY}",
    ),
    (
        replies.SEC_WHERE,
        replies.CONTEXT_EXEC_OR_GROUP,
    ),
    (
        "/leaveall",
        "Makes the bot leave every connected group simultaneously, marks them all as "
        "disconnected in the database, and posts a log entry for each group. "
        "This is irreversible - each group must be manually reconnected with "
        "<code>/tcconnect</code>. Use only in emergencies.",
    ),
    (
        "/cleanup",
        "Scans all groups in the database and attempts to verify the bot still has access. "
        "Any group where the bot was kicked, removed, or can no longer reach is marked as "
        "disconnected and removed from the active list. "
        "Run this periodically to keep the group list accurate.",
    ),
    (
        replies.SEC_EXAMPLES,
        "<code>/cleanup</code>: remove stale or inaccessible groups.\n"
        "<code>/leaveall</code>: emergency withdrawal from all connected groups.",
    ),
]


# ──────────────────────── Helper Functions ──────────────────────── #


async def _leave_one(
    bot: Bot,
    grp: dict,
    lc: int,
    lt: int | None,
    admin_id: int,
    admin_name: str,
) -> list:
    """Leave one group, deactivate it in DB, and post a disconnection log - all in parallel."""
    return await asyncio.gather(
        bot.leave_chat(grp["chat_id"]),
        db.groups_db.deactivate_group(grp["chat_id"]),
        bot.send_message(
            lc,
            parse_logmsg.group_disconnected_log(
                grp["chat_id"],
                grp["title"],
                admin_id,
                admin_name,
            ),
            parse_mode="HTML",
            message_thread_id=lt,
        ),
        return_exceptions=True,
    )


async def _should_remove(bot: Bot, grp: GroupDoc) -> bool:
    """Return True if the bot has left or been kicked from the group."""
    try:
        member = await asyncio.wait_for(
            bot.get_chat_member(grp["chat_id"], bot.id),
            timeout=_MEMBERSHIP_CHECK_TIMEOUT,
        )
        return member.status in ("left", "kicked")
    except Exception as exc:
        log.debug("Could not verify membership for %d: %s", grp["chat_id"], exc)
        return True


# ────────────────── Command Leave All </leaveall> ───────────────── #


@decorators.ratelimiter(limit=_RL_LEAVEALL_LIMIT, period=_RL_PERIOD_BULK_S)
@decorators.owner_only
@decorators.log_execution
async def cmd_leaveall(update: Update, ctx: ContextTypes.DEFAULT_TYPE) -> None:
    """Leave all active connected groups and deactivate their DB records.

    Fetches active groups, fans out individual leave-and-deactivate coroutines
    concurrently (``_leave_one``), then edits the status message with the final
    success/failure counts.
    """
    admin = update.effective_user
    groups = await db.groups_db.active_groups()
    if not groups:
        await update.effective_message.reply_text(replies.ERR_NO_CONNECTED_GROUPS)
        return

    status = await update.effective_message.reply_text(
        f"Leaving {len(groups)} groups..."
    )
    lc, lt = cfg.logs

    # * All groups processed concurrently - no sequential sleep between them
    all_results = await asyncio.gather(
        *(_leave_one(ctx.bot, g, lc, lt, admin.id, admin.first_name) for g in groups),
        return_exceptions=True,
    )

    left = sum(
        1
        for r in all_results
        if not isinstance(r, BaseException) and not isinstance(r[0], BaseException)
    )
    failed = len(groups) - left

    try:
        await status.edit_text(
            f"Left {code(str(left))} groups. Failed: {code(str(failed))}.",
            parse_mode="HTML",
        )
    except Exception:
        log.exception("Leaveall status edit failed")


# ─────────────────── Command CleanUp </cleanup> ─────────────────── #


@decorators.ratelimiter(limit=_RL_CLEANUP_LIMIT, period=_RL_PERIOD_LONG_S)
@decorators.staff_only
@decorators.log_execution
async def cmd_cleanup(update: Update, ctx: ContextTypes.DEFAULT_TYPE) -> None:
    """Prune inaccessible groups from the active federation list.

    Checks all groups concurrently via ``_should_remove``, deactivates the
    identified stale records in parallel, then replies with the count of removed
    groups.
    """
    groups = await db.groups_db.active_groups()

    # * Check all groups concurrently - one network round-trip per group, all in parallel
    checks = await asyncio.gather(
        *(_should_remove(ctx.bot, g) for g in groups),
        return_exceptions=True,
    )

    to_remove = [g for g, remove in zip(groups, checks, strict=False) if remove is True]

    if to_remove:
        await asyncio.gather(
            *(db.groups_db.deactivate_group(g["chat_id"]) for g in to_remove),
            return_exceptions=True,
        )

    await update.effective_message.reply_text(
        f"Cleaned up {code(str(len(to_remove)))} inaccessible group(s).",
        parse_mode="HTML",
    )


# ──────────────────────────── Handlers ──────────────────────────── #

_LEAVEALL_CMDS = (
    build_prefixed_filters("leaveall")
    | build_prefixed_filters("exitall")
    | build_prefixed_filters("tcleave")
)
_CLEANUP_CMDS = (
    build_prefixed_filters("cleanup")
    | build_prefixed_filters("tcclean")
    | build_prefixed_filters("tcc")
)


__handlers__ = [
    MessageHandler(_LEAVEALL_CMDS, cmd_leaveall),
    MessageHandler(_CLEANUP_CMDS, cmd_cleanup),
]
