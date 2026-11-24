# © Copyright 2024 - 2026 Transsion Core
# © Copyright 2024 - 2026 Dizzy
# © Copyright 2026 Ave Labs

"""Rules commands: staff editor, public read-only menu, and acknowledgement."""

from __future__ import annotations

import asyncio
from typing import TYPE_CHECKING, Any

from telegram.ext import CallbackQueryHandler, ContextTypes, MessageHandler, filters

from tcbot import cfg
from tcbot import database as db
from tcbot.modules.helper import decorators
from tcbot.modules.helper.buttons import rules as rules_btn
from tcbot.modules.helper.locale import locale_for_update
from tcbot.modules.helper.messages import replies, reply_rich, safe_edit_cb
from tcbot.modules.helper.messages import rich_edit as rich_msg
from tcbot.modules.helper.messages import rules as rules_msg
from tcbot.modules.helper.pipelines.rules_editor import build_rules_conv
from tcbot.utils.i18n import t
from tcbot.utils.logger import get_logger
from tcbot.utils.prefixes import build_prefixed_filters

if TYPE_CHECKING:
    from telegram import Update

log = get_logger(__name__)

__module_name__ = "Rules"


def get_help(locale: str | None = None) -> replies.HelpEntry:
    """Return the help entry of the rules module."""
    return replies.module_help(
        locale,
        name=__module_name__,
        overview=t("rules.help.overview", locale),
        commands=t("rules.help.commands.body", locale),
        who=replies.perm_staff_only(locale, plain=False),
        where=replies.context_bot_or_group(locale),
        what=t("rules.help.what.body", locale),
        target=False,
    )


__help__: replies.HelpEntry = get_help()


# ─────────────────────────── Commands ─────────────────────────── #


@decorators.ratelimiter(decorators.THROTTLE_READ)
@decorators.log_execution
async def cmd_rules(update: Update, ctx: ContextTypes.DEFAULT_TYPE) -> None:
    """Show the public read-only rules menu."""
    msg = update.effective_message
    if msg is None:
        return
    locale = await locale_for_update(update)
    try:
        published = await db.rules_db.published_rules(locale=locale)
    except asyncio.CancelledError:
        raise
    except Exception:
        log.warning("The public rules menu could not load the published version.")
        await reply_rich(
            msg, t("common.err.db_retry", locale, plain=True), parse_mode=None
        )
        return
    if (
        published is None
        or not published.get("items")
        or not published.get("categories")
    ):
        await reply_rich(
            msg, t("rules.menu.empty", locale, plain=True), parse_mode=None
        )
        return
    await reply_rich(
        msg,
        rules_msg.rules_menu(locale, cfg.community_name),
        reply_markup=rules_btn.rules_index_btn(published["categories"], locale),
    )


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
    try:
        # * Validate against the same authority that built the greeting button.
        # * The button carries the version from acknowledgement_requirement()
        # * (the working-locale published version); comparing against the
        # * reader-locale published version told non-default-locale members their
        # * freshly generated button was outdated, so they could never accept.
        requirement = await db.rules_db.acknowledgement_requirement()
        if requirement is None or int(requirement[0]) != version_id:
            await query.answer(
                t("rules.ack.outdated", locale, plain=True), show_alert=True
            )
            return
        if await db.rules_db.has_acknowledged(version_id, user.id):
            await query.answer(
                t("rules.ack.already", locale, plain=True), show_alert=True
            )
            return
        await db.rules_db.record_acknowledgement(
            version_id,
            user.id,
            getattr(query.message, "chat_id", None),
            getattr(query.message, "message_id", None),
        )
    except asyncio.CancelledError:
        raise
    except Exception:
        # * The button would otherwise spin forever with no answer at all.
        log.warning("Rule acknowledgement could not be recorded for %s.", user.id)
        await query.answer(
            t("common.err.db_retry", locale, plain=True), show_alert=True
        )
        return
    await query.answer(t("rules.ack.recorded", locale, plain=True), show_alert=True)


