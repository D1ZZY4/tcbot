# © Copyright 2024 - 2026 Transsion Core
# © Copyright 2024 - 2026 Dizzy
# © Copyright 2026 Ave Labs

"""Fresh-ban proof prompt: renders the evidence step and records its identity.

The prompt identity is the replay guard for every ban callback. It used to be
recorded by the removed rules picker; keeping it here preserves stale-tap
protection on the direct reason-to-proof path.
"""

from __future__ import annotations

from typing import TYPE_CHECKING

from tcbot.modules.helper.context import Ctx, chat_id_of
from tcbot.modules.helper.handlers import ConversationHandler
from tcbot.modules.helper.messages import reply_rich_result, safe_edit_cb
from tcbot.modules.helper.pipelines.ban_session import BAN_USER_DATA_KEYS, WAITING_PROOF
from tcbot.modules.helper.pipelines.proof_steps import proof_prompt_content
from tcbot.modules.helper.scope import flow_scope
from tcbot.utils.logger import get_logger

if TYPE_CHECKING:
    from pyrogram.types import InlineKeyboardMarkup

log = get_logger(__name__)


async def show_ban_proof(ctx: Ctx) -> int:
    """Render the ban proof prompt and record the live prompt identity."""
    scope = flow_scope(ctx)
    target_id = int(scope.get("ban_target_id", 0) or 0)
    # * Flat-registered handlers reach this without an active flow. A missing
    # * target must never render a "Banning 0" prompt that looks actionable.
    if target_id <= 0:
        for key in BAN_USER_DATA_KEYS:
            scope.pop(key, None)
        return ConversationHandler.END
    text, button = proof_prompt_content(
        target_id,
        str(scope.get("ban_target_fname") or ""),
        str(scope.get("ban_reason") or ""),
        scope.get("ban_locale"),
    )
    markup: InlineKeyboardMarkup = button
    query = ctx.callback_query
    try:
        if query is not None:
            await safe_edit_cb(query, text, reply_markup=markup)
            if query.message is not None:
                scope["ban_prompt_msg_id"] = query.message.id
                scope["ban_prompt_chat_id"] = chat_id_of(query.message.chat)
        elif ctx.effective_message is not None:
            sent = await reply_rich_result(
                ctx.effective_message, text, reply_markup=markup
            )
            scope["ban_prompt_msg_id"] = sent.id
            scope["ban_prompt_chat_id"] = chat_id_of(ctx.effective_message.chat)
    except Exception as exc:
        log.debug("Ban proof prompt failed: %s", exc)
        for key in BAN_USER_DATA_KEYS:
            scope.pop(key, None)
        return ConversationHandler.END
    return WAITING_PROOF
