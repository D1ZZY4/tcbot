# © Copyright 2024 - 2026 Transsion Core
# © Copyright 2024 - 2026 Dizzy
# © Copyright 2026 Ave Labs

"""Rules commands: staff editor, public read-only menu, and acknowledgement."""

from __future__ import annotations

from typing import TYPE_CHECKING, Any, cast

from telegram.ext import CallbackQueryHandler, CommandHandler, ContextTypes

from tcbot import cfg
from tcbot import database as db
from tcbot.modules.helper import decorators
from tcbot.modules.helper.keyboards import rules as rules_kb
from tcbot.modules.helper.locale import locale_for_update
from tcbot.modules.helper.messages import replies, safe_edit_cb, safe_reply
from tcbot.modules.helper.messages import rules as rules_msg
from tcbot.modules.helper.pipelines.rules_flow import (
    WAITING_CATEGORY_TITLE,
    build_rules_conv,
    editor_allowed,
    refuse_editor,
)
from tcbot.modules.helper.pipelines.rules_publish import publish_rules
from tcbot.modules.helper.scope import flow_scope
from tcbot.utils.i18n import t
from tcbot.utils.logger import get_logger

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
        who=t("common.perm.staff_only", locale, plain=True),
        where=t("common.context.bot_or_group", locale),
        what=t("rules.menu.rules", locale, plain=True),
        target=False,
    )


# ─────────────────────────── Commands ─────────────────────────── #


@decorators.ratelimiter(decorators.THROTTLE_STAFF)
@decorators.permission_only("rules.manage")
@decorators.log_execution
async def cmd_tcrules(update: Update, ctx: ContextTypes.DEFAULT_TYPE) -> None:
    """Open the rules editor in the user's private chat."""
    msg = update.effective_message
    user = update.effective_user
    if msg is None or user is None:
        return
    locale = await locale_for_update(update)
    if update.effective_chat is not None and update.effective_chat.type != "private":
        await safe_reply(
            msg,
            t("rules.editor.open_pm", locale, plain=True),
            parse_mode=None,
        )
        return
    rule_set = await db.rules_db.get_or_create_community_set()
    panel = await db.rules_db.open_draft(int(rule_set["id"]), user.id)
    text = await rules_msg.editor_panel(rule_set, panel, locale)
    await safe_reply(msg, text, reply_markup=rules_kb.editor_panel_kb(locale))


@decorators.ratelimiter(decorators.THROTTLE_READ)
@decorators.log_execution
async def cmd_rules(update: Update, ctx: ContextTypes.DEFAULT_TYPE) -> None:
    """Show the public read-only rules menu."""
    msg = update.effective_message
    if msg is None:
        return
    locale = await locale_for_update(update)
    if update.effective_chat is not None and update.effective_chat.type != "private":
        await safe_reply(
            msg,
            t("rules.editor.open_pm", locale, plain=True),
            parse_mode=None,
        )
        return
    published = await db.rules_db.published_rules()
    if published is None or not published.get("items"):
        await safe_reply(
            msg, t("rules.menu.empty", locale, plain=True), parse_mode=None
        )
        return
    text = rules_msg.rules_menu(locale, cfg.community_name)
    markup = rules_kb.rules_menu_kb(published["categories"], locale)
    await safe_reply(msg, text, reply_markup=markup)


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
            t("rules.ack.wrong_member", None, plain=True), show_alert=True
        )
        return
    current = await db.rules_db.published_rules()
    if current is None or int(current["version"]["id"]) != version_id:
        await query.answer(t("rules.ack.outdated", None, plain=True), show_alert=True)
        return
    if not current["set"].get("requires_acknowledgement"):
        await query.answer(t("rules.ack.disabled", None, plain=True), show_alert=True)
        return
    if await db.rules_db.has_acknowledged(version_id, user.id):
        await query.answer(t("rules.ack.already", None, plain=True), show_alert=True)
        return
    await db.rules_db.record_acknowledgement(
        version_id,
        user.id,
        getattr(query.message, "chat_id", None),
        None,
    )
    await query.answer(t("rules.ack.recorded", None, plain=True), show_alert=True)


async def on_rules_show(update: Update, ctx: ContextTypes.DEFAULT_TYPE) -> None:
    """Render one published category in the read-only menu."""
    query = update.callback_query
    if query is None or query.data is None:
        return
    key = query.data.split(":", 1)[-1]
    published = await db.rules_db.published_rules()
    if published is None:
        await query.answer()
        return
    items = [item for item in published["items"] if item["category_key"] == key]
    category = next(
        (cat["title"] for cat in published["categories"] if cat["category_key"] == key),
        key,
    )
    text = rules_msg.category_view(
        str(category), items, await locale_for_update(update)
    )
    await safe_edit_cb(
        query, text, parse_mode="MarkdownV2", reply_markup=rules_kb.category_back_kb()
    )


