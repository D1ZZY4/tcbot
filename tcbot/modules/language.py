# © Copyright 2024 - 2026 Transsion Core
# © Copyright 2024 - 2026 Dizzy
# © Copyright 2026 Ave Labs

"""Language preferences: per-user and per-group locale selection UI."""

from __future__ import annotations

import asyncio
import logging
import re
from typing import TYPE_CHECKING

from telegram.ext import CallbackQueryHandler, ContextTypes, MessageHandler

from tcbot import database as db
from tcbot.modules.helper import decorators, keyboards, replies
from tcbot.modules.helper.parse_editmsg import safe_reply
from tcbot.utils.formatter import code
from tcbot.utils.i18n import (
    DEFAULT_LOCALE,
    available_locales,
    display_name,
    is_known_locale,
    resolve_locale,
    t,
)
from tcbot.utils.prefixes import build_prefixed_filters
from tcbot.utils.time_and_date import TELEGRAM_LOOKUP_TIMEOUT

if TYPE_CHECKING:
    from telegram import Update

log = logging.getLogger(__name__)

# ─────────────────────── Rate-limiter constants ──────────────────── #
_RL_PERIOD_S: int = 30
_RL_CMD_LIMIT: int = 10
_RL_CB_LIMIT: int = 15

# ────────────────────── Module & Help Message ───────────────────── #

__module_name__ = "Language"
__help_text__ = "View or change language preferences for yourself or the group\\."

__help_sections__: list[tuple[str, str]] = [
    (
        replies.SEC_COMMANDS,
        f"{code('/language')} \\(aliases: {code('/lang')}, {code('/langs')}\\)",
    ),
    (
        replies.SEC_WHO,
        "Anyone for their own preference\\. Group language needs the group "
        "owner or staff rank\\.",
    ),
    (
        replies.SEC_WHAT,
        "Shows the current language with one button per available locale\\. "
        "Tapping a language saves it immediately and edits the panel into "
        "a confirmation\\.",
    ),
    (
        replies.SEC_EXAMPLES,
        f"{code('/lang')}",
    ),
]

__help__: replies.HelpEntry = {
    "name": __module_name__,
    "overview": __help_text__,
    "sections": __help_sections__,
}

# ─────────────────────── Callback Data Shapes ────────────────────── #
# * lang:list:<scope> opens the option list; lang:set:<scope>:<locale>
# * saves and edits the panel into a confirmation. Scope is user|group
# * and must match the chat type, so crafted cross-scope taps die early.

_SCOPE_RE: str = r"(user|group)"
_LOCALE_RE: str = r"([A-Za-z]{2}(?:-[A-Za-z]{2})?)"
_LIST_PATTERN: str = rf"^lang:list:{_SCOPE_RE}$"
_SET_PATTERN: str = rf"^lang:set:{_SCOPE_RE}:{_LOCALE_RE}$"


def _chat_scope(chat_type: str | None) -> str:
    """Map a chat type to the locale scope it reads: user in PM, group otherwise."""
    return "user" if chat_type == "private" else "group"


async def _effective_locale(chat_type: str | None, user_id: int, chat_id: int) -> str:
    """Resolve the locale used to render a panel in this chat."""
    user_locale, group_locale = await asyncio.gather(
        db.settings_db.get_user_locale(user_id),
        db.groups_db.get_group_locale(chat_id),
        return_exceptions=True,
    )
    if isinstance(user_locale, BaseException):
        log.debug("language user-locale read failed for %d: %s", user_id, user_locale)
        user_locale = None
    if isinstance(group_locale, BaseException):
        log.debug("language group-locale read failed for %d: %s", chat_id, group_locale)
        group_locale = None
    return resolve_locale(
        chat_type=chat_type or "private",
        user_locale=user_locale if isinstance(user_locale, str) else None,
        group_locale=group_locale if isinstance(group_locale, str) else None,
    )


