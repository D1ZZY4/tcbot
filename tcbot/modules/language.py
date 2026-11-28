# © Copyright 2024 - 2026 Transsion Core
# © Copyright 2024 - 2026 Dizzy
# © Copyright 2026 Ave Labs

"""Language preferences: per-user and per-group locale selection UI."""

from __future__ import annotations

import asyncio
import re

from pyrogram.types import InlineKeyboardMarkup

from tcbot import cfg
from tcbot import database as db
from tcbot.modules.helper import buttons, decorators
from tcbot.modules.helper.context import Ctx, chat_id_of
from tcbot.modules.helper.handlers import CallbackQueryHandler, MessageHandler
from tcbot.modules.helper.identity import can_manage_group
from tcbot.modules.helper.locale import effective_locale
from tcbot.modules.helper.messages import (
    answer_ack,
    replies,
    reply_rich,
    safe_edit_cb,
)
from tcbot.modules.helper.rich.formats import heading, quote
from tcbot.utils.dispatch import throw_if_cancelled
from tcbot.utils.i18n import (
    Safe,
    available_locales,
    display_name,
    divider,
    esc,
    is_known_locale,
    t,
)
from tcbot.utils.logger import get_logger
from tcbot.utils.prefixes import build_prefixed_filters

log = get_logger(__name__)


# ────────────────────── Module & Help Message ───────────────────── #

__module_name__ = "Language"


def get_help(locale: str | None = None) -> replies.HelpEntry:
    """Build this module's help entry in the given locale."""
    return replies.module_help(
        locale,
        name=__module_name__,
        overview=t("language.help.overview", locale),
        commands=t("language.help.commands.body", locale),
        who=t("language.help.who.body", locale),
        where=replies.context_bot_or_group(locale),
        what=t("language.help.what.body", locale),
        target=False,
        examples=t("language.help.examples.body", locale),
    )


__help__: replies.HelpEntry = get_help()

# ─────────────────────── Callback Data Shapes ────────────────────── #
# * lang:list:<scope> opens the option list; lang:set:<scope>:<locale>
# * saves and edits the panel into a confirmation. Scope is user|group
# * and must match the chat type, so crafted cross-scope taps die early.

_SCOPE_RE: str = r"(user|group)"
_LOCALE_RE: str = r"([A-Za-z]{2}(?:-[A-Za-z]{2})?)"
_LIST_PATTERN: str = rf"^lang:list:{_SCOPE_RE}$"
_SET_PATTERN: str = rf"^lang:set:{_SCOPE_RE}:{_LOCALE_RE}$"


def _chat_scope(chat_type: object) -> str:
    """Map a chat type to the locale scope it reads: user in PM, group otherwise."""
    return "user" if getattr(chat_type, "value", chat_type) == "private" else "group"


def _options_btn(scope: str, locale: str) -> InlineKeyboardMarkup:
    """Build the locale-option keyboard for ``scope`` in display ``locale``."""
    items = [(display_name(code_), code_) for code_ in available_locales()]
    return buttons.language_list_btn(scope, items, selected=locale, locale=locale)


def _panel_text(scope: str, locale: str) -> str:
    """Render the selection panel body for ``scope`` in ``locale``.

    The heading, rules, and quotation are real rich blocks. Newline-separated
    plain text reaches the rich transport as one collapsed line, so the
    structure lives in the catalog with pre-formatted fragments from here.
    """
    if scope == "user":
        body = t(
            "language.current_user", locale, language=display_name(locale), plain=True
        )
        title = t("language.title_user", locale, plain=True)
    else:
        body = t(
            "language.current_group", locale, language=display_name(locale), plain=True
        )
        title = t("language.title_group", locale, plain=True)
    hint = t("language.prompt", locale, plain=True)
    return t(
        "language.panel",
        locale,
        title=Safe(heading(title)),
        divider=Safe(divider()),
        # * quote() does not escape; a translated body with & or < would
        # * otherwise be injected into the rich HTML payload.
        quote=Safe(quote(esc(f"{body}\n{hint}"))),
    )