def _page_from_data(data: str | None) -> int:
    """Parse a page index from a callback payload, defaulting to the first page."""
    try:
        return max(0, int(str(data).split(":", 1)[1]))
    except ValueError, IndexError:
        return 0


def _section_label(item: dict[str, Any]) -> str:
    """Return the section name stored in an item title after the category prefix."""
    title = str(item.get("title") or "Rules")
    return title.split(":", 1)[1].strip() if ":" in title else title


def _category_sections(items: list[dict[str, Any]]) -> list[str]:
    """Return section names in stored display order, without duplicates."""
    sections: list[str] = []
    for item in items:
        label = _section_label(item)
        if label not in sections:
            sections.append(label)
    return sections


async def _edit_payload(
    update: Update,
    ctx: ContextTypes.DEFAULT_TYPE,
    payload: dict[str, Any],
    markup: Any,
    fallback: str,
) -> None:
    """Edit the tapped panel as a rich message, with a plain fallback."""
    query = update.callback_query
    if query is None:
        return
    message = query.message
    if message is not None and getattr(message, "chat", None) is not None:
        try:
            await rich_msg.edit_rich(
                ctx.bot,
                message.chat.id,
                message.message_id,
                payload,
                reply_markup=markup,
            )
            return
        except Exception as exc:
            log.debug("Rich rules panel edit failed: %s", exc)
    await safe_edit_cb(query, fallback, reply_markup=markup)