async def _can_set_group(bot: object, chat_id: int, user_id: int) -> bool:
    """Return True when ``user_id`` may change the group language.

    Group owner (creator) or federation staff, mirroring the disconnect
    permission shape. Fail closed: any lookup failure denies.
    """
    try:
        is_staff = await db.users_roles.is_staff(user_id)
    except asyncio.CancelledError:
        raise
    except Exception as exc:
        log.debug("language staff check failed for %d: %s", user_id, exc)
        return False
    if is_staff:
        return True
    get_member = getattr(bot, "get_chat_member", None)
    if get_member is None:
        return False
    try:
        member = await asyncio.wait_for(
            get_member(chat_id, user_id), timeout=TELEGRAM_LOOKUP_TIMEOUT
        )
    except asyncio.CancelledError:
        raise
    except Exception as exc:
        log.debug("language member check failed for %d/%d: %s", chat_id, user_id, exc)
        return False
    return getattr(member, "status", None) == "creator"


def _options_kb(scope: str, locale: str) -> keyboards.InlineKeyboardMarkup:
    """Build the locale-option keyboard for ``scope`` in display ``locale``."""
    items = [(display_name(code_), code_) for code_ in available_locales()]
    back = t("common.back", locale)
    return keyboards.language_list_kb(scope, items, back_label=back, selected=locale)


def _panel_text(scope: str, locale: str) -> str:
    """Render the selection panel body for ``scope`` in ``locale``."""
    if scope == "user":
        body = t("language.current_user", locale, language=display_name(locale))
        title = t("language.title_user", locale)
    else:
        body = t("language.current_group", locale, language=display_name(locale))
        title = t("language.title_group", locale)
    hint = t("language.prompt", locale)
    return f"{title}\n\n{body}\n\n{hint}"


def _confirmation_text(scope: str, chosen: str) -> str:
    """Render the saved-confirmation body in the newly chosen locale."""
    name = display_name(chosen)
    if scope == "user":
        return t("language.updated_user", chosen, language=name)
    return t("language.updated_group", chosen, language=name)


# ──────────────────────── Command Handlers ───────────────────────── #


@decorators.ratelimiter(limit=_RL_CMD_LIMIT, period=_RL_PERIOD_S)
@decorators.log_execution
async def cmd_language(update: Update, ctx: ContextTypes.DEFAULT_TYPE) -> None:
    """Show the language panel: personal in PM, group-wide in groups."""
    msg = update.effective_message
    user = update.effective_user
    chat = update.effective_chat
    if msg is None or user is None or chat is None:
        return
    scope = _chat_scope(chat.type)
    locale = await _effective_locale(chat.type, user.id, chat.id)
    if scope == "group":
        permitted = await _can_set_group(ctx.bot, chat.id, user.id)
    else:
        permitted = True
    if permitted:
        kb: keyboards.InlineKeyboardMarkup | None = _options_kb(scope, locale)
    else:
        kb = None
    await safe_reply(
        msg, _panel_text(scope, locale), log_label="cmd_language", reply_markup=kb
    )


# ──────────────────────── Callback Handlers ──────────────────────── #


@decorators.ratelimiter(limit=_RL_CB_LIMIT, period=_RL_PERIOD_S)
@decorators.log_execution
async def on_language_menu(update: Update, ctx: ContextTypes.DEFAULT_TYPE) -> None:
    """Open the personal language panel from the start-menu Language button."""
    q = update.callback_query
    user = update.effective_user
    chat = update.effective_chat
    if q is None or user is None or chat is None:
        if q is not None:
            await q.answer()
        return
    await q.answer()
    locale = await _effective_locale(chat.type, user.id, chat.id)
    try:
        await q.edit_message_text(
            _panel_text("user", locale),
            parse_mode="MarkdownV2",
            reply_markup=keyboards.language_list_kb(
                "user",
                [(display_name(code_), code_) for code_ in available_locales()],
                back_label=t("common.back", locale),
                back_callback="back_to_start",
                selected=locale,
            ),
        )
    except Exception as exc:
        log.debug("language menu edit failed: %s", exc)


