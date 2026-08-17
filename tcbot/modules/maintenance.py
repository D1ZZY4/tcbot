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
from tcbot.modules.helper.formatter import bold, code
from tcbot.utils.dispatch import fan_out
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

__module_name__ = "Maintenance"
__help_text__ = (
    "Maintenance commands for managing connected groups: clean up inaccessible ones "
    "or leave all in an emergency."
)

__help_sections__: list[tuple[str, str]] = [
    (
        replies.SEC_COMMANDS,
        f"{code('/leaveall')} (aliases: {code('/exitall')}, {code('/tcleave')})\n"
        f"{code('/cleanup')} (aliases: {code('/tcclean')}, {code('/tcc')})",
    ),
    replies.who_section(
        f"{bold('/leaveall')}: {replies.PERM_FOUNDER_ONLY}\n"
        f"{bold('/cleanup')}: {replies.PERM_STAFF_ONLY}"
    ),
    replies.where_section(replies.CONTEXT_EXEC_OR_GROUP),
    (
        "/leaveall",
        "Makes the bot leave every connected group simultaneously, marks them all as "
        "disconnected in the database, and posts a log entry for each group. "
        f"This is irreversible - each group must be manually reconnected with "
        f"{code('/tcconnect')}. Use only in emergencies.",
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
        f"{code('/cleanup')}: remove stale or inaccessible groups.\n"
        f"{code('/leaveall')}: emergency withdrawal from all connected groups.",
    ),
]

__help__: replies.HelpEntry = {
    "name": __module_name__,
    "overview": __help_text__,
    "sections": __help_sections__,
}


# ──────────────────────── Helper Functions ──────────────────────── #


async def _leave_one(
    bot: Bot,
    grp: GroupDoc,
    lc: int,
    lt: int | None,
    admin_id: int,
    admin_name: str,
) -> tuple:
    """Leave one group, deactivate it in DB, and post a disconnection log - all in parallel."""
    chat_id = grp.get("chat_id")
    title = grp.get("title", "Unknown")
    assert chat_id is not None
    return await asyncio.gather(
        bot.leave_chat(chat_id),
        db.groups_db.deactivate_group(chat_id),
        bot.send_message(
            lc,
            parse_logmsg.group_disconnected_log(
                chat_id,
                title,
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
    chat_id = grp.get("chat_id")
    if chat_id is None:
        return True
    try:
        member = await asyncio.wait_for(
            bot.get_chat_member(chat_id, bot.id),
            timeout=_MEMBERSHIP_CHECK_TIMEOUT,
        )
        return member.status in ("left", "kicked")
    except Exception as exc:
        log.debug("Could not verify membership for %d: %s", chat_id, exc)
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
    assert admin is not None
    groups = await db.groups_db.active_groups()
    if not groups:
        status_msg = update.effective_message
        if status_msg is not None:
            try:
                await status_msg.reply_text(replies.ERR_NO_CONNECTED_GROUPS)
            except Exception as exc:
                log.debug("leaveall no-groups reply failed: %s", exc)
        return

    status_msg = update.effective_message
    status = None
    if status_msg is not None:
        try:
            status = await status_msg.reply_text(f"Leaving {len(groups)} groups...")
        except Exception as exc:
            log.debug("leaveall status reply failed: %s", exc)
    lc, lt = cfg.logs

    # * Semaphore-bounded to respect Telegram rate limits on large federations.
    all_results = await fan_out(
        [
            _leave_one(ctx.bot, g, lc, lt, admin.id, admin.first_name)
            for g in groups
        ]
    )

    left = sum(
        1
        for r in all_results
        if not isinstance(r, BaseException)
        and not isinstance(r[0], BaseException)
    )
    failed = len(groups) - left

    if status is not None:
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
    reply_msg = update.effective_message
    assert reply_msg is not None
    groups = await db.groups_db.active_groups()

    # * Semaphore-bounded to respect Telegram rate limits on large federations.
    checks = await fan_out([_should_remove(ctx.bot, g) for g in groups])

    to_remove = [g for g, remove in zip(groups, checks, strict=False) if remove is True]

    if to_remove:
        await fan_out(
            [db.groups_db.deactivate_group(g.get("chat_id", 0)) for g in to_remove]
        )

    try:
        await reply_msg.reply_text(
            f"Cleaned up {code(str(len(to_remove)))} inaccessible group(s).",
            parse_mode="HTML",
        )
    except Exception as exc:
        log.debug("cleanup reply failed: %s", exc)


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