def _confirmation_text(scope: str, chosen: str) -> str:
    """Render the saved-confirmation body in the newly chosen locale."""
    name = display_name(chosen)
    if scope == "user":
        return t("language.updated_user", chosen, language=name)
    return t("language.updated_group", chosen, language=name)


async def _ack_and_notice(q: object, msg: object, text: str, *, label: str) -> None:
    """Acknowledge a refused tap and reply to its message in parallel.

    The callback answer and the reply address different surfaces and carry no
    shared payload, so one round trip suffices. Both helpers swallow normal
    failures; cancellation must still propagate.
    """
    if msg is None:
        await answer_ack(q)  # type: ignore[arg-type]
        return
    ack_r, reply_r = await asyncio.gather(
        answer_ack(q),  # type: ignore[arg-type]
        reply_rich(msg, text, log_label=label),  # type: ignore[arg-type]
        return_exceptions=True,
    )
    throw_if_cancelled((ack_r, reply_r))


# ──────────────────────── Command Handlers ───────────────────────── #


@decorators.ratelimiter(decorators.THROTTLE_STAFF)
@decorators.log_execution
async def cmd_language(ctx: Ctx) -> None:
    """Show the language panel: personal in PM, group-wide in groups."""
    msg = ctx.effective_message
    user = ctx.effective_user
    chat = ctx.effective_chat
    if msg is None or user is None or chat is None:
        return
    scope = _chat_scope(chat.type)
    locale = await effective_locale(chat.type, user.id, chat_id_of(chat))
    if scope == "group":
        permitted = await can_manage_group(ctx.bot, chat_id_of(chat), user.id)
    else:
        permitted = True
    if permitted:
        btn: InlineKeyboardMarkup | None = _options_btn(scope, locale)
    else:
        btn = None
    await reply_rich(
        msg, _panel_text(scope, locale), log_label="cmd_language", reply_markup=btn
    )


# ──────────────────────── Callback Handlers ──────────────────────── #


@decorators.ratelimiter(decorators.THROTTLE_CALLBACK)
@decorators.log_execution
async def on_language_menu(ctx: Ctx) -> None:
    """Open the personal language panel from the start-menu Language button."""
    q = ctx.callback_query
    user = ctx.effective_user
    chat = ctx.effective_chat
    if q is None or user is None or chat is None:
        if q is not None:
            await q.answer()
        return
    await q.answer()
    locale = await effective_locale(chat.type, user.id, chat_id_of(chat))
    await safe_edit_cb(
        q,
        _panel_text("user", locale),
        reply_markup=buttons.language_list_btn(
            "user",
            [(display_name(code_), code_) for code_ in available_locales()],
            back_callback="back_to_start",
            selected=locale,
            locale=locale,
        ),
        log_level="debug",
        log_label="language menu",
        catch_all=True,
    )


@decorators.ratelimiter(decorators.THROTTLE_CALLBACK)
@decorators.log_execution
async def on_lang_list(ctx: Ctx) -> None:
    """Re-render the option list (Back target of confirmations)."""
    q = ctx.callback_query
    user = ctx.effective_user
    chat = ctx.effective_chat
    if q is None or q.data is None or user is None or chat is None:
        if q is not None:
            await q.answer()
        return
    data = q.data
    if isinstance(data, bytes):
        data = data.decode("utf-8", "replace")
    match = re.fullmatch(_LIST_PATTERN, data)
    if match is None:
        await q.answer()
        return
    scope = match.group(1)
    if scope != _chat_scope(chat.type):
        await q.answer()
        return
    if scope == "group" and not await can_manage_group(
        ctx.bot, chat_id_of(chat), user.id, fresh=True
    ):
        # * Re-rendering the group panel is a group-management action, so
        # * the same check the save path applies guards the Back target.
        denied_locale = await effective_locale(chat.type, user.id, chat_id_of(chat))
        try:
            await q.answer(
                t("language.denied", denied_locale, plain=True), show_alert=True
            )
        except Exception as exc:
            log.debug("language denied answer failed: %s", exc)
        return
    await q.answer()
    locale = await effective_locale(chat.type, user.id, chat_id_of(chat))
    back_callback = "back_to_start" if scope == "user" else None
    await safe_edit_cb(
        q,
        _panel_text(scope, locale),
        reply_markup=buttons.language_list_btn(
            scope,
            [(display_name(code_), code_) for code_ in available_locales()],
            back_callback=back_callback,
            selected=locale,
            locale=locale,
        ),
        log_level="debug",
        log_label="language list",
        catch_all=True,
    )