@decorators.ratelimiter(limit=_RL_CB_LIMIT, period=_RL_PERIOD_S)
@decorators.log_execution
async def on_lang_list(update: Update, ctx: ContextTypes.DEFAULT_TYPE) -> None:
    """Re-render the option list (Back target of confirmations)."""
    q = update.callback_query
    user = update.effective_user
    chat = update.effective_chat
    if q is None or q.data is None or user is None or chat is None:
        if q is not None:
            await q.answer()
        return
    match = re.fullmatch(_LIST_PATTERN, q.data)
    if match is None:
        await q.answer()
        return
    scope = match.group(1)
    if scope != _chat_scope(chat.type):
        await q.answer()
        return
    await q.answer()
    locale = await _effective_locale(chat.type, user.id, chat.id)
    back_callback = "back_to_start" if scope == "user" else None
    try:
        await q.edit_message_text(
            _panel_text(scope, locale),
            parse_mode="MarkdownV2",
            reply_markup=keyboards.language_list_kb(
                scope,
                [(display_name(code_), code_) for code_ in available_locales()],
                back_label=t("common.back", locale),
                back_callback=back_callback,
                selected=locale,
            ),
        )
    except Exception as exc:
        log.debug("language list edit failed: %s", exc)


@decorators.ratelimiter(limit=_RL_CB_LIMIT, period=_RL_PERIOD_S)
@decorators.log_execution
async def on_lang_set(update: Update, ctx: ContextTypes.DEFAULT_TYPE) -> None:
    """Save the tapped locale and edit the panel into a confirmation."""
    q = update.callback_query
    user = update.effective_user
    chat = update.effective_chat
    msg = update.effective_message
    if q is None or q.data is None or user is None or chat is None:
        if q is not None:
            await q.answer()
        return
    match = re.fullmatch(_SET_PATTERN, q.data)
    if match is None:
        await q.answer()
        return
    scope, raw_locale = match.group(1), match.group(2)
    if scope != _chat_scope(chat.type):
        await q.answer()
        return
    await q.answer()
    if not is_known_locale(raw_locale):
        try:
            await q.answer(
                t("language.unavailable", DEFAULT_LOCALE, plain=True), show_alert=True
            )
        except Exception as exc:
            log.debug("language unavailable answer failed: %s", exc)
        return
    locale = raw_locale
    if scope == "group":
        if not await _can_set_group(ctx.bot, chat.id, user.id):
            try:
                await q.answer(
                    t("language.denied", DEFAULT_LOCALE, plain=True), show_alert=True
                )
            except Exception as exc:
                log.debug("language denied answer failed: %s", exc)
            return
        try:
            connected = await db.groups_db.is_connected(chat.id)
        except Exception as exc:
            log.debug("language is_connected failed for %d: %s", chat.id, exc)
            connected = False
        if not connected:
            if msg is not None:
                await safe_reply(
                    msg,
                    t("language.not_connected", DEFAULT_LOCALE),
                    log_label="language not-connected",
                )
            return
        try:
            await db.groups_db.set_group_locale(chat.id, locale)
        except Exception:
            log.exception("set_group_locale failed for chat %d", chat.id)
            if msg is not None:
                await safe_reply(
                    msg,
                    t("common.retry", DEFAULT_LOCALE),
                    log_label="language group-save-fail",
                )
            return
    else:
        try:
            await db.settings_db.set_user_locale(user.id, locale)
        except Exception:
            log.exception("set_user_locale failed for user %d", user.id)
            if msg is not None:
                await safe_reply(
                    msg,
                    t("common.retry", DEFAULT_LOCALE),
                    log_label="language user-save-fail",
                )
            return
    try:
        await q.edit_message_text(
            _confirmation_text(scope, locale),
            parse_mode="MarkdownV2",
            reply_markup=keyboards.back_to_module_kb(f"lang:list:{scope}"),
        )
    except Exception as exc:
        log.debug("language confirm edit failed: %s", exc)


# ──────────────────────────── Handlers ───────────────────────────── #

_LANG_CMDS = (
    build_prefixed_filters("language")
    | build_prefixed_filters("lang")
    | build_prefixed_filters("langs")
)

__handlers__ = [
    MessageHandler(_LANG_CMDS, cmd_language),
    CallbackQueryHandler(on_language_menu, pattern=r"^language_menu$"),
    CallbackQueryHandler(on_lang_list, pattern=r"^lang:list:(user|group)$"),
    CallbackQueryHandler(
        on_lang_set, pattern=r"^lang:set:(user|group):[A-Za-z]{2}(?:-[A-Za-z]{2})?$"
    ),
]
