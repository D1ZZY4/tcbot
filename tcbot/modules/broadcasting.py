# © Copyright 2024 - 2026 Transsion Core
# © Copyright 2024 - 2026 Dizzy
# © Copyright 2026 Ave Labs

"""Broadcast command handler: sends a message to all connected groups."""

from __future__ import annotations

import asyncio
import logging
from typing import TYPE_CHECKING

from telegram.error import BadRequest
from telegram.ext import ContextTypes, MessageHandler

from tcbot import cfg
from tcbot import database as db
from tcbot.database.documents import GroupDoc
from tcbot.modules.helper import decorators, parse_logmsg, replies
from tcbot.modules.helper.locale import locale_for_update
from tcbot.modules.helper.parse_editmsg import safe_reply
from tcbot.utils.dispatch import count_transient_errors, fan_out
from tcbot.utils.formatter import code
from tcbot.utils.i18n import Safe, t
from tcbot.utils.prefixes import build_prefixed_filters, parse_cmd_args

if TYPE_CHECKING:
    from telegram import Update

log = logging.getLogger(__name__)

# ─────────────────────── Rate-limiter constants ──────────────────── #
_RL_PERIOD_S: int = 60
_RL_LIMIT: int = 3


# ────────────────────── Module & Help Message ───────────────────── #

__module_name__ = "Broadcast"


def get_help(locale: str | None = None) -> replies.HelpEntry:
    """Build this module's help entry in the given locale."""
    overview = t("broadcasting.help.overview", locale, community=cfg.community_name)
    sections: list[tuple[str, str]] = [
        (
            replies.sec_commands(locale),
            t("broadcasting.help.commands.body", locale),
        ),
        replies.who_section(replies.perm_staff_only(locale, plain=False), locale),
        replies.where_section(replies.context_exec_or_group(locale), locale),
        (
            replies.sec_what(locale),
            t("broadcasting.help.what.body", locale, community=cfg.community_name),
        ),
        (
            replies.sec_examples(locale),
            t("broadcasting.help.examples.body", locale),
        ),
    ]
    return {"name": __module_name__, "overview": overview, "sections": sections}


__help__: replies.HelpEntry = get_help()
__help_text__ = __help__["overview"]
__help_sections__ = __help__["sections"]


# ──────────────── Command Broadcast </tcbroadcast> ──────────────── #


@decorators.ratelimiter(limit=_RL_LIMIT, period=_RL_PERIOD_S)
@decorators.staff_only
@decorators.log_execution
async def cmd_broadcast(update: Update, ctx: ContextTypes.DEFAULT_TYPE) -> None:
    """Send a message or forward a replied-to message to all connected groups.

    Accepts an inline text argument or a reply-to-message. Fans out sends to
    every active group via ``fan_out`` with semaphore limiting. Logs the result
    and edits the status message in parallel.
    """
    locale = await locale_for_update(update)
    msg = update.effective_message
    admin = update.effective_user
    if msg is None or admin is None:
        return

    args = parse_cmd_args(msg.text)
    broadcast_text: str | None = " ".join(args).strip() if args else None

    has_reply = bool(msg.reply_to_message)
    if not broadcast_text and not has_reply:
        await safe_reply(
            msg,
            t("broadcasting.send.no_content", locale),
            log_label="cmd_broadcast no-content",
        )
        return

    try:
        groups = await db.groups_db.active_groups()
    except Exception:
        log.exception("active_groups failed during broadcast")
        await safe_reply(
            msg,
            replies.err_groups_load_failed(locale, plain=False),
            log_label="cmd_broadcast groups-failed",
        )
        return
    if not groups:
        await safe_reply(
            msg,
            replies.err_no_connected_groups(locale, plain=False),
            log_label="cmd_broadcast no-groups",
        )
        return

    status = None
    try:
        status = await msg.reply_text(
            t("broadcasting.send.sending", locale, n=len(groups), plain=True)
        )
    except Exception as exc:
        log.debug("cmd_broadcast status reply failed: %s", exc)

    # * Build per-group send coroutines, then fan out with semaphore limiting.
    # * Staff text goes out as MarkdownV2 (invalid markup raises BadRequest
    # * per group); fall back to plain text so one typo does not fail the
    # * whole broadcast.
    async def _send_one(grp: GroupDoc) -> None:
        chat_id = grp.get("chat_id")
        if chat_id is None:
            return
        if has_reply and msg.reply_to_message:
            await msg.reply_to_message.forward(chat_id)
        elif broadcast_text:
            try:
                await ctx.bot.send_message(
                    chat_id, broadcast_text, parse_mode="MarkdownV2"
                )
            except BadRequest as exc:
                # * Retry as plain text only for MarkdownV2 parse failures. Any
                # * other BadRequest (chat gone, bot demoted) would fail the
                # * retry identically, so re-raise to avoid doubling Telegram
                # * calls on every dead group in the federation.
                if "can't parse entities" not in str(exc).lower():
                    raise
                log.info(
                    "Broadcast markup rejected in chat=%d; retrying as plain text",
                    chat_id,
                )
                await ctx.bot.send_message(chat_id, broadcast_text)

    results = await fan_out([_send_one(grp) for grp in groups])
    # * Benign per-group refusals (bot removed, chat gone) are not operator
    # * failures; count only transient errors like every other fan-out.
    failed = count_transient_errors(results)
    success = len(results) - failed

    for grp, r in zip(groups, results, strict=False):
        if isinstance(r, BaseException):
            log.warning("Broadcast failed for %d: %s", grp.get("chat_id", "?"), r)

    if broadcast_text:
        preview = broadcast_text
    elif msg.reply_to_message:
        preview = msg.reply_to_message.text or "media"
    else:
        preview = ""
    lc, lt = cfg.logs

    # * send log and update status message in parallel
    log_coro = ctx.bot.send_message(
        lc,
        parse_logmsg.broadcast_log(
            admin.id, admin.first_name, preview, success, failed
        ),
        parse_mode="MarkdownV2",
        message_thread_id=lt,
    )
    if status is not None:
        edit_r, log_r = await asyncio.gather(
            status.edit_text(
                t(
                    "broadcasting.send.done",
                    locale,
                    ok=Safe(code(str(success))),
                    failed=Safe(code(str(failed))),
                ),
                parse_mode="MarkdownV2",
            ),
            log_coro,
            return_exceptions=True,
        )
    else:
        edit_r = None
        (log_r,) = await asyncio.gather(log_coro, return_exceptions=True)
    if isinstance(edit_r, BaseException):
        log.debug("Broadcast status edit failed: %s", edit_r)
    if isinstance(log_r, BaseException):
        log.error("Broadcast log send failed: %s", log_r)


# ──────────────────────────── Handlers ──────────────────────────── #

_BROADCAST_CMDS = build_prefixed_filters("tcbroadcast") | build_prefixed_filters("bc")

__handlers__ = [MessageHandler(_BROADCAST_CMDS, cmd_broadcast)]
