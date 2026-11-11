# © Copyright 2024 - 2026 Transsion Core
# © Copyright 2024 - 2026 Dizzy
# © Copyright 2026 Ave Labs

"""Per-conversation payload scope for the moderation flows.

python-telegram-bot stores ``ctx.user_data`` per user id, so one dict is
shared by every chat a user is in. The moderation conversations are
registered ``per_chat=True, per_user=True``, which means their payload
belongs to one (chat, user) pair.

Keeping the payload directly in ``ctx.user_data`` therefore mixes two
conversations of the same moderator: a second action started in another
group overwrites the target, the reason and the prompt of the first one, so
the first action enforces against the wrong target. This module owns the
scoping so every flow reads and writes its own payload only.
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
    from telegram import Update
    from telegram.ext import ContextTypes

# * Key holding the per-user map of conversation scopes inside
# * ``ctx.user_data``.
_SCOPES_KEY = "tc_flow_scopes"


def conversation_key(update: Update) -> tuple[int, int] | None:
    """Return the (chat id, user id) key of the conversation owning ``update``.

    This mirrors the key python-telegram-bot builds for a conversation
    registered with ``per_chat=True, per_user=True``. ``None`` when the
    update carries no chat or no user, which means it cannot belong to a
    conversation.
    """
    chat = update.effective_chat
    user = update.effective_user
    if chat is None or user is None:
        return None
    return (chat.id, user.id)


def flow_scope(ctx: ContextTypes.DEFAULT_TYPE, update: Update) -> dict[str, Any]:
    """Return the payload dict owned by the conversation driving ``update``.

    The dict is created on first use and lives under one key of
    ``ctx.user_data``, so it disappears with the user data of that user.
    An empty dict is returned when the context carries no user data or the
    update belongs to no conversation; the flow handlers check for that
    before they write, so no payload is silently dropped.

    The scope map of one user holds one entry per chat that user moderated
    in, so its size follows the federation and not the traffic.
    """
    user_data = ctx.user_data
    if user_data is None:
        return {}
    key = conversation_key(update)
    if key is None:
        return {}
    scopes = user_data.get(_SCOPES_KEY)
    if not isinstance(scopes, dict):
        scopes = {}
        user_data[_SCOPES_KEY] = scopes
    scope = scopes.get(key)
    if not isinstance(scope, dict):
        scope = {}
        scopes[key] = scope
    return scope


def clear_flow_scope(ctx: ContextTypes.DEFAULT_TYPE, update: Update) -> None:
    """Drop the payload of the conversation driving ``update``.

    Removing the whole scope entry keeps ``ctx.user_data`` from growing
    with one empty dict per chat a user ever moderated in.
    """
    user_data = ctx.user_data
    if user_data is None:
        return
    key = conversation_key(update)
    if key is None:
        return
    scopes = user_data.get(_SCOPES_KEY)
    if isinstance(scopes, dict):
        scopes.pop(key, None)
        if not scopes:
            user_data.pop(_SCOPES_KEY, None)
