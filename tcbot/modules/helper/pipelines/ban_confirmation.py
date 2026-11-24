# © Copyright 2024 - 2026 Transsion Core
# © Copyright 2024 - 2026 Dizzy
# © Copyright 2026 Ave Labs

"""Freshness guard and re-ban confirmation for the ban conversation."""

from __future__ import annotations

from pyrogram.types import Message

from tcbot.modules.helper import guards
from tcbot.modules.helper.context import Ctx
from tcbot.modules.helper.handlers import ConversationHandler
from tcbot.modules.helper.scope import callback_is_current, flow_scope
from tcbot.utils.logger import get_logger

log = get_logger(__name__)


async def stale_ban_callback(ctx: Ctx) -> bool:
    """Answer and report a tap that did not come from the live ban prompt.

    A ConversationHandler keys a dialogue by (chat, user), so a button left
    on an older ban prompt can be delivered to a newer ban. The prompt
    identity recorded at entry decides which taps are current.
    """
    if callback_is_current(
        ctx,
        flow_scope(ctx),
        chat_key="ban_prompt_chat_id",
        message_key="ban_prompt_msg_id",
    ):
        return False
    query = ctx.callback_query
    if query is not None:
        try:
            await query.answer()
        except Exception as exc:
            log.debug("Ban stale callback answer failed: %s", exc)
    return True


async def on_ban_update_continue(ctx: Ctx) -> int | None:
    """Proceed from the re-ban confirmation to proof collection."""
    q = ctx.callback_query
    msg = ctx.effective_message
    if q is None or msg is None or ctx.user_data is None:
        return ConversationHandler.END
    if await stale_ban_callback(ctx):
        return None
    scope = flow_scope(ctx)
    if not isinstance(msg, Message):
        for key in _ban_keys():
            scope.pop(key, None)
        return ConversationHandler.END
    await q.answer()
    tapper = ctx.effective_user
    if tapper is None or not await guards.recheck_executor_rank(
        msg, tapper.id, min_role="developer"
    ):
        for key in _ban_keys():
            scope.pop(key, None)
        return ConversationHandler.END
    target_id = int(scope.get("ban_target_id", 0) or 0)
    reason = str(scope.get("ban_reason") or "")
    if not target_id or not reason:
        return ConversationHandler.END
    # * The demote runs at enforcement time while the proof step stays
    # * cancelable. Late import avoids a cycle with the rules step.
    from tcbot.modules.helper.pipelines.ban_rules_step import show_ban_rules  # noqa: PLC0415

    return await show_ban_rules(ctx)


def _ban_keys() -> tuple[str, ...]:
    """Return the ban payload keys; imported late to avoid a module cycle."""
    from tcbot.modules.helper.pipelines.ban_actions import BAN_USER_DATA_KEYS  # noqa: PLC0415

    return BAN_USER_DATA_KEYS
