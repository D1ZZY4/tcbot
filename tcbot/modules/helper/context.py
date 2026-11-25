# © Copyright 2024 - 2026 Transsion Core
# © Copyright 2024 - 2026 Dizzy
# © Copyright 2026 Ave Labs

"""Kurigram-native update context and per-conversation state.

Kurigram delivers a bare ``Client`` and an update object to each handler. The
application needs a small, stable surface for the acting user, chat, message,
callback query and the multi-step flow state. ``Ctx`` owns that surface and
backs its state with a bounded, TTL-limited store keyed by (chat, user), so
simultaneous moderators and separate groups never share a conversation.
"""

from __future__ import annotations

import contextlib
import time
from collections import OrderedDict
from dataclasses import dataclass, field
from types import SimpleNamespace
from typing import TYPE_CHECKING, Any

from tcbot.utils.logger import get_logger

if TYPE_CHECKING:
    from pyrogram import Client
    from pyrogram.types import (
        CallbackQuery,
        Chat,
        ChatJoinRequest,
        ChatMemberUpdated,
        Message,
        User,
    )

log = get_logger(__name__)


async def bot_identity(client: Client) -> Any:
    """Return the bot's own User, fetching it once from Telegram.

    Kurigram's ``Client`` is not a User: profile fields live on the parsed
    ``client.me`` returned by ``get_me()``. Doubles that expose the fields
    directly are returned as-is so tests need no Telegram round trip.
    """
    me = getattr(client, "me", None)
    if me is not None:
        return me
    if hasattr(client, "first_name") or hasattr(client, "username"):
        return client
    if not callable(getattr(client, "get_me", None)):
        return SimpleNamespace(id=0, first_name="", username=None)
    me = await client.get_me()
    with contextlib.suppress(Exception):
        client.me = me
    return me


_STATE_TTL_S: float = 3600.0
_MAX_STATES: int = 10_000


@dataclass(slots=True)
class _Slot:
    state: dict[str, Any] = field(default_factory=dict)
    touched: float = field(default_factory=time.monotonic)


def chat_id_of(chat: object) -> int:
    """Return a non-optional chat id for state keys and Telegram calls."""
    return int(getattr(chat, "id", 0) or 0)


def display_name(user: object) -> str:
    """Return a user's display name, falling back to a stable identifier."""
    first = getattr(user, "first_name", None)
    if first:
        return str(first)
    username = getattr(user, "username", None)
    if username:
        return str(username)
    return str(getattr(user, "id", 0) or 0)


_StateKey = tuple[int, int]
# * OrderedDict keeps slots in ascending order of last access so expired and
# * over-capacity entries are popped from the head in O(expired) time instead
# * of scanning up to _MAX_STATES entries on every update.
_states: OrderedDict[_StateKey, _Slot] = OrderedDict()


def _evict_expired(now: float) -> None:
    """Drop slots that outlived the TTL or exceed the bounded store."""
    cutoff = now - _STATE_TTL_S
    while _states:
        _, oldest_slot = next(iter(_states.items()))
        if oldest_slot.touched >= cutoff and len(_states) <= _MAX_STATES:
            break
        _states.popitem(last=False)


def _state_for_sync(chat_id: int, user_id: int, now: float) -> dict[str, Any]:
    """Return the mutable state dict for one (chat, user) conversation."""
    key = (chat_id, user_id)
    _evict_expired(now)
    slot = _states.get(key)
    if slot is None:
        slot = _Slot(touched=now)
        _states[key] = slot
    else:
        slot.touched = now
        _states.move_to_end(key)
    return slot.state


async def state_for(chat_id: int, user_id: int) -> dict[str, Any]:
    """Return the mutable state dict for one (chat, user) conversation."""
    return _state_for_sync(chat_id, user_id, time.monotonic())


async def clear_state(chat_id: int, user_id: int) -> None:
    """Drop the state of one conversation, e.g. after cancel or completion."""
    _states.pop((chat_id, user_id), None)


