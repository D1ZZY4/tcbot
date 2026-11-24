# © Copyright 2024 - 2026 Transsion Core
# © Copyright 2024 - 2026 Dizzy
# © Copyright 2026 Ave Labs

"""Kurigram handler construction for the application's command and flow layer.

The bot registers commands, callbacks and multi-step flows. Kurigram exposes
real handler classes; this module builds them from the application's filter
and callback declarations so call sites stay compact. Every object returned
here is a genuine ``pyrogram.handlers.Handler`` ready for ``add_handler``.
"""

from __future__ import annotations

from contextvars import ContextVar
from typing import TYPE_CHECKING, Any

from pyrogram import filters
from pyrogram.handlers import (
    CallbackQueryHandler as _CallbackQueryHandler,
)
from pyrogram.handlers import (
    ChatJoinRequestHandler as _ChatJoinRequestHandler,
)
from pyrogram.handlers import (
    ChatMemberUpdatedHandler as _ChatMemberUpdatedHandler,
)
from pyrogram.handlers import (
    EditedMessageHandler as _EditedMessageHandler,
)
from pyrogram.handlers import (
    MessageHandler as _MessageHandler,
)
from pyrogram.types import CallbackQuery, ChatJoinRequest, ChatMemberUpdated, Message

from tcbot.modules.helper.context import build_ctx
from tcbot.utils.logger import get_logger
from tcbot.utils.update_processor import KeyedUpdateProcessor

if TYPE_CHECKING:
    from collections.abc import Awaitable, Callable

    from pyrogram import Client
    from pyrogram.filters import Filter
    from pyrogram.handlers import Handler

log = get_logger(__name__)

# * Kurigram dispatches with a worker pool and no per-key ordering. The flow
# * state is keyed by (chat, user), so updates of one conversation must stay
# * ordered while other conversations keep running.
_updates = KeyedUpdateProcessor()
# * The error handler receives a raw MTProto update. The application context
# * built here is the reliable source of user, chat, and callback details.
_current_ctx: ContextVar[Any | None] = ContextVar("tcbot_current_ctx", default=None)


def current_ctx() -> Any | None:
    """Return the application context of the handler running in this task."""
    return _current_ctx.get()


def _wrap(
    callback: Callable[..., Awaitable[object]],
) -> Callable[..., Awaitable[object]]:
    """Wrap an application handler ``(ctx)`` into a Kurigram ``(client, update)`` callback."""

    async def wrapped(client: Client, update: object) -> object:
        callback_query = update if isinstance(update, CallbackQuery) else None
        chat_member = update if isinstance(update, ChatMemberUpdated) else None
        join_request = update if isinstance(update, ChatJoinRequest) else None
        message = (
            update
            if isinstance(update, Message)
            else (callback_query.message if callback_query is not None else None)
        )
        args: tuple[str, ...] = ()
        if message is not None:
            command = getattr(message, "command", None)
            if isinstance(command, list) and len(command) > 1:
                args = tuple(command[1:])
            elif isinstance(message.text, str):
                parts = message.text.split(None, 1)
                args = tuple(parts[1].split()) if len(parts) > 1 else ()
        ctx = await build_ctx(
            client,
            message=message if isinstance(update, Message) else None,
            callback_query=callback_query,
            chat_member=chat_member,
            chat_join_request=join_request,
            update_id=getattr(update, "id", 0) or 0,
            args=args,
        )
        token = _current_ctx.set(ctx)
        try:
            await _updates.do_process_update(ctx, callback(ctx))
        finally:
            _current_ctx.reset(token)
        return None

    return wrapped


def MessageHandler(filter_or_callback: Any, callback: Any = None) -> Handler:
    """Build a Kurigram message handler.

    Accepts both ``(callback, filters)`` and the application's historical
    ``(filters, callback)`` ordering; the latter is used by existing call sites.
    """
    if callback is None:
        return _MessageHandler(_wrap(filter_or_callback))
    return _MessageHandler(_wrap(callback), filter_or_callback)


def CallbackQueryHandler(callback: Any, pattern: str | None = None) -> Handler:
    """Build a Kurigram callback-query handler from an application callback."""
    return _CallbackQueryHandler(
        _wrap(callback), filters.regex(pattern) if pattern else None
    )


def ChatMemberHandler(callback: Any, *args: Any, **kwargs: Any) -> Handler:
    """Build a Kurigram chat-member-updated handler."""
    return _ChatMemberUpdatedHandler(_wrap(callback))


# * Registration sites use these labels to distinguish the two member events.
CHAT_MEMBER = "chat_member"
MY_CHAT_MEMBER = "my_chat_member"


def ChatJoinRequestHandler(callback: Any, *args: Any, **kwargs: Any) -> Handler:
    """Build a Kurigram chat-join-request handler."""
    return _ChatJoinRequestHandler(_wrap(callback))


def EditedMessageHandler(callback: Any, filter_: Filter | None = None) -> Handler:
    """Build a Kurigram edited-message handler."""
    return _EditedMessageHandler(_wrap(callback), filter_)


class ConversationHandler:
    """Flatten a multi-step flow into one Kurigram handler group.

    Kurigram has no conversation framework. This small owner keeps the
    application's entry points, state handlers and fallbacks together and
    dispatches each update to the first matching handler. Flow state lives in
    ``Ctx.user_data`` (a TTL-bounded store), not in the framework.
    """

    END: int = -1

    def __init__(
        self,
        *,
        entry_points: list[Handler] | None = None,
        states: dict[object, list[Handler]] | None = None,
        fallbacks: list[Handler] | None = None,
        **kwargs: Any,
    ) -> None:
        """Store the flow's handlers so they can be flattened at registration."""
        self.entry_points = entry_points or []
        self.states = states or {}
        self.fallbacks = fallbacks or []
        self.handlers: list[Handler] = [
            *self.entry_points,
            *(handler for group in self.states.values() for handler in group),
            *self.fallbacks,
        ]

    def as_handlers(self) -> list[Handler]:
        """Return the flattened Kurigram handlers of this flow."""
        return self.handlers


async def shutdown_dispatcher() -> None:
    """Release the per-conversation locks when the client stops."""
    await _updates.shutdown()


def flatten(handlers: list[Any]) -> list[Handler]:
    """Expand conversation flows into their concrete Kurigram handlers."""
    result: list[Handler] = []
    for handler in handlers:
        if isinstance(handler, ConversationHandler):
            result.extend(handler.as_handlers())
        else:
            result.append(handler)
    return result
