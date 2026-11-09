# © Copyright 2024 - 2026 Transsion Core
# © Copyright 2024 - 2026 Dizzy
# © Copyright 2026 Ave Labs

"""Main-group appeal entry point for the appeal submission flow."""

from __future__ import annotations

import re
from typing import TYPE_CHECKING

from tcbot import database as db
from tcbot.modules.helper.parse_editmsg import safe_reply
from tcbot.modules.helper.workflows import appeal_submit_flow as flow_pkg
from tcbot.modules.helper.workflows.appeal_submit_flow.gates import (
    WAITING_APPEAL,
    _clear_appeal_state,
    starts_with_appeal_tag,
)
from tcbot.utils.i18n import t
from tcbot.utils.logger import get_logger

if TYPE_CHECKING:
    from collections.abc import Awaitable, Callable

    from telegram import Update
    from telegram.ext import ContextTypes

log = get_logger(__name__)


async def handle_group_appeal(
    update: Update,
    ctx: ContextTypes.DEFAULT_TYPE,
    on_message: Callable[..., Awaitable[int]],
) -> None:
    """Handle ``#appeal`` in the main group through the DM submit path.

    The active ban is looked up by sender; an explicit 10-char ban id
    in the text must match it. Other chats return silently so the tag
    stays a no-op outside MAIN_GROUP.
    """
    msg = update.effective_message
    user = update.effective_user
    chat = update.effective_chat
    if msg is None or user is None or msg.text is None or chat is None:
        return
    if chat.id != flow_pkg.cfg.main_group or not chat.id:
        return
    text = msg.text.strip()
    if not starts_with_appeal_tag(text):
        return
    locale = await flow_pkg.locale_for_update(update)
    try:
        ban = await db.bans_db.get_active_ban(user.id)
    except Exception:
        log.exception("Appeal group lookup failed for user=%d", user.id)
        ban = None
    bid = str(ban.get("ban_id", "")) if ban else ""
    if not ban or not bid:
        await safe_reply(
            msg,
            t("appeals.submit.invalid_link", locale, plain=True),
            log_label="Appeal group no-ban",
            parse_mode=None,
        )
        return
    mentioned = re.search(r"\b([a-z0-9]{10})\b", text)
    if mentioned and mentioned.group(1) != bid:
        await safe_reply(
            msg,
            t("appeals.submit.invalid_link", locale, plain=True),
            log_label="Appeal group id-mismatch",
            parse_mode=None,
        )
        return
    if ctx.user_data is None:
        return
    ctx.user_data["appeal_ban_id"] = bid
    ctx.user_data["appeal_log_msg_id"] = ban.get("log_message_id", 0)
    result = await on_message(update, ctx)
    if result != WAITING_APPEAL:
        _clear_appeal_state(ctx.user_data)
