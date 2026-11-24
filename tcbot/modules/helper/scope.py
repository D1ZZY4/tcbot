# © Copyright 2024 - 2026 Transsion Core
# © Copyright 2024 - 2026 Dizzy
# © Copyright 2026 Ave Labs

"""Per-conversation payload scope for the moderation flows.

The application context already keys its state by (chat, user), which is the
same granularity the multi-step conversations use. This module keeps the
single source of truth for reading and clearing that payload so flows cannot
mix two conversations of one moderator in different groups.
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Any

from tcbot.utils.update_processor import conversation_key  # noqa: F401 (public re-export)

if TYPE_CHECKING:
    from collections.abc import Collection

    from tcbot.modules.helper.context import Ctx


def flow_scope(ctx: Ctx) -> dict[str, Any]:
    """Return the payload dict owned by the conversation driving ``ctx``."""
    return ctx.user_data


def clear_flow_scope(ctx: Ctx, *, keys: Collection[str] | None = None) -> None:
    """Drop the flow payload of this conversation, optionally only named keys."""
    scope = ctx.user_data
    if keys is None:
        scope.clear()
        return
    for name in keys:
        scope.pop(name, None)


def callback_is_current(
    ctx: Ctx,
    scope: dict[str, Any],
    *,
    chat_key: str,
    message_key: str,
) -> bool:
    """Return True when a callback came from the flow's live prompt message."""
    query = ctx.callback_query
    if query is None:
        return False
    live_chat = scope.get(chat_key)
    live_msg = scope.get(message_key)
    # * Fail closed: a callback with no recorded prompt is not from a live
    # * flow. An empty scope used to be treated as current, which let a
    # * fabricated moderation callback reach an executor with no target.
    if not isinstance(live_chat, int) or not isinstance(live_msg, int):
        return False
    message = getattr(query, "message", None)
    if message is None:
        return False
    return (
        getattr(getattr(message, "chat", None), "id", None) == live_chat
        and getattr(message, "id", None) == live_msg
    )
