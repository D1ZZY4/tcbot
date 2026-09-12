# © Copyright 2024 - 2026 Transsion Core
# © Copyright 2024 - 2026 Dizzy
# © Copyright 2026 Ave Labs

"""safe_edit / safe_edit_cb helpers: edit messages in place, suppressing benign Telegram errors."""

from __future__ import annotations

import logging
from typing import TYPE_CHECKING, Any, Protocol

from telegram.error import BadRequest

if TYPE_CHECKING:
    from telegram import CallbackQuery, Message

log = logging.getLogger(__name__)

_IGNORED = {
    "message is not modified",
    "message to edit not found",
    "chat not found",
}


# ──────────────────────── safe_edit helper ──────────────────────── #


class _EditableMessage(Protocol):
    """Anything that exposes the ``edit_text`` coroutine used by ``safe_edit``.

    Both :class:`telegram.Message` and the ``Message`` half of a
    :class:`telegram.CallbackQuery` satisfy this protocol; the bot client
    half of a callback query exposes ``edit_message_text`` instead, so
    :func:`safe_edit_cb` uses a different code path.
    """

    async def edit_text(self, text: str, **kwargs: Any) -> object: ...


async def safe_edit(msg: _EditableMessage, text: str, **kwargs: Any) -> None:
    """Edit a message via ``msg.edit_text``; swallow harmless not-modified errors."""
    try:
        await msg.edit_text(text, parse_mode="MarkdownV2", **kwargs)
    except BadRequest as e:
        if any(i in str(e).lower() for i in _IGNORED):
            return
        log.warning("edit failed: %s", e)


async def safe_edit_cb(q: CallbackQuery, text: str, **kwargs: Any) -> None:
    """Edit a callback-query message; swallow harmless not-modified errors.

    Use this whenever a user can re-tap a button that lands them on the same
    content (e.g. a section sub-button while already viewing that section).
    """
    try:
        await q.edit_message_text(text, parse_mode="MarkdownV2", **kwargs)
    except BadRequest as e:
        if any(i in str(e).lower() for i in _IGNORED):
            return
        log.warning("callback edit failed: %s", e)


async def clear_markup_cb(q: CallbackQuery) -> None:
    """Remove the inline keyboard from a callback-query message.

    Editing message text without ``reply_markup`` keeps the old buttons
    (the parameter is omitted from the API call), so ending a flow with
    only an edit would leave dead buttons behind. Call this after the
    edit; "not modified" (already removed) is swallowed like
    :func:`safe_edit_cb`.
    """
    try:
        await q.edit_message_reply_markup(reply_markup=None)
    except BadRequest as e:
        if any(i in str(e).lower() for i in _IGNORED):
            return
        log.warning("clear markup failed: %s", e)


# ──────────────────────── safe_reply helper ─────────────────────── #


async def safe_reply(
    msg: Message,
    text: str,
    *,
    log_label: str = "reply",
    parse_mode: str | None = "MarkdownV2",
    **kwargs: Any,
) -> None:
    """Send a reply via ``msg.reply_text``; log failures at debug.

    Replaces the recurring 3-line pattern of

        try:
            await msg.reply_text(...)
        except Exception as exc:
            log.debug("...reply failed: %s", exc)

    which is duplicated across the command modules and workflows. The
    ``log_label`` parameter is the human-readable name of the call site
    (e.g. ``"mute summary fallback"``); it appears in the debug log line
    so the operator can identify the source without grepping for the
    function name.

    ``parse_mode`` defaults to ``"MarkdownV2"`` for formatted replies; pass
    ``None`` for plain-text replies (error strings, constants, community
    names) so Telegram performs no entity parsing, exactly like a bare
    ``reply_text`` call without the parameter.

    Failures are logged at ``debug`` (not ``warning``) because a failed
    ``reply_text`` is almost always benign: the user blocked the bot,
    the chat was deleted, or the message thread was closed.
    """
    try:
        await msg.reply_text(text, parse_mode=parse_mode, **kwargs)
    except Exception as exc:
        log.debug("%s reply failed: %s", log_label, exc)