@dataclass(slots=True)
class Ctx:
    """One Kurigram update plus its application-level state.

    ``bot`` is an alias of ``client``. The ``effective_*`` and
    ``callback_query`` names are the stable application surface used across
    the handlers; they are implemented here directly on top of Kurigram types
    and carry no framework dependency.
    """

    client: Client
    message: Message | None = None
    callback_query: CallbackQuery | None = None
    chat_member: ChatMemberUpdated | None = None
    chat_join_request: ChatJoinRequest | None = None
    update_id: int = 0
    args: tuple[str, ...] = ()
    _state_chat_id: int = 0
    _state_user_id: int = 0
    _conv_key: tuple[int, int] | None = None
    _user_data: dict[str, Any] | None = None
    _chat_data: dict[str, Any] | None = None
    _bot_data: dict[str, Any] | None = None

    @property
    def user_data(self) -> dict[str, Any]:
        """Return the per-conversation state dict, allocating lazily on first read."""
        if self._user_data is None:
            self._user_data = _state_for_sync(
                self._state_chat_id, self._state_user_id, time.monotonic()
            )
        return self._user_data

    @user_data.setter
    def user_data(self, value: dict[str, Any]) -> None:
        self._user_data = value

    @property
    def chat_data(self) -> dict[str, Any]:
        """Return the per-chat state dict, allocating lazily on first read."""
        if self._chat_data is None:
            self._chat_data = _state_for_sync(self._state_chat_id, 0, time.monotonic())
        return self._chat_data

    @chat_data.setter
    def chat_data(self, value: dict[str, Any]) -> None:
        self._chat_data = value

    @property
    def bot_data(self) -> dict[str, Any]:
        """Return the bot-wide scratch dict, allocating lazily on first read."""
        if self._bot_data is None:
            self._bot_data = {}
        return self._bot_data

    @bot_data.setter
    def bot_data(self, value: dict[str, Any]) -> None:
        self._bot_data = value

    @property
    def bot(self) -> Client:
        """Return the Kurigram client that owns this update."""
        return self.client

    @property
    def effective_user(self) -> User | None:
        """Return the acting user, regardless of update kind."""
        if self.callback_query is not None:
            return self.callback_query.from_user
        if self.chat_member is not None:
            return self.chat_member.from_user
        if self.chat_join_request is not None:
            return self.chat_join_request.from_user
        if self.message is not None:
            return self.message.from_user
        return None

    @property
    def effective_chat(self) -> Chat | None:
        """Return the chat the update belongs to."""
        if self.chat_member is not None:
            return self.chat_member.chat
        if self.chat_join_request is not None:
            return self.chat_join_request.chat
        if self.callback_query is not None and self.callback_query.message is not None:
            return self.callback_query.message.chat
        if self.message is not None:
            return self.message.chat
        return None

    @property
    def effective_message(self) -> Message | None:
        """Return the message to act on, including a callback's host message."""
        if self.message is not None:
            return self.message
        if self.callback_query is not None:
            return self.callback_query.message
        return None

    @property
    def chat_id(self) -> int:
        """Return the acting chat id as a non-optional integer."""
        return chat_id_of(self.effective_chat)

    @property
    def actor_id(self) -> int:
        """Return the acting user's id as a non-optional integer."""
        return int(getattr(self.effective_user, "id", 0) or 0)

    @property
    def actor_fname(self) -> str:
        """Return the acting user's display name."""
        return display_name(self.effective_user)

    async def bot_identity(self) -> Any:
        """Return the bot's parsed identity for display names and links."""
        return await bot_identity(self.client)

    async def answer(
        self, text: str | None = None, *, show_alert: bool = False
    ) -> None:
        """Acknowledge the callback query once; no-op for message updates."""
        if self.callback_query is None:
            return
        try:
            await self.callback_query.answer(text, show_alert=show_alert)
        except Exception as exc:
            log.debug("callback answer failed: %s", exc)


def build_ctx_sync(
    client: Client,
    *,
    message: Message | None = None,
    callback_query: CallbackQuery | None = None,
    chat_member: ChatMemberUpdated | None = None,
    chat_join_request: ChatJoinRequest | None = None,
    update_id: int = 0,
    args: tuple[str, ...] = (),
) -> Ctx:
    """Build a context synchronously; conversation state dicts allocate lazily."""
    chat = None
    user = None
    if chat_member is not None:
        chat, user = chat_member.chat, chat_member.from_user
    elif chat_join_request is not None:
        chat, user = chat_join_request.chat, chat_join_request.from_user
    elif callback_query is not None:
        user = callback_query.from_user
        if callback_query.message is not None:
            chat = callback_query.message.chat
    elif message is not None:
        chat, user = message.chat, message.from_user
    raw_chat_id = getattr(chat, "id", None) if chat is not None else None
    raw_user_id = getattr(user, "id", None) if user is not None else None
    conv_key = (
        (raw_chat_id, raw_user_id)
        if isinstance(raw_chat_id, int) and isinstance(raw_user_id, int)
        else None
    )
    return Ctx(
        client=client,
        message=message,
        callback_query=callback_query,
        chat_member=chat_member,
        chat_join_request=chat_join_request,
        update_id=update_id,
        args=args,
        _state_chat_id=int(raw_chat_id or 0),
        _state_user_id=int(raw_user_id or 0),
        _conv_key=conv_key,
    )


async def build_ctx(
    client: Client,
    *,
    message: Message | None = None,
    callback_query: CallbackQuery | None = None,
    chat_member: ChatMemberUpdated | None = None,
    chat_join_request: ChatJoinRequest | None = None,
    update_id: int = 0,
    args: tuple[str, ...] = (),
) -> Ctx:
    """Build a context and attach the persistent state of this conversation."""
    return build_ctx_sync(
        client,
        message=message,
        callback_query=callback_query,
        chat_member=chat_member,
        chat_join_request=chat_join_request,
        update_id=update_id,
        args=args,
    )


__all__ = [
    "Ctx",
    "bot_identity",
    "build_ctx",
    "build_ctx_sync",
    "chat_id_of",
    "clear_state",
    "display_name",
    "state_for",
]