async def on_rules_menu(update: Update, ctx: ContextTypes.DEFAULT_TYPE) -> None:
    """Return from a category view to the published menu."""
    query = update.callback_query
    if query is None:
        return
    text = rules_msg.rules_menu(await locale_for_update(update), cfg.community_name)
    published = await db.rules_db.published_rules()
    markup = rules_kb.rules_menu_kb(
        published["categories"] if published else [], await locale_for_update(update)
    )
    await safe_edit_cb(query, text, parse_mode="MarkdownV2", reply_markup=markup)


async def on_rules_panel(update: Update, ctx: ContextTypes.DEFAULT_TYPE) -> None:
    """Reopen the editor panel from a sub-menu."""
    query = update.callback_query
    if query is None:
        return
    if not await editor_allowed(update):
        await refuse_editor(update)
        return
    await query.answer()
    rule_set = await db.rules_db.get_or_create_community_set()
    draft = await db.rules_db.open_draft(int(rule_set["id"]), query.from_user.id)
    text = await rules_msg.editor_panel(
        rule_set, draft, await locale_for_update(update)
    )
    await safe_edit_cb(
        query,
        text,
        parse_mode="MarkdownV2",
        reply_markup=rules_kb.editor_panel_kb(await locale_for_update(update)),
    )


@decorators.permission_only("rules.manage")
async def on_rules_publish(update: Update, ctx: ContextTypes.DEFAULT_TYPE) -> None:
    """Publish the open draft and immediately sync the channel."""
    query = update.callback_query
    if query is None:
        return
    await query.answer()
    rule_set = await db.rules_db.get_or_create_community_set()
    draft = await db.rules_db.open_draft(int(rule_set["id"]), query.from_user.id)
    try:
        result = await publish_rules(
            int(rule_set["id"]), int(draft["id"]), query.from_user.id, ctx.bot
        )
    except Exception as exc:
        await safe_edit_cb(
            query,
            t("rules.publish.error", None, error=str(exc)),
            parse_mode="MarkdownV2",
        )
        return
    await safe_edit_cb(
        query,
        t(
            "rules.publish.result",
            None,
            synced=result["synced"],
            failed=len(result["failed"]),
        ),
        parse_mode="MarkdownV2",
    )


async def on_rules_cat_action(update: Update, ctx: ContextTypes.DEFAULT_TYPE) -> None:
    """Handle rename, reorder, and delete actions on a category."""
    query = update.callback_query
    if query is None or query.data is None:
        return
    if not await editor_allowed(update):
        await refuse_editor(update)
        return
    await query.answer()
    action, key = query.data.split(":", 1)
    rule_set = await db.rules_db.get_or_create_community_set()
    set_id = int(rule_set["id"])
    locale = await locale_for_update(update)
    if action == "rules_cat_rename":
        scope = flow_scope(ctx, update)
        scope["rules_category_key"] = key
        scope["rules_step"] = "rename_category"
        if query.message is not None:
            await safe_reply(
                cast("Any", query.message),
                t("rules.editor.ask_rename", locale, plain=True),
                parse_mode=None,
            )
        # * The reply above is the prompt; the next text lands in the editor
        # * conversation, which stores the pending rename in the scope.
        scope["rules_rename_state"] = WAITING_CATEGORY_TITLE
        return
    if action == "rules_cat_up":
        await db.rules_db.move_category(set_id, key, -1)
    elif action == "rules_cat_down":
        await db.rules_db.move_category(set_id, key, 1)
    elif action == "rules_cat_del":
        await db.rules_db.delete_category(set_id, key)
    categories = await db.rules_db.list_categories(set_id)
    await safe_edit_cb(
        query,
        rules_msg.category_list(categories, locale),
        parse_mode="MarkdownV2",
        reply_markup=rules_kb.categories_kb(categories, locale),
    )


__handlers__ = [
    CommandHandler("tcrules", cmd_tcrules),
    CommandHandler("rules", cmd_rules),
    CallbackQueryHandler(_acknowledge, pattern=r"^rules_ack:\d+:\d+$"),
    CallbackQueryHandler(on_rules_show, pattern=r"^rules_show:"),
    CallbackQueryHandler(on_rules_menu, pattern=r"^rules_menu$"),
    CallbackQueryHandler(
        on_rules_cat_action,
        pattern=r"^rules_cat_(rename|up|down|del):.+",
    ),
    CallbackQueryHandler(on_rules_panel, pattern=r"^rules_panel$"),
    CallbackQueryHandler(on_rules_publish, pattern=r"^rules_publish$"),
    build_rules_conv(),
]