async def _show_index(
    update: Update, ctx: ContextTypes.DEFAULT_TYPE, page: int
) -> None:
    """Render a page of category buttons, two per row."""
    query = update.callback_query
    if query is None:
        return
    locale = await locale_for_update(update)
    try:
        published = await db.rules_db.published_rules(locale=locale)
    except asyncio.CancelledError:
        raise
    except Exception:
        log.warning("The rules index could not load the published version.")
        await safe_edit_cb(
            query, t("common.err.db_retry", locale, plain=True), parse_mode=None
        )
        return
    if published is None or not published.get("categories"):
        return
    categories = published["categories"]
    per_page = rules_btn._RULES_PER_PAGE
    total = max(1, (len(categories) + per_page - 1) // per_page)
    page = max(0, min(page, total - 1))
    payload = rules_msg.rich_index_page(
        t("rules.menu.body", locale, community=cfg.community_name), locale
    )
    await _edit_payload(
        update,
        ctx,
        payload,
        rules_btn.rules_index_btn(categories, locale, page=page),
        t("rules.menu.body", locale, community=cfg.community_name),
    )


async def on_rules_index(update: Update, ctx: ContextTypes.DEFAULT_TYPE) -> None:
    """Show a page of the topic index."""
    query = update.callback_query
    if query is None:
        return
    await query.answer()
    await _show_index(update, ctx, _page_from_data(query.data))


async def on_rules_prev(update: Update, ctx: ContextTypes.DEFAULT_TYPE) -> None:
    """Show the previous topic page."""
    query = update.callback_query
    if query is None:
        return
    await query.answer()
    await _show_index(update, ctx, _page_from_data(query.data))


async def on_rules_next(update: Update, ctx: ContextTypes.DEFAULT_TYPE) -> None:
    """Show the next topic page."""
    query = update.callback_query
    if query is None:
        return
    await query.answer()
    await _show_index(update, ctx, _page_from_data(query.data))


async def on_rules_show(update: Update, ctx: ContextTypes.DEFAULT_TYPE) -> None:
    """Render one category with its short description and section buttons."""
    query = update.callback_query
    if query is None:
        return
    await query.answer()
    locale = await locale_for_update(update)
    try:
        published = await db.rules_db.published_rules(locale=locale)
    except asyncio.CancelledError:
        raise
    except Exception:
        log.warning("The rules category could not load the published version.")
        await safe_edit_cb(
            query, t("common.err.db_retry", locale, plain=True), parse_mode=None
        )
        return
    if published is None:
        return
    key = str(query.data or "").split(":", 1)[-1]
    category = next(
        (cat for cat in published["categories"] if str(cat["category_key"]) == key),
        None,
    )
    if category is None:
        return
    locale = await locale_for_update(update)
    items = [item for item in published["items"] if item["category_key"] == key]
    label = str(category.get("label") or category.get("title") or key)
    # * Both values are resolved from the database for the reader's locale.
    description = str(category.get("description") or "")
    payload = rules_msg.rich_category_index(key, label, description, locale)
    if ctx.user_data is not None:
        ctx.user_data["rules_current_category"] = key
    sections = _category_sections(items)
    await _edit_payload(
        update,
        ctx,
        payload,
        rules_btn.category_sections_btn(sections, locale),
        f"{label}\n{description}",
    )


async def on_rules_section(update: Update, ctx: ContextTypes.DEFAULT_TYPE) -> None:
    """Render the items of one section inside the current category."""
    query = update.callback_query
    if query is None or query.data is None:
        return
    await query.answer()
    locale = await locale_for_update(update)
    try:
        published = await db.rules_db.published_rules(locale=locale)
    except asyncio.CancelledError:
        raise
    except Exception:
        log.warning("The rules section could not load the published version.")
        await safe_edit_cb(
            query, t("common.err.db_retry", locale, plain=True), parse_mode=None
        )
        return
    if published is None:
        return
    index = _page_from_data(query.data)
    state = ctx.user_data if ctx.user_data is not None else {}
    key = str(state.get("rules_current_category") or "")
    if not key:
        return
    items = [item for item in published["items"] if item["category_key"] == key]
    sections = _category_sections(items)
    if index >= len(sections):
        return
    section = sections[index]
    section_items = [item for item in items if _section_label(item) == section]
    category = next(
        (cat for cat in published["categories"] if str(cat["category_key"]) == key),
        None,
    )
    label = (
        str(category.get("label") or category.get("title") or key) if category else key
    )
    payload = rules_msg.rich_section_page(
        key, section, section_items, locale, category_title=label
    )
    await _edit_payload(
        update,
        ctx,
        payload,
        rules_btn.rules_section_btn(key, locale),
        f"{label}: {section}",
    )


async def on_rules_menu(update: Update, ctx: ContextTypes.DEFAULT_TYPE) -> None:
    """Handle a stale Back tap from a keyboard emitted before pagination."""
    query = update.callback_query
    if query is None:
        return
    await query.answer()
    await _show_index(update, ctx, 0)


async def on_rules_page(update: Update, ctx: ContextTypes.DEFAULT_TYPE) -> None:
    """Handle a stale More tap by opening the requested topic page."""
    query = update.callback_query
    if query is None:
        return
    await query.answer()
    await _show_index(update, ctx, _page_from_data(query.data))


_RULES_CMDS = build_prefixed_filters("rules")

# * The Open in PM button on the group surface uses a deep link, so the
# * reader lands directly on the public rules menu instead of the start menu.
_RULES_START = filters.ChatType.PRIVATE & filters.Regex(r"^/start\s+rules$")

__handlers__ = [
    MessageHandler(_RULES_START, cmd_rules),
    MessageHandler(_RULES_CMDS, cmd_rules),
    CallbackQueryHandler(_acknowledge, pattern=r"^rules_ack:\d+:\d+$"),
    CallbackQueryHandler(on_rules_index, pattern=r"^rules_index:\d+$"),
    CallbackQueryHandler(on_rules_section, pattern=r"^rules_section:\d+$"),
    CallbackQueryHandler(on_rules_prev, pattern=r"^rules_prev:\d+$"),
    CallbackQueryHandler(on_rules_next, pattern=r"^rules_next:\d+$"),
    CallbackQueryHandler(on_rules_show, pattern=r"^rules_show:"),
    CallbackQueryHandler(on_rules_menu, pattern=r"^rules_menu$"),
    CallbackQueryHandler(on_rules_page, pattern=r"^rules_page:\d+$"),
    build_rules_conv(),
]