@decorators.ratelimiter(decorators.THROTTLE_CALLBACK)
@decorators.log_execution
async def on_lang_set(ctx: Ctx) -> None:
    """Save the tapped locale and edit the panel into a confirmation."""
    q = ctx.callback_query
    user = ctx.effective_user
    chat = ctx.effective_chat
    msg = ctx.effective_message
    if q is None or q.data is None or user is None or chat is None:
        if q is not None:
            await q.answer()
        return
    data = q.data
    if isinstance(data, bytes):
        data = data.decode("utf-8", "replace")
    match = re.fullmatch(_SET_PATTERN, data)
    if match is None:
        await q.answer()
        return
    scope, raw_locale = match.group(1), match.group(2)
    if scope != _chat_scope(chat.type):
        await q.answer()
        return
    # * Alerts below render in the tapper's current locale, not the
    # * default: the tapped target may be unknown or denied, but the
    # * reader's own setting is still resolvable. The query is answered per
    # * branch: Telegram accepts one answer, so an ack here would make the
    # * denial alerts impossible to show.
    tapper_locale = await effective_locale(chat.type, user.id, chat_id_of(chat))
    if not is_known_locale(raw_locale):
        try:
            await q.answer(
                t("language.unavailable", tapper_locale, plain=True), show_alert=True
            )
        except Exception as exc:
            log.debug("language unavailable answer failed: %s", exc)
        return
    locale = raw_locale
    if scope == "group":
        if not await can_manage_group(ctx.bot, chat_id_of(chat), user.id, fresh=True):
            try:
                await q.answer(
                    t("language.denied", tapper_locale, plain=True), show_alert=True
                )
            except Exception as exc:
                log.debug("language denied answer failed: %s", exc)
            return
        try:
            # * The main group and other deployment destinations are origins
            # * even though they are not connected federation groups, so
            # * their locale stays configurable.
            connected = (
                cfg.is_primary_group(chat_id_of(chat))
                or cfg.is_infrastructure_chat(chat_id_of(chat))
                or await db.groups_db.is_connected(chat_id_of(chat), fresh=True)
            )
        except Exception as exc:
            log.debug("language is_connected failed for %d: %s", chat_id_of(chat), exc)
            connected = False
        if not connected:
            await _ack_and_notice(
                q,
                msg,
                t("language.not_connected", tapper_locale),
                label="language not-connected",
            )
            return
        try:
            saved = await db.groups_db.set_group_locale(chat_id_of(chat), locale)
        except Exception:
            log.exception("set_group_locale failed for chat %d", chat_id_of(chat))
            await _ack_and_notice(
                q,
                msg,
                t("common.retry", tapper_locale),
                label="language group-save-fail",
            )
            return
        if not saved:
            # * An infrastructure chat without a settings row is an UPDATE
            # * that matches nothing. Never claim the locale was saved when
            # * no row changed; the next render would still use the default.
            log.warning("set_group_locale matched no row for chat %d", chat_id_of(chat))
            await _ack_and_notice(
                q, msg, t("common.retry", tapper_locale), label="language group-no-row"
            )
            return
    else:
        try:
            await db.settings_db.set_user_locale(user.id, locale)
        except Exception:
            log.exception("set_user_locale failed for user %d", user.id)
            await _ack_and_notice(
                q,
                msg,
                t("common.retry", tapper_locale),
                label="language user-save-fail",
            )
            return
    await answer_ack(q)
    await safe_edit_cb(
        q,
        _confirmation_text(scope, locale),
        reply_markup=buttons.back_to_module_btn(f"lang:list:{scope}", locale),
        log_level="debug",
        log_label="language confirm",
        catch_all=True,
    )


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
