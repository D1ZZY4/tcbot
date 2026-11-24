# © Copyright 2024 - 2026 Transsion Core
# © Copyright 2024 - 2026 Dizzy
# © Copyright 2026 Ave Labs

"""Regression checks for the Kurigram-only runtime contracts."""

from __future__ import annotations

import asyncio
from types import SimpleNamespace
from typing import Any

from pyrogram import Client
from pyrogram.enums import ChatType

from tcbot.modules.helper import handlers
from tcbot.modules.helper.context import bot_identity
from tcbot.modules.helper.extraction import resolve
from tcbot.modules.helper.rich import msg as rich_msg


class _ReplyCapture:
    """Minimal message double that records the transport keywords."""

    def __init__(self) -> None:
        self.kwargs: dict[str, Any] = {}

    async def reply_rich(self, _payload: Any, **kwargs: Any) -> Any:
        self.kwargs = kwargs
        return SimpleNamespace(id=7)


def test_rich_reply_does_not_pass_thread_id_to_kurigram() -> None:
    """The bound Kurigram reply already carries the host thread id."""
    message = _ReplyCapture()
    sent = asyncio.run(rich_msg.reply_rich_result(message, "hello"))
    assert sent.id == 7
    assert "message_thread_id" not in message.kwargs


def test_chat_type_enums_resolve_by_value() -> None:
    """A Kurigram chat-type enum compares equal to its string value."""
    assert ChatType.PRIVATE.value == "private"
    assert resolve._is_private_chat(SimpleNamespace(type=ChatType.PRIVATE)) is True
    assert resolve._is_private_chat(SimpleNamespace(type=ChatType.GROUP)) is False


def test_client_is_not_a_user_object() -> None:
    """Display name and id must come from get_me, not the Client itself."""
    assert not hasattr(Client, "first_name")
    assert not hasattr(Client, "id")
    assert hasattr(Client, "delete_messages")


def test_bot_identity_comes_from_get_me_and_is_cached() -> None:
    """The Kurigram Client is not a User; its profile lives on get_me()."""
    calls: list[int] = []

    class _Client:
        def __init__(self) -> None:
            self.me: Any = None

        async def get_me(self) -> Any:
            calls.append(1)
            return SimpleNamespace(id=42, first_name="TCF", username="tcfbot")

    client = _Client()
    first = asyncio.run(bot_identity(client))  # type: ignore[arg-type]
    second = asyncio.run(bot_identity(client))  # type: ignore[arg-type]
    assert first.first_name == "TCF"
    assert first is second
    assert calls == [1]


def test_updates_are_serialized_per_conversation() -> None:
    """The keyed processor owns handler execution at the framework boundary."""
    assert isinstance(handlers._updates, handlers.KeyedUpdateProcessor)
    asyncio.run(handlers.shutdown_dispatcher())
