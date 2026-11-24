# © Copyright 2024 - 2026 Transsion Core
# © Copyright 2024 - 2026 Dizzy
# © Copyright 2026 Ave Labs

"""Start command handler and main-menu callback handlers."""

from __future__ import annotations

import asyncio
from typing import Any

from pyrogram.types import CallbackQuery

from tcbot import cfg
from tcbot import database as db
from tcbot.modules.helper import buttons, decorators
from tcbot.modules.helper.context import Ctx, chat_id_of
from tcbot.modules.helper.handlers import CallbackQueryHandler, MessageHandler
from tcbot.modules.helper.locale import locale_for_update
from tcbot.modules.helper.messages import (
    about_msg,
    about_section_labels,
    answer_and_edit,
    render_groups,
    replies,
    reply_rich,
    safe_edit_cb,
)
from tcbot.modules.helper.rich.formats import heading, highlight, quote
from tcbot.modules.helper.rich.list import bullet_list
from tcbot.utils.dispatch import throw_if_cancelled
from tcbot.utils.i18n import Safe, divider, esc, italic, t
from tcbot.utils.logger import get_logger
from tcbot.utils.prefixes import build_prefixed_filters

log = get_logger(__name__)


__module_name__ = None

# ────────────────────────── Start Message ───────────────────────── #


def _start_blocks(botname: str, locale: str | None, *, private: bool) -> str:
    """Build the welcome card from real rich blocks in the requested locale.

    All prose lives in the catalog. The fragments built here are pre-formatted
    rich HTML so the template can keep the order without double escaping.
    """
    if private:
        title_key = "start.private.title"
        intro_key = "start.private.intro"
        hint_key = "start.private.hint"
        body_key = "start.private.body"
    else:
        title_key = "start.group.title"
        intro_key = "start.group.intro"
        hint_key = "start.group.hint"
        body_key = "start.group.body"
    title = heading(t(title_key, locale, botname=botname, plain=True))
    intro = quote(esc(t(intro_key, locale, community=cfg.community_name, plain=True)))
    fragments: dict[str, Any] = {
        "title": Safe(title),
        "divider": Safe(divider()),
        "intro": Safe(intro),
    }
    if private:
        fragments["capabilities"] = Safe(
            bullet_list(
                [
                    t("start.private.cap_bans", locale, plain=True),
                    t("start.private.cap_mutes", locale, plain=True),
                    t("start.private.cap_kicks", locale, plain=True),
                    t("start.private.cap_moderation", locale, plain=True),
                ]
            )
        )
        fragments["usage"] = Safe(
            highlight(t("start.private.usage", locale, plain=True))
        )
    fragments["hint"] = Safe(italic(t(hint_key, locale, plain=True)))
    return t(body_key, locale, **fragments)


def _private_start_text(botname: str, locale: str | None = None) -> str:
    """Build the PM start message for the given plain-text bot display name."""
    return _start_blocks(botname, locale, private=True)


def _group_start_text(botname: str, locale: str | None = None) -> str:
    """Build the group start message for the given plain-text bot display name."""
    return _start_blocks(botname, locale, private=False)


# ──────────────────────── Command Handlers ──────────────────────── #


@decorators.ratelimiter(decorators.THROTTLE_READ)
@decorators.log_execution
async def cmd_start(ctx: Ctx) -> None:
    """Respond to /start in private chats and groups.

    In group context sends a minimal message with a PM deep-link. In private
    context dispatches to the relevant info handler when a deep-link argument is
    present (``ban_<id>``), otherwise shows the full welcome message.
    """
    msg = ctx.effective_message
    chat = ctx.effective_chat
    if msg is None or chat is None:
        return

    text = (msg.text or "").strip()
    parts = text.split(None, 1)
    arg = parts[1].strip() if len(parts) > 1 else ""
    identity = await ctx.bot_identity()
    botname = identity.first_name or ""
    locale = await locale_for_update(ctx)

    # * A forum is a supergroup in Telegram; "forum" is not a chat type.
    if getattr(chat.type, "value", chat.type) in ("group", "supergroup"):
        bot_username = identity.username or ""
        await reply_rich(
            msg,
            _group_start_text(botname, locale),
            log_label="cmd_start group",
            reply_markup=buttons.group_start_btn(bot_username, locale),
        )
        return

    if arg == "about":
        await reply_rich(
            msg,
            about_msg(locale),
            log_label="cmd_start about",
            reply_markup=buttons.about_sections_btn(
                about_section_labels(locale), locale
            ),
        )
        return

    # * appeal<ban_id> deep links are handled by the ConversationHandler in appeals.py
    await reply_rich(
        msg,
        _private_start_text(botname, locale),
        log_label="cmd_start PM",
        reply_markup=buttons.main_menu_btn(locale),
    )


