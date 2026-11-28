# © Copyright 2024 - 2026 Transsion Core
# © Copyright 2024 - 2026 Dizzy
# © Copyright 2026 Ave Labs

"""Broadcast command handler: sends a message to all connected groups."""

from __future__ import annotations

import asyncio

from tcbot import cfg
from tcbot import database as db
from tcbot.database.documents import GroupDoc
from tcbot.modules.helper import decorators, guards, messages
from tcbot.modules.helper.context import Ctx, chat_id_of, display_name
from tcbot.modules.helper.handlers import MessageHandler
from tcbot.modules.helper.locale import locale_for_update
from tcbot.modules.helper.messages import (
    forward_rich,
    replies,
    reply_rich,
    reply_rich_result,
    safe_edit,
    send_log,
    send_text,
)
from tcbot.utils import circuit_breaker as _cb
from tcbot.utils.circuit_breaker import CircuitState
from tcbot.utils.dispatch import fan_out, throw_if_cancelled
from tcbot.utils.i18n import Safe, code, esc, t
from tcbot.utils.logger import get_logger
from tcbot.utils.prefixes import build_prefixed_filters, parse_cmd_args

log = get_logger(__name__)


# ────────────────────── Module & Help Message ───────────────────── #

__module_name__ = "Broadcast"


def get_help(locale: str | None = None) -> replies.HelpEntry:
    """Build this module's help entry in the given locale."""
    return replies.module_help(
        locale,
        name=__module_name__,
        overview=t("broadcasting.help.overview", locale, community=cfg.community_name),
        commands=t("broadcasting.help.commands.body", locale),
        who=replies.perm_staff_only(locale, plain=False),
        where=replies.context_bot_or_group(locale),
        what=t("broadcasting.help.what.body", locale, community=cfg.community_name),
        target=False,
        examples=t("broadcasting.help.examples.body", locale),
    )


__help__: replies.HelpEntry = get_help()


# ──────────────── Command Broadcast </tcbroadcast> ──────────────── #


@decorators.ratelimiter(decorators.THROTTLE_FEDERATION)
@decorators.staff_only
@decorators.log_execution
async def cmd_broadcast(ctx: Ctx) -> None:
    """Send a message or forward a replied-to message to all connected groups.

    Accepts an inline text argument or a reply-to-message. Fans out sends to
    every active group via ``fan_out`` with semaphore limiting. Logs the result
    and edits the status message in parallel.
    """
    locale = await locale_for_update(ctx)
    msg = ctx.effective_message
    admin = ctx.effective_user
    if msg is None or admin is None or msg.chat is None:
        return
    if not await guards.require_federation_origin(
        msg,
        chat_id=chat_id_of(msg.chat),
        chat_type=msg.chat.type,
        locale=locale,
        allow_private=True,
        log_label="cmd_broadcast origin",
    ):
        return

    # * fan_out runs its slots concurrently. A circuit that is OPEN or already
    # * holding a HALF_OPEN probe would deliver to only part of the federation
    # * and report the rest as failed, with no durable retry for a broadcast.
    # * Refuse up front so staff get a clear retry instead of a silent split.
    state = _cb.telegram.state
    if state is not CircuitState.CLOSED:
        log.warning("Broadcast skipped: Telegram circuit is %s.", state.value)
        await reply_rich(
            msg,
            t("broadcasting.send.circuit_busy", locale, plain=True),
            log_label="cmd_broadcast circuit",
            parse_mode=None,
        )
        return

    args = parse_cmd_args(msg.text)
    broadcast_text: str | None = " ".join(args).strip() if args else None

    has_reply = bool(msg.reply_to_message)
    if not broadcast_text and not has_reply:
        await reply_rich(
            msg,
            t("broadcasting.send.no_content", locale),
            log_label="cmd_broadcast no-content",
        )
        return

    try:
        groups = await db.groups_db.active_groups()
    except Exception:
        log.exception("active_groups failed during broadcast")
        await reply_rich(
            msg,
            replies.err_groups_load_failed(locale, plain=False),
            log_label="cmd_broadcast groups-failed",
        )
        return
    if not groups:
        await reply_rich(
            msg,
            replies.err_no_connected_groups(locale, plain=False),
            log_label="cmd_broadcast no-groups",
        )
        return

    status = None
    try:
        status = await reply_rich_result(
            msg,
            t("broadcasting.send.sending", locale, n=len(groups), plain=True),
        )
    except Exception as exc:
        log.debug("cmd_broadcast status reply failed: %s", exc)

    # * Build per-group send coroutines, then fan out with semaphore limiting.
    # * Staff text is untrusted plain text and stays unparsed: interpreting it
    # * as rich HTML would let a broadcast inject markup into every group.
    async def _send_one(grp: GroupDoc) -> None:
        chat_id = grp.get("chat_id")
        if chat_id is None:
            return
        if has_reply and msg.reply_to_message:
            await forward_rich(msg.reply_to_message, chat_id)
        elif broadcast_text:
            # * Staff text is untrusted, so escape it before the rich transport;
            # * the rendered HTML then shows the literal text in every group.
            await send_text(ctx.bot, chat_id, esc(broadcast_text))

    results = await fan_out([_send_one(grp) for grp in groups])
    # * Every refusal is a lost delivery here. Unlike moderation, where a
    # * benign refusal means "nothing to enforce", a broadcast promises the
    # * message reached the group, so CHAT_NOT_FOUND must be reported as failed.
    failed = sum(isinstance(result, BaseException) for result in results)
    success = len(results) - failed

    for grp, r in zip(groups, results, strict=True):
        if isinstance(r, BaseException):
            log.warning("Broadcast failed for %d: %s", grp.get("chat_id", "?"), r)

    if broadcast_text:
        preview = broadcast_text
    elif msg.reply_to_message:
        preview = msg.reply_to_message.text or "media"
    else:
        preview = ""

    # * send log and ctx status message in parallel
    log_coro = send_log(
        ctx.bot,
        messages.broadcast_log(admin.id, display_name(admin), preview, success, failed),
    )
    if status is not None:
        edit_r, log_r = await asyncio.gather(
            safe_edit(
                status,
                t(
                    "broadcasting.send.done",
                    locale,
                    ok=Safe(code(str(success))),
                    failed=Safe(code(str(failed))),
                ),
            ),
            log_coro,
            return_exceptions=True,
        )
        throw_if_cancelled((edit_r, log_r))
    else:
        edit_r = None
        (log_r,) = await asyncio.gather(log_coro, return_exceptions=True)
        throw_if_cancelled((log_r,))
    if isinstance(edit_r, BaseException):
        log.debug("Broadcast status edit failed: %s", edit_r)
    if isinstance(log_r, BaseException):
        log.error("Broadcast log send failed: %s", log_r, exc_info=log_r)


# ──────────────────────────── Handlers ──────────────────────────── #

_BROADCAST_CMDS = build_prefixed_filters("tcbroadcast") | build_prefixed_filters("bc")

__handlers__ = [MessageHandler(_BROADCAST_CMDS, cmd_broadcast)]
