# © Copyright 2024 - 2026 Transsion Core
# © Copyright 2024 - 2026 Dizzy
# © Copyright 2026 Ave Labs

"""Rules picker step for the ban conversation.

Ban collects its reason inline, so the picker sits between the command and
the proof prompt. The handlers live outside ``ban_actions`` to keep that module
within the project's file budget.
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Any

from pyrogram import filters

from tcbot import database as db
from tcbot.modules.helper.buttons import rules as rules_btn
from tcbot.modules.helper.context import Ctx, chat_id_of
from tcbot.modules.helper.handlers import (
    CallbackQueryHandler,
    ConversationHandler,
    MessageHandler,
)
from tcbot.modules.helper.locale import locale_for_update
from tcbot.modules.helper.messages import (
    reply_rich,
    reply_rich_result,
    safe_edit_cb,
)
from tcbot.modules.helper.pipelines import rules_picker
from tcbot.modules.helper.pipelines.ban_actions import (
    BAN_USER_DATA_KEYS,
    WAITING_PROOF,
    on_cancel_proof,
)
from tcbot.modules.helper.pipelines.ban_confirmation import stale_ban_callback
from tcbot.modules.helper.pipelines.mod_action_steps import MAX_RULES_NOTE_LEN
from tcbot.modules.helper.pipelines.proof_steps import proof_prompt_content
from tcbot.modules.helper.rich.edit import callback_text_of
from tcbot.modules.helper.scope import flow_scope
from tcbot.utils.i18n import t
from tcbot.utils.logger import get_logger
from tcbot.utils.prefixes import ALL_PREFIXES_CMD_FILTER

if TYPE_CHECKING:
    from pyrogram.types import InlineKeyboardMarkup

log = get_logger(__name__)

WAITING_BAN_RULES = 2
WAITING_BAN_RULES_NOTE = 3


async def _items() -> list[dict[str, Any]]:
    published = await db.rules_db.published_rules()
    return published["items"] if published else []


async def _render(ctx: Ctx) -> int:
    q = ctx.callback_query
    scope = flow_scope(ctx)
    selected: list[int] = scope.get("ban_rules", [])
    locale = await locale_for_update(ctx)
    items = await _items()
    # * Record the prompt identity from this first interactive step. Without
    # * it a stale Cancel on an older ban prompt still looks current here and
    # * cancels the newer ban before proof collection starts.
    if q is not None:
        try:
            await safe_edit_cb(
                q,
                rules_picker.picker_text(items, selected, locale),
                reply_markup=rules_btn.picker_btn(items, selected, locale),
            )
            if q.message is not None:
                scope["ban_prompt_msg_id"] = q.message.id
                scope["ban_prompt_chat_id"] = chat_id_of(q.message.chat)
        except Exception as exc:
            log.debug("Ban rules picker edit failed: %s", exc)
    elif ctx.effective_message is not None:
        try:
            sent = await reply_rich_result(
                ctx.effective_message,
                rules_picker.picker_text(items, selected, locale),
                reply_markup=rules_btn.picker_btn(items, selected, locale),
            )
            scope["ban_prompt_msg_id"] = sent.id
            scope["ban_prompt_chat_id"] = chat_id_of(ctx.effective_message.chat)
        except Exception as exc:
            log.debug("Ban rules picker reply failed: %s", exc)
    return WAITING_BAN_RULES


async def show_ban_rules(ctx: Ctx) -> int:
    """Show the picker, or go straight to proof when no rules are published."""
    scope = flow_scope(ctx)
    scope["ban_rules"] = []
    uid = ctx.effective_user.id if ctx.effective_user else 0
    try:
        may_pick = await db.users_roles.has_permission(uid, "rules.view")
    except Exception as exc:
        log.warning("rules.view lookup failed for %d: %s", uid, exc)
        may_pick = False
    if not may_pick or not await _items():
        return await _show_proof(ctx)
    return await _render(ctx)


async def _show_proof(ctx: Ctx) -> int:
    scope = flow_scope(ctx)
    text, btn = proof_prompt_content(
        int(scope.get("ban_target_id", 0) or 0),
        str(scope.get("ban_target_fname") or ""),
        str(scope.get("ban_reason") or ""),
        scope.get("ban_locale"),
    )
    markup: InlineKeyboardMarkup = btn
    q = ctx.callback_query
    try:
        if q is not None:
            await safe_edit_cb(q, text, reply_markup=markup)
            if q.message is not None:
                scope["ban_prompt_msg_id"] = q.message.id
                scope["ban_prompt_chat_id"] = chat_id_of(q.message.chat)
        elif ctx.effective_message is not None:
            sent = await reply_rich_result(
                ctx.effective_message, text, reply_markup=markup
            )
            scope["ban_prompt_msg_id"] = sent.id
            scope["ban_prompt_chat_id"] = chat_id_of(ctx.effective_message.chat)
    except Exception as exc:
        log.debug("Ban proof prompt after rules failed: %s", exc)
        for key in BAN_USER_DATA_KEYS:
            scope.pop(key, None)
        return ConversationHandler.END
    return WAITING_PROOF


async def on_ban_rules_toggle(ctx: Ctx) -> int | None:
    """Toggle one rule and redraw the picker."""
    q = ctx.callback_query
    if q is None or q.data is None:
        return WAITING_BAN_RULES
    if await stale_ban_callback(ctx):
        return None
    item_id = rules_picker.item_id_from_callback(callback_text_of(q))
    scope = flow_scope(ctx)
    if item_id is not None:
        scope["ban_rules"] = rules_picker.toggle(scope.get("ban_rules", []), item_id)
    await q.answer()
    return await _render(ctx)


async def on_ban_rules_clear(ctx: Ctx) -> int | None:
    """Clear the current selection."""
    q = ctx.callback_query
    if q is None:
        return WAITING_BAN_RULES
    if await stale_ban_callback(ctx):
        return None
    flow_scope(ctx)["ban_rules"] = []
    await q.answer()
    return await _render(ctx)


async def on_ban_rules_done(ctx: Ctx) -> int | None:
    """Accept a selection and continue to proof."""
    q = ctx.callback_query
    if q is None:
        return WAITING_BAN_RULES
    scope = flow_scope(ctx)
    if await stale_ban_callback(ctx):
        return None
    if not scope.get("ban_rules") and not scope.get("ban_rules_note"):
        await q.answer(
            t(
                "rules.picker.require_selection",
                await locale_for_update(ctx),
                plain=True,
            ),
            show_alert=True,
        )
        return WAITING_BAN_RULES
    await q.answer()
    return await _show_proof(ctx)


async def on_ban_rules_other(ctx: Ctx) -> int | None:
    """Ask for the optional Other note."""
    q = ctx.callback_query
    if q is None:
        return WAITING_BAN_RULES
    if await stale_ban_callback(ctx):
        return None
    await q.answer()
    if ctx.effective_message is not None:
        await reply_rich(
            ctx.effective_message,
            t("rules.picker.ask_note", await locale_for_update(ctx), plain=True),
            parse_mode=None,
        )
    return WAITING_BAN_RULES_NOTE


async def on_ban_rules_note(ctx: Ctx) -> int:
    """Store the note and continue to proof."""
    msg = ctx.effective_message
    if msg is None or not msg.text:
        return WAITING_BAN_RULES_NOTE
    note = msg.text.strip()
    if not note or len(note) > MAX_RULES_NOTE_LEN:
        await reply_rich(
            msg,
            t(
                "rules.picker.bad_note",
                await locale_for_update(ctx),
                limit=MAX_RULES_NOTE_LEN,
                plain=True,
            ),
            parse_mode=None,
        )
        return WAITING_BAN_RULES_NOTE
    flow_scope(ctx)["ban_rules_note"] = note
    return await _show_proof(ctx)


BAN_RULES_STATES: dict[int, list[Any]] = {
    WAITING_BAN_RULES: [
        CallbackQueryHandler(on_ban_rules_toggle, pattern=r"^rules_step:pick:\d+$"),
        CallbackQueryHandler(on_ban_rules_done, pattern=r"^rules_step:done$"),
        CallbackQueryHandler(on_ban_rules_other, pattern=r"^rules_step:other$"),
        CallbackQueryHandler(on_ban_rules_clear, pattern=r"^rules_step:clear$"),
        CallbackQueryHandler(on_cancel_proof, pattern=r"^rules_step:cancel$"),
    ],
    WAITING_BAN_RULES_NOTE: [
        MessageHandler(filters.text & ~ALL_PREFIXES_CMD_FILTER, on_ban_rules_note),
        # * The picker's Cancel button stays visible after "Other".
        CallbackQueryHandler(on_cancel_proof, pattern=r"^rules_step:cancel$"),
    ],
}