# ──────────────────────── Callback Handlers ─────────────────────── #


@decorators.ratelimiter(decorators.THROTTLE_CALLBACK)
@decorators.log_execution
async def on_back_to_start(ctx: Ctx) -> None:
    """Return to the main menu when the Back button is tapped in a sub-menu."""
    q = ctx.callback_query
    if q is None:
        return

    identity = await ctx.bot_identity()
    botname = identity.first_name or ""
    locale = await locale_for_update(ctx)
    await answer_and_edit(
        q,
        _private_start_text(botname, locale),
        reply_markup=buttons.main_menu_btn(locale),
    )


async def _show_groups(q: CallbackQuery, ctx: Ctx, *, detailed: bool) -> None:
    """Shared renderer for all group-menu callbacks."""
    locale = await locale_for_update(ctx)
    # * q.answer() and active_groups() are independent; run in parallel.
    answer_r, groups_r = await asyncio.gather(
        q.answer(), db.groups_db.active_groups(), return_exceptions=True
    )
    throw_if_cancelled((answer_r, groups_r))
    if isinstance(groups_r, BaseException):
        # * Never render an empty list from a failed read: during an outage
        # * that would claim no groups are connected. Keep the back keyboard
        # * so re-tapping the menu retries the fetch.
        log.warning("_show_groups groups fetch failed: %s", groups_r)
        await safe_edit_cb(
            q,
            replies.err_groups_load_failed(locale, plain=False),
            reply_markup=buttons.back_to_start_btn(locale),
            log_level="debug",
            log_label="_show_groups load-failed",
            catch_all=True,
        )
        return
    groups = groups_r
    if not groups:
        # * Already answered in the gather above; answering again would raise
        # * BadRequest (query already answered). Edit in place like the list
        # * branch below (the old msg.reply_text referenced an undefined name,
        # * so the empty state never rendered at all).
        await safe_edit_cb(
            q,
            # * Rich mode: this edit carries rich HTML, so the configured
            # * community name must be escaped rather than passed through raw.
            t(
                "groups.menu.empty",
                locale,
                community=cfg.community_name,
            ),
            parse_mode=None,
            reply_markup=buttons.back_to_start_btn(locale),
            log_level="debug",
            log_label="_show_groups no-groups",
            catch_all=True,
        )
        return
    await safe_edit_cb(
        q,
        render_groups(groups, detailed=detailed, locale=locale),
        reply_markup=buttons.groups_menu_btn(detailed=detailed, locale=locale),
        log_level="debug",
        log_label="_show_groups list",
        catch_all=True,
    )


@decorators.ratelimiter(decorators.THROTTLE_CALLBACK)
@decorators.log_execution
async def on_menu_groups(ctx: Ctx) -> None:
    """Show the connected-groups list in simple view from the start menu."""
    q = ctx.callback_query
    if q is None:
        return
    await _show_groups(q, ctx, detailed=False)


@decorators.ratelimiter(decorators.THROTTLE_CALLBACK)
@decorators.log_execution
async def on_menu_groups_details(ctx: Ctx) -> None:
    """Show the connected-groups list with full group IDs visible."""
    q = ctx.callback_query
    if q is None:
        return
    await _show_groups(q, ctx, detailed=True)


@decorators.ratelimiter(decorators.THROTTLE_CALLBACK)
@decorators.log_execution
async def on_close(ctx: Ctx) -> None:
    """Dismiss a read-only panel by deleting the message it lives on."""
    q = ctx.callback_query
    if q is None:
        return
    await q.answer()
    try:
        if q.message is not None:
            chat = getattr(q.message, "chat", None)
            if chat is not None:
                await ctx.bot.delete_messages(chat_id_of(chat), q.message.id)
    except Exception as exc:
        log.debug("Close button could not delete the panel: %s", exc)


# ──────────────────────────── Handlers ──────────────────────────── #

_START_CMDS = build_prefixed_filters("start")

__handlers__ = [
    MessageHandler(_START_CMDS, cmd_start),
    CallbackQueryHandler(on_back_to_start, pattern=r"^back_to_start$"),
    CallbackQueryHandler(on_close, pattern=r"^close_msg$"),
    CallbackQueryHandler(on_menu_groups, pattern=r"^(menu_groups|menu_groups_simple)$"),
    CallbackQueryHandler(on_menu_groups_details, pattern=r"^menu_groups_details$"),
]
