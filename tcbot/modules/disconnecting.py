# © Copyright 2024 - 2026 Transsion Core
# © Copyright 2024 - 2026 Dizzy
# © Copyright 2026 Ave Labs

"""Group disconnect handlers: removes a group from the federation."""

from __future__ import annotations

import asyncio

from tcbot import cfg
from tcbot import database as db
from tcbot.modules.helper import decorators, messages
from tcbot.modules.helper.context import Ctx, chat_id_of, display_name
from tcbot.modules.helper.handlers import MessageHandler
from tcbot.modules.helper.identity import can_manage_group, is_anon_admin
from tcbot.modules.helper.locale import locale_for_update
from tcbot.modules.helper.messages import replies, reply_rich, send_log
from tcbot.utils.dispatch import throw_if_cancelled
from tcbot.utils.i18n import Safe, code, t
from tcbot.utils.logger import get_logger
from tcbot.utils.prefixes import build_prefixed_filters, parse_cmd_args

log = get_logger(__name__)

# * Disconnect runtime prose lives in disconnecting.toml [state]/[removed].


# ────────────────────── Module & Help Message ───────────────────── #

__module_name__ = "Disconnect"


def get_help(locale: str | None = None) -> replies.HelpEntry:
    """Build this module's help entry in the given locale."""
    return replies.module_help(
        locale,
        name=__module_name__,
        overview=t("disconnecting.help.overview", locale, community=cfg.community_name),
        commands=t("disconnecting.help.commands.body", locale),
        who=t("disconnecting.help.who.body", locale),
        where=t("disconnecting.help.where.body", locale),
        what=t("disconnecting.help.what.body", locale, community=cfg.community_name),
        target=False,
        examples=t("disconnecting.help.examples.body", locale),
    )


__help__: replies.HelpEntry = get_help()


# ────────── Command to Disconnect a Group </tcdisconnect> ───────── #


@decorators.ratelimiter(decorators.THROTTLE_FEDERATION)
@decorators.log_execution
async def cmd_tcdisconnect(ctx: Ctx) -> None:
    """Request to disconnect the current group from the federation.

    Group-only command. Confirms the group is connected, checks that the
    sender is federation staff or the group creator (shared helper with a
    bounded Telegram call), then deactivates the group record first and
    leaves the chat.
    """
    chat = ctx.effective_chat
    user = ctx.effective_user
    msg = ctx.effective_message
    if chat is None or user is None or msg is None:
        return
    locale = await locale_for_update(ctx)

    if getattr(chat.type, "value", chat.type) == "private":
        await reply_rich(
            msg,
            replies.err_group_only(locale, plain=True),
            log_label="cmd_tcdisconnect group-only",
            parse_mode=None,
        )
        return

    # * Deployment destinations (main group, proofs, logs, appeals, main
    # * channel) are required for fan-out and delivery. A legacy active row
    # * must not let this command make the bot leave one of them; the
    # * force-remove path applies the same guard (see cmd_rmtc).
    if cfg.is_infrastructure_chat(chat_id_of(chat)):
        await reply_rich(
            msg,
            t("disconnecting.state.infrastructure_refused", locale, plain=True),
            log_label="cmd_tcdisconnect infrastructure-group",
            parse_mode=None,
        )
        return

    try:
        is_connected = await db.groups_db.is_connected(chat_id_of(chat), fresh=True)
    except Exception as exc:
        log.warning("is_connected check failed for chat=%d: %s", chat_id_of(chat), exc)
        await reply_rich(
            msg,
            t("disconnecting.state.status_failed", locale, plain=True),
            log_label="cmd_tcdisconnect status-check-failed",
            parse_mode=None,
        )
        return
    if not is_connected:
        await reply_rich(
            msg,
            t(
                "disconnecting.state.not_connected",
                locale,
                community=cfg.community_name,
            ),
            log_label="cmd_tcdisconnect not-connected",
            parse_mode=None,
        )
        return

    if not await can_manage_group(ctx.bot, chat_id_of(chat), user.id, fresh=True):
        if is_anon_admin(user):
            msg_text = t("disconnecting.state.anon_admin", locale, plain=True)
        else:
            msg_text = t("disconnecting.state.not_authorized", locale, plain=True)
        await reply_rich(
            msg, msg_text, log_label="cmd_tcdisconnect not-authorized", parse_mode=None
        )
        return

    # * Deactivate first: only leave after the DB confirms, otherwise a
    # * deactivate failure leaves a ghost (bot gone, DB still active).
    try:
        deactivated = await db.groups_db.deactivate_group(chat_id_of(chat))
    except Exception:
        log.exception(
            "deactivate_group failed for chat %d during tcdisconnect", chat_id_of(chat)
        )
        deactivated = False
    if not deactivated:
        await reply_rich(
            msg,
            t("disconnecting.state.deactivate_failed", locale, plain=True),
            log_label="cmd_tcdisconnect deactivate-failed",
            parse_mode=None,
        )
        return
    log_r, reply_r, leave_r = await asyncio.gather(
        send_log(
            ctx.bot,
            messages.group_disconnected_log(
                chat_id_of(chat), chat.title or "Unknown", user.id, display_name(user)
            ),
        ),
        reply_rich(
            msg,
            t(
                "disconnecting.state.disconnected",
                locale,
                community=cfg.community_name,
            ),
            parse_mode=None,
        ),
        ctx.bot.leave_chat(chat_id_of(chat)),
        return_exceptions=True,
    )
    throw_if_cancelled((log_r, reply_r, leave_r))
    if isinstance(log_r, BaseException):
        log.debug(
            "tcdisconnect log send failed for chat %d: %s", chat_id_of(chat), log_r
        )
    if isinstance(reply_r, BaseException):
        log.debug(
            "tcdisconnect reply failed for chat %d: %s", chat_id_of(chat), reply_r
        )
    if isinstance(leave_r, BaseException):
        log.debug(
            "tcdisconnect leave_chat failed for chat %d: %s", chat_id_of(chat), leave_r
        )


