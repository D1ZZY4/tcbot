# © Copyright 2024 - 2026 Transsion Core
# © Copyright 2024 - 2026 Dizzy
# © Copyright 2026 Ave Labs

"""About verification step of the group connection steps."""

from __future__ import annotations

import asyncio
import contextlib
from typing import TYPE_CHECKING, Any

from telegram.constants import ChatMemberStatus

from tcbot import cfg
from tcbot.modules.helper.locale import locale_for_update
from tcbot.modules.helper.messages import answer_ack, answer_alert, safe_edit_cb
from tcbot.utils.i18n import t
from tcbot.utils.logger import get_logger
from tcbot.utils.transport import TELEGRAM_LOOKUP_TIMEOUT

if TYPE_CHECKING:
    from telegram import Update
    from telegram.ext import ContextTypes

log = get_logger(__name__)

# * Three membership requirements, one moderation-scope notice, then a final
# * confirmation. The last page reveals the Connect button.
VERIFY_STEPS: int = 5


async def handle_verify_step(
    flow: Any, update: Update, ctx: ContextTypes.DEFAULT_TYPE
) -> None:
    """Advance the About pages shown before a group joins the federation."""
    q = update.callback_query
    chat = update.effective_chat
    user = update.effective_user
    if q is None:
        return
    if chat is None or user is None:
        try:
            await q.answer()
        except Exception as exc:
            log.debug("Verify step answer failed with no chat/user: %s", exc)
        return
    if cfg.is_primary_group(chat.id) or cfg.is_infrastructure_chat(chat.id):
        try:
            await q.answer()
        except Exception as exc:
            log.debug("Verify step infrastructure answer failed: %s", exc)
        return

    locale = await locale_for_update(update)
    try:
        step = int(q.data[len(flow.verify_callback) + 1 :]) if q.data else -1
    except ValueError:
        step = -1
    if step < 1 or step >= VERIFY_STEPS:
        await answer_alert(q, t("about.error.invalid_section", locale, plain=True))
        return

    try:
        membership = await asyncio.wait_for(
            ctx.bot.get_chat_member(chat.id, user.id),
            timeout=TELEGRAM_LOOKUP_TIMEOUT,
        )
    except asyncio.CancelledError:
        raise
    except Exception as exc:
        log.debug("Verify step role check failed: %s", exc)
        await answer_alert(
            q, t("connecting.state.role_check_failed", locale, plain=True)
        )
        return
    if membership.status != ChatMemberStatus.OWNER:
        await answer_alert(q, t("connecting.state.owner_only", locale, plain=True))
        return

    await answer_ack(q)
    with contextlib.suppress(Exception):
        await safe_edit_cb(
            q,
            flow.verify_prompt(step, locale),
            reply_markup=flow.verify_keyboard(step, locale),
        )
