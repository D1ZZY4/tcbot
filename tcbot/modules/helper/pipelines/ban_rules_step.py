# © Copyright 2024 - 2026 Transsion Core
# © Copyright 2024 - 2026 Dizzy
# © Copyright 2026 Ave Labs

"""Rules picker step for the ban conversation.

Ban collects its reason inline, so the picker sits between the command and
the proof prompt. The handlers live outside ``ban_flow`` to keep that module
within the project's file budget.
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Any

from telegram import Update
from telegram.ext import (
    CallbackQueryHandler,
    ContextTypes,
    ConversationHandler,
    MessageHandler,
    filters,
)

from tcbot import database as db
from tcbot.modules.helper.buttons import rules as rules_btn
from tcbot.modules.helper.locale import locale_for_update
from tcbot.modules.helper.messages import (
    reply_rich,
    reply_rich_result,
    safe_edit_cb,
)
from tcbot.modules.helper.pipelines import rules_step
from tcbot.modules.helper.pipelines.ban_confirmation import stale_ban_callback
from tcbot.modules.helper.pipelines.ban_flow import (
    BAN_USER_DATA_KEYS,
    WAITING_PROOF,
    on_cancel_proof,
    proof_prompt_content,
)
from tcbot.modules.helper.pipelines.reason_flow import MAX_RULES_NOTE_LEN
from tcbot.modules.helper.scope import flow_scope
from tcbot.utils.i18n import t
from tcbot.utils.logger import get_logger
from tcbot.utils.prefixes import ALL_PREFIXES_CMD_FILTER

if TYPE_CHECKING:
    from telegram import InlineKeyboardMarkup

log = get_logger(__name__)

WAITING_BAN_RULES = 2
WAITING_BAN_RULES_NOTE = 3


async def _items() -> list[dict[str, Any]]:
    published = await db.rules_db.published_rules()
    return published["items"] if published else []


async def _render(update: Update, ctx: ContextTypes.DEFAULT_TYPE) -> int:
    q = update.callback_query
    scope = flow_scope(ctx, update)
    selected: list[int] = scope.get("ban_rules", [])
    locale = await locale_for_update(update)
    items = await _items()
    # * Record the prompt identity from this first interactive step. Without
    # * it a stale Cancel on an older ban prompt still looks current here and
    # * cancels the newer ban before proof collection starts.
    if q is not None:
        try:
            await safe_edit_cb(
                q,
                rules_step.picker_text(items, selected, locale),
                reply_markup=rules_btn.picker_btn(items, selected, locale),
            )
            if q.message is not None:
                scope["ban_prompt_msg_id"] = q.message.message_id
                scope["ban_prompt_chat_id"] = q.message.chat.id
        except Exception as exc:
            log.debug("Ban rules picker edit failed: %s", exc)
    elif update.effective_message is not None:
        try:
            sent = await reply_rich_result(
                update.effective_message,
                rules_step.picker_text(items, selected, locale),
                reply_markup=rules_btn.picker_btn(items, selected, locale),
            )
            scope["ban_prompt_msg_id"] = sent.message_id
            scope["ban_prompt_chat_id"] = update.effective_message.chat.id
        except Exception as exc:
            log.debug("Ban rules picker reply failed: %s", exc)
    return WAITING_BAN_RULES


async def show_ban_rules(update: Update, ctx: ContextTypes.DEFAULT_TYPE) -> int:
    """Show the picker, or go straight to proof when no rules are published."""
    scope = flow_scope(ctx, update)
    scope["ban_rules"] = []
    uid = update.effective_user.id if update.effective_user else 0
    try:
        may_pick = await db.users_roles.has_permission(uid, "rules.view")
    except Exception as exc:
        log.warning("rules.view lookup failed for %d: %s", uid, exc)
        may_pick = False
    if not may_pick or not await _items():
        return await _show_proof(update, ctx)
    return await _render(update, ctx)


async def _show_proof(update: Update, ctx: ContextTypes.DEFAULT_TYPE) -> int:
    scope = flow_scope(ctx, update)
    text, btn = proof_prompt_content(
        int(scope.get("ban_target_id", 0) or 0),
        str(scope.get("ban_target_fname") or ""),
        str(scope.get("ban_reason") or ""),
        scope.get("ban_locale"),
    )
    markup: InlineKeyboardMarkup = btn
    q = update.callback_query
    try:
        if q is not None:
            await safe_edit_cb(q, text, reply_markup=markup)
            if q.message is not None:
                scope["ban_prompt_msg_id"] = q.message.message_id
                scope["ban_prompt_chat_id"] = q.message.chat.id
        elif update.effective_message is not None:
            sent = await reply_rich_result(
                update.effective_message, text, reply_markup=markup
            )
            scope["ban_prompt_msg_id"] = sent.message_id
            scope["ban_prompt_chat_id"] = update.effective_message.chat.id
    except Exception as exc:
        log.debug("Ban proof prompt after rules failed: %s", exc)
        for key in BAN_USER_DATA_KEYS:
            scope.pop(key, None)
        return ConversationHandler.END
    return WAITING_PROOF


async def on_ban_rules_toggle(
    update: Update, ctx: ContextTypes.DEFAULT_TYPE
) -> int | None:
    """Toggle one rule and redraw the picker."""
    q = update.callback_query
    if q is None or q.data is None:
        return WAITING_BAN_RULES
    if await stale_ban_callback(update, ctx):
        return None
    item_id = rules_step.item_id_from_callback(q.data)
    scope = flow_scope(ctx, update)
    if item_id is not None:
        scope["ban_rules"] = rules_step.toggle(scope.get("ban_rules", []), item_id)
    await q.answer()
    return await _render(update, ctx)


async def on_ban_rules_clear(
    update: Update, ctx: ContextTypes.DEFAULT_TYPE
) -> int | None:
    """Clear the current selection."""
    q = update.callback_query
    if q is None:
        return WAITING_BAN_RULES
    if await stale_ban_callback(update, ctx):
        return None
    flow_scope(ctx, update)["ban_rules"] = []
    await q.answer()
    return await _render(update, ctx)


async def on_ban_rules_done(
    update: Update, ctx: ContextTypes.DEFAULT_TYPE
) -> int | None:
    """Accept a selection and continue to proof."""
    q = update.callback_query
    if q is None:
        return WAITING_BAN_RULES
    scope = flow_scope(ctx, update)
    if await stale_ban_callback(update, ctx):
        return None
    if not scope.get("ban_rules") and not scope.get("ban_rules_note"):
        await q.answer(
            t(
                "rules.picker.require_selection",
                await locale_for_update(update),
                plain=True,
            ),
            show_alert=True,
        )
        return WAITING_BAN_RULES
    await q.answer()
    return await _show_proof(update, ctx)


async def on_ban_rules_other(
    update: Update, ctx: ContextTypes.DEFAULT_TYPE
) -> int | None:
    """Ask for the optional Other note."""
    q = update.callback_query
    if q is None:
        return WAITING_BAN_RULES
    if await stale_ban_callback(update, ctx):
        return None
    await q.answer()
    if update.effective_message is not None:
        await reply_rich(
            update.effective_message,
            t("rules.picker.ask_note", await locale_for_update(update), plain=True),
            parse_mode=None,
        )
    return WAITING_BAN_RULES_NOTE


async def on_ban_rules_note(update: Update, ctx: ContextTypes.DEFAULT_TYPE) -> int:
    """Store the note and continue to proof."""
    msg = update.effective_message
    if msg is None or not msg.text:
        return WAITING_BAN_RULES_NOTE
    note = msg.text.strip()
    if not note or len(note) > MAX_RULES_NOTE_LEN:
        await reply_rich(
            msg,
            t(
                "rules.picker.bad_note",
                await locale_for_update(update),
                limit=MAX_RULES_NOTE_LEN,
                plain=True,
            ),
            parse_mode=None,
        )
        return WAITING_BAN_RULES_NOTE
    flow_scope(ctx, update)["ban_rules_note"] = note
    return await _show_proof(update, ctx)


BAN_RULES_STATES: dict[int, list[Any]] = {
    WAITING_BAN_RULES: [
        CallbackQueryHandler(on_ban_rules_toggle, pattern=r"^rules_step:pick:\d+$"),
        CallbackQueryHandler(on_ban_rules_done, pattern=r"^rules_step:done$"),
        CallbackQueryHandler(on_ban_rules_other, pattern=r"^rules_step:other$"),
        CallbackQueryHandler(on_ban_rules_clear, pattern=r"^rules_step:clear$"),
        CallbackQueryHandler(on_cancel_proof, pattern=r"^rules_step:cancel$"),
    ],
    WAITING_BAN_RULES_NOTE: [
        MessageHandler(filters.TEXT & ~ALL_PREFIXES_CMD_FILTER, on_ban_rules_note),
        # * The picker's Cancel button stays visible after "Other".
        CallbackQueryHandler(on_cancel_proof, pattern=r"^rules_step:cancel$"),
    ],
}