# ───────────── Command to Force-Remove a Group </rmtc> ──────────── #


@decorators.ratelimiter(decorators.THROTTLE_MODERATION)
@decorators.staff_only
@decorators.log_execution
async def cmd_rmtc(ctx: Ctx) -> None:
    """Force-remove a group from the federation by chat ID (staff command).

    Parses the numeric chat ID from the command argument, deactivates the group
    record, then fans out a log message, a bot leave, and a confirmation reply
    in parallel.
    """
    locale = await locale_for_update(ctx)
    msg = ctx.effective_message
    admin = ctx.effective_user
    if msg is None or admin is None:
        return
    args = parse_cmd_args(msg.text)
    if not args:
        await reply_rich(
            msg,
            t("disconnecting.state.usage", locale),
            log_label="cmd_rmtc usage",
            parse_mode=None,
        )
        return
    try:
        chat_id = int(args[0])
    except ValueError:
        await reply_rich(
            msg,
            t("disconnecting.state.usage", locale),
            log_label="cmd_rmtc usage",
            parse_mode=None,
        )
        return

    # * The main group is a required destination for ban / unban / mute /
    # * warn fan-out and the federation log channel. It must never be
    # * force-disconnected by /rmtc; the bot would lose
    # * primary-group enforcement and log delivery.
    if cfg.is_primary_group(chat_id):
        await reply_rich(
            msg,
            t("disconnecting.state.primary_refused", locale, plain=True),
            log_label="cmd_rmtc primary-group",
            parse_mode=None,
        )
        return
    # * A legacy connection row must not let /rmtc make the bot leave a
    # * configured log, proof, or appeal destination.
    if cfg.is_infrastructure_chat(chat_id):
        await reply_rich(
            msg,
            t("disconnecting.state.infrastructure_refused", locale, plain=True),
            log_label="cmd_rmtc infrastructure-chat",
            parse_mode=None,
        )
        return

    # * Mirror cmd_tcdisconnect: never leave on an unconfirmed DB write,
    # * and never crash out without a reply on a DB outage.
    try:
        removed = await db.groups_db.deactivate_group(chat_id)
    except Exception:
        log.exception("deactivate_group failed for chat %d during rmtc", chat_id)
        await reply_rich(
            msg,
            t("disconnecting.state.rmtc_failed", locale, plain=True),
            log_label="cmd_rmtc deactivate-failed",
            parse_mode=None,
        )
        return
    if removed:
        # * log, leave, and reply all run in parallel
        log_r, leave_r, reply_r = await asyncio.gather(
            send_log(
                ctx.bot,
                messages.group_disconnected_log(
                    chat_id,
                    str(chat_id),
                    admin.id,
                    display_name(admin),
                ),
            ),
            ctx.bot.leave_chat(chat_id),
            reply_rich(
                msg,
                t(
                    "disconnecting.removed.body",
                    locale,
                    id=Safe(code(str(chat_id))),
                    community=cfg.community_name,
                ),
            ),
            return_exceptions=True,
        )
        throw_if_cancelled((log_r, leave_r, reply_r))
        if isinstance(log_r, BaseException):
            log.debug("rmtc log send failed for chat %d: %s", chat_id, log_r)
        if isinstance(leave_r, BaseException):
            log.debug("rmtc leave_chat failed for chat %d: %s", chat_id, leave_r)
        if isinstance(reply_r, BaseException):
            log.debug("rmtc reply failed for chat %d: %s", chat_id, reply_r)
    else:
        await reply_rich(
            msg,
            replies.err_group_not_found(locale, plain=True),
            log_label="cmd_rmtc not-found",
            parse_mode=None,
        )


# ──────────────────────────── Handlers ──────────────────────────── #

_DISCONNECT_CMDS = build_prefixed_filters("tcdisconnect") | build_prefixed_filters(
    "tcdiscon"
)
_RMTC_CMDS = build_prefixed_filters("rmtc")


__handlers__ = [
    MessageHandler(_DISCONNECT_CMDS, cmd_tcdisconnect),
    MessageHandler(_RMTC_CMDS, cmd_rmtc),
]
