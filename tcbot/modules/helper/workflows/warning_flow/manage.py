# © Copyright 2024 - 2026 Transsion Core
# © Copyright 2024 - 2026 Dizzy
# © Copyright 2026 Ave Labs

"""Warn management executors: unwarn, warnlist, and resetwarns."""

from __future__ import annotations

import asyncio
from typing import TYPE_CHECKING

from telegram import Update

from tcbot import cfg
from tcbot import database as db
from tcbot.modules.helper import parse_logmsg, replies
from tcbot.modules.helper.locale import locale_for_update
from tcbot.modules.helper.parse_editmsg import safe_reply
from tcbot.utils.formatter import user_ref
from tcbot.utils.i18n import Safe, t
from tcbot.utils.logger import get_logger

if TYPE_CHECKING:
    from telegram.ext import ContextTypes

log = get_logger(__name__)


async def execute_unwarn(
    update: Update,
    ctx: ContextTypes.DEFAULT_TYPE,
    target_id: int,
    target_name: str,
) -> None:
    """Remove one warning from the target in the current group.

    Checks the current warn count; replies and returns early if the target has
    none. Otherwise decrements by one, logs the action, and sends the log and
    reply concurrently.
    """
    msg = update.effective_message
    if msg is None:
        return
    chat = update.effective_chat
    if chat is None:
        return
    chat_id = chat.id
    locale = await locale_for_update(update)

    # * Fail closed with a retry reply instead of ending silently on outage.
    try:
        count = await db.warns_db.warn_count(target_id, chat_id)
    except Exception:
        log.exception(
            "warn_count read failed for target=%d chat=%d", target_id, chat_id
        )
        await safe_reply(
            msg,
            replies.err_db_retry(locale, plain=True),
            log_label="execute_unwarn DB-fail",
            parse_mode=None,
        )
        return
    if count == 0:
        await safe_reply(
            msg,
            t(
                "warnings.none.body",
                locale,
                user=Safe(user_ref(target_id, target_name)),
            ),
            log_label="execute_unwarn no-warns",
        )
        return

    new_count = max(count - 1, 0)
    chat_title = chat.title or str(chat_id)
    warn_limit = cfg.warn_limit
    admin = update.effective_user
    if admin is None:
        return
    lc, lt = cfg.logs
    log_text = parse_logmsg.unwarn_log(
        target_id,
        target_name,
        admin.id,
        admin.first_name,
        new_count,
        cfg.warn_limit,
        chat_id,
        chat_title,
    )
    # * Remove first, then report what actually happened. Logging the
    # * computed new_count before the delete lands lies on concurrent
    # * unwarns: a second racing unwarn finds nothing to delete but the
    # * reply was already sent claiming success.
    try:
        removed = await db.warns_db.remove_last_warn(target_id, chat_id)
    except Exception:
        log.exception(
            "remove_last_warn DB write failed for target=%d chat=%d",
            target_id,
            chat_id,
        )
        # * Fail closed: remove_last_warn raises on write outage (never a
        # * silent False), so report the outage instead of the "no warnings"
        # * message below, which would lie about a user that may hold warns.
        await safe_reply(
            msg,
            replies.err_db_retry(locale, plain=True),
            log_label="execute_unwarn db_retry",
        )
        return
    if not removed:
        await safe_reply(
            msg,
            t(
                "warnings.none.body",
                locale,
                user=Safe(user_ref(target_id, target_name)),
            ),
            log_label="execute_unwarn empty",
        )
        return
    # * Re-read the count after the delete so concurrent unwarns report
    # * the true remaining total instead of a stale computed value.
    try:
        new_count = await db.warns_db.warn_count(target_id, chat_id)
    except Exception:
        log.exception(
            "warn_count re-read failed for target=%d chat=%d",
            target_id,
            chat_id,
        )
        new_count = max(count - 1, 0)
    log_text = parse_logmsg.unwarn_log(
        target_id,
        target_name,
        admin.id,
        admin.first_name,
        new_count,
        cfg.warn_limit,
        chat_id,
        chat_title,
    )
    results = await asyncio.gather(
        ctx.bot.send_message(
            lc, log_text, parse_mode="MarkdownV2", message_thread_id=lt
        ),
        msg.reply_text(
            t(
                "warnings.removed.body",
                locale,
                user=Safe(user_ref(target_id, target_name)),
                new=new_count,
                limit=warn_limit,
            ),
            parse_mode="MarkdownV2",
        ),
        return_exceptions=True,
    )
    if isinstance(results[0], BaseException):
        log.error("Unwarn log send failed: %s", results[0])


