# © Copyright 2024 - 2026 Transsion Core
# © Copyright 2024 - 2026 Dizzy
# © Copyright 2026 Ave Labs

"""Forward transport for messages that carry user-authored content."""

from __future__ import annotations

from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from pyrogram.types import Message


async def forward_rich(
    msg: Message, chat_id: int | str, *, message_thread_id: int | None = None
) -> Message | list[Message] | None:
    """Forward an existing message through the owned transport.

    A forward keeps the original sender header, so it cannot be rendered as a
    bot-authored rich message. Keeping the low-level call here means no feature
    module reaches into a Telegram send method directly, and a future rich
    forward block has one owner to change.
    """
    return await msg.forward(chat_id, message_thread_id=message_thread_id)


__all__ = ["forward_rich"]
