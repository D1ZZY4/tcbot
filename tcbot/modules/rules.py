# © Copyright 2024 - 2026 Transsion Core
# © Copyright 2024 - 2026 Dizzy
# © Copyright 2026 Ave Labs

"""Rules commands: staff editor, public read-only menu, and acknowledgement."""

from __future__ import annotations

from typing import TYPE_CHECKING

from telegram.ext import CallbackQueryHandler, ContextTypes, MessageHandler

from tcbot import cfg
from tcbot import database as db
from tcbot.modules.helper import decorators
from tcbot.modules.helper.buttons import rules as rules_btn
from tcbot.modules.helper.buttons.menus import open_pm_btn
from tcbot.modules.helper.locale import locale_for_update
from tcbot.modules.helper.messages import replies, reply_rich, safe_edit_cb
from tcbot.modules.helper.messages import rich_edit as rich_msg
from tcbot.modules.helper.messages import rules as rules_msg
from tcbot.modules.helper.pipelines.rules_flow import build_rules_conv
from tcbot.utils.i18n import t
from tcbot.utils.logger import get_logger
from tcbot.utils.prefixes import build_prefixed_filters

if TYPE_CHECKING:
    from telegram import Update

log = get_logger(__name__)

__module_name__ = None


def get_help(locale: str | None = None) -> replies.HelpEntry:
    """Return the help entry of the rules module."""
    return replies.module_help(
        locale,
        name=t("button.rules", locale, plain=True),
        overview=t("rules.menu.body", locale, community=cfg.community_name),
        commands="/tcrules, /rules",
        who=replies.perm_staff_only(locale, plain=False),
        where=t("common.context.bot_or_group", locale),
        what=t("rules.menu.rules", locale),
        target=False,
    )


# ─────────────────────────── Commands ─────────────────────────── #


@decorators.ratelimiter(decorators.THROTTLE_READ)
@decorators.log_execution
async def cmd_rules(update: Update, ctx: ContextTypes.DEFAULT_TYPE) -> None:
    """Show the public read-only rules menu."""
    msg = update.effective_message
    if msg is None:
        return
    locale = await locale_for_update(update)
    if update.effective_chat is not None and update.effective_chat.type != "private":
        await reply_rich(
            msg,
            t("rules.editor.open_pm", locale, plain=True),
            parse_mode=None,
            reply_markup=open_pm_btn(ctx.bot.username or "", "menu", locale),
        )
        return
    published = await db.rules_db.published_rules()
    if published is None or not published.get("items"):
        await reply_rich(
            msg, t("rules.menu.empty", locale, plain=True), parse_mode=None
        )
        return
    text = rules_msg.rules_menu(locale, cfg.community_name)
    markup = rules_btn.rules_menu_btn(published["categories"], locale)
    await reply_rich(msg, text, reply_markup=markup)


# ─────────────────────────── Callbacks ─────────────────────────── #


async def _acknowledge(update: Update, ctx: ContextTypes.DEFAULT_TYPE) -> None:
    """Record a member's acceptance of the greeting's rule version."""
    query = update.callback_query
    if query is None or query.data is None:
        return
    parts = query.data.split(":")
    if len(parts) != 3:
        await query.answer()
        return
    try:
        version_id, member_id = int(parts[1]), int(parts[2])
    except ValueError:
        await query.answer()
        return
    user = update.effective_user
    if user is None or user.id != member_id:
        await query.answer(
            t("rules.ack.wrong_member", await locale_for_update(update), plain=True),
            show_alert=True,
        )
        return
    locale = await locale_for_update(update)
    current = await db.rules_db.published_rules()
    if current is None or int(current["version"]["id"]) != version_id:
        await query.answer(t("rules.ack.outdated", locale, plain=True), show_alert=True)
        return
    if not current["set"].get("requires_acknowledgement"):
        await query.answer(t("rules.ack.disabled", locale, plain=True), show_alert=True)
        return
    if await db.rules_db.has_acknowledged(version_id, user.id):
        await query.answer(t("rules.ack.already", locale, plain=True), show_alert=True)
        return
    await db.rules_db.record_acknowledgement(
        version_id,
        user.id,
        getattr(query.message, "chat_id", None),
        None,
    )
    await query.answer(t("rules.ack.recorded", locale, plain=True), show_alert=True)


async def on_rules_show(update: Update, ctx: ContextTypes.DEFAULT_TYPE) -> None:
    """Render one published category in the read-only menu."""
    query = update.callback_query
    if query is None or query.data is None:
        return
    await query.answer()
    key = query.data.split(":", 1)[-1]
    published = await db.rules_db.published_rules()
    if published is None:
        return
    items = [item for item in published["items"] if item["category_key"] == key]
    category = next(
        (cat["title"] for cat in published["categories"] if cat["category_key"] == key),
        key,
    )
    locale = await locale_for_update(update)
    text = rules_msg.category_view(str(category), items, locale)
    markup = rules_btn.category_back_btn()
    message = query.message
    if message is not None and getattr(message, "chat", None) is not None:
        try:
            await rich_msg.edit_rich(
                ctx.bot,
                message.chat.id,
                message.message_id,
                rules_msg.rich_category_view(str(category), items, locale),
                reply_markup=markup,
            )
            return
        except Exception as exc:
            log.debug("Rich category view edit failed: %s", exc)
    await safe_edit_cb(query, text, reply_markup=markup)


async def on_rules_menu(update: Update, ctx: ContextTypes.DEFAULT_TYPE) -> None:
    """Return from a category view to the published menu."""
    query = update.callback_query
    if query is None:
        return
    await query.answer()
    text = rules_msg.rules_menu(await locale_for_update(update), cfg.community_name)
    published = await db.rules_db.published_rules()
    markup = rules_btn.rules_menu_btn(
        published["categories"] if published else [], await locale_for_update(update)
    )
    await safe_edit_cb(query, text, parse_mode=None, reply_markup=markup)


async def on_rules_page(update: Update, ctx: ContextTypes.DEFAULT_TYPE) -> None:
    """Show the next page of the public rules category menu."""
    query = update.callback_query
    if query is None or query.data is None:
        return
    await query.answer()
    try:
        page = int(query.data.split(":", 1)[1])
    except ValueError, IndexError:
        return
    locale = await locale_for_update(update)
    published = await db.rules_db.published_rules()
    markup = rules_btn.rules_menu_btn(
        published["categories"] if published else [], locale, page=page
    )
    await safe_edit_cb(
        query,
        rules_msg.rules_menu(locale, cfg.community_name),
        parse_mode=None,
        reply_markup=markup,
    )


_RULES_CMDS = build_prefixed_filters("rules")

__handlers__ = [
    MessageHandler(_RULES_CMDS, cmd_rules),
    CallbackQueryHandler(_acknowledge, pattern=r"^rules_ack:\d+:\d+$"),
    CallbackQueryHandler(on_rules_show, pattern=r"^rules_show:"),
    CallbackQueryHandler(on_rules_menu, pattern=r"^rules_menu$"),
    CallbackQueryHandler(on_rules_page, pattern=r"^rules_page:\d+$"),
    build_rules_conv(),
]