async def execute_warnlist(
    update: Update,
    ctx: ContextTypes.DEFAULT_TYPE,
    target_id: int,
    target_name: str,
) -> None:
    """Reply with the numbered list of active warnings for the target in this group.

    Fetches all warnings from ``db.warns_db.get_warns`` and replies with a
    formatted list. Replies early if no warnings exist.
    """
    msg = update.effective_message
    if msg is None:
        return
    chat = update.effective_chat
    if chat is None:
        return
    chat_id = chat.id
    locale = await locale_for_update(update)

    # * Fail closed with a retry reply instead of ending silently on outage.
    try:
        warns = await db.warns_db.get_warns(target_id, chat_id)
    except Exception:
        log.exception("get_warns read failed for target=%d chat=%d", target_id, chat_id)
        await safe_reply(
            msg,
            replies.err_db_retry(locale, plain=True),
            log_label="execute_warnlist DB-fail",
            parse_mode=None,
        )
        return
    count = len(warns)

    if count == 0:
        await safe_reply(
            msg,
            t(
                "warnings.none.body",
                locale,
                user=Safe(user_ref(target_id, target_name)),
            ),
            log_label="execute_warnlist no-warns",
        )
        return

    header = t(
        "warnings.list.header",
        locale,
        user=Safe(user_ref(target_id, target_name)),
        count=count,
        limit=cfg.warn_limit,
    )
    lines = [header]
    for i, w in enumerate(warns, 1):
        lines.append(
            t(
                "warnings.list.item",
                locale,
                i=i,
                reason=w.get("reason", "")
                or t("warnings.list.no_reason", locale, plain=True),
            )
        )

    await safe_reply(msg, "\n".join(lines), log_label="execute_warnlist")


async def execute_resetwarns(
    update: Update,
    ctx: ContextTypes.DEFAULT_TYPE,
    target_id: int,
    target_name: str,
) -> None:
    """Clear all active warnings for the target in the current group.

    Calls ``db.warns_db.clear_warns`` and replies with the number of removed
    warnings. Replies early if the target has no warnings to clear.
    Logs the action to the mod log channel on success.
    """
    msg = update.effective_message
    if msg is None:
        return
    admin = update.effective_user
    if admin is None:
        return
    chat = update.effective_chat
    if chat is None:
        return
    chat_id = chat.id
    chat_title = chat.title or str(chat_id)
    lc, lt = cfg.logs
    locale = await locale_for_update(update)

    removed = 0
    try:
        removed = await db.warns_db.clear_warns(target_id, chat_id)
    except Exception:
        log.exception("clear_warns failed for target=%d chat=%d", target_id, chat_id)
        await safe_reply(
            msg,
            replies.err_db_retry(locale, plain=True),
            log_label="execute_resetwarns DB-fail",
            parse_mode=None,
        )
        return
    if removed == 0:
        await safe_reply(
            msg,
            t(
                "warnings.none_clear.body",
                locale,
                user=Safe(user_ref(target_id, target_name)),
            ),
            log_label="execute_resetwarns no-warns",
        )
        return

    log_text = parse_logmsg.resetwarns_log(
        target_id,
        target_name,
        admin.id,
        admin.first_name,
        removed,
        chat_id,
        chat_title,
    )
    results = await asyncio.gather(
        ctx.bot.send_message(
            lc, log_text, parse_mode="MarkdownV2", message_thread_id=lt
        ),
        msg.reply_text(
            t(
                "warnings.cleared.body",
                locale,
                removed=removed,
                user=Safe(user_ref(target_id, target_name)),
            ),
            parse_mode="MarkdownV2",
        ),
        return_exceptions=True,
    )
    if isinstance(results[0], BaseException):
        log.exception(
            "Reset-warns log send failed for target=%d: %s", target_id, results[0]
        )
