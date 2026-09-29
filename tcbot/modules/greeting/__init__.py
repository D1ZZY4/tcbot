# © Copyright 2024 - 2026 Transsion Core
# © Copyright 2024 - 2026 Dizzy
# © Copyright 2026 Ave Labs

"""New and left member event handlers, plus chat migration tracking."""

from __future__ import annotations

from telegram.ext import (
    ChatJoinRequestHandler,
    ChatMemberHandler,
    MessageHandler,
    filters,
)

from tcbot.modules.greeting.events import on_chat_migration, on_left_member
from tcbot.modules.greeting.joins import (
    _MAX_CONCURRENT_JOINS,
    _auto_demote_for_enforcement,
    _handle_member,
    _in_federation,
    _join_sem,
    on_new_member,
)
from tcbot.modules.greeting.requests import (
    on_join_request,
    on_join_request_approved,
)

__all__ = [
    "_MAX_CONCURRENT_JOINS",
    "__handlers__",
    "_auto_demote_for_enforcement",
    "_handle_member",
    "_in_federation",
    "_join_sem",
    "on_chat_migration",
    "on_join_request",
    "on_join_request_approved",
    "on_left_member",
    "on_new_member",
]


# ──────────────────────────── Handlers ──────────────────────────── #

# NOTE: The bot's own chat-member updates (MY_CHAT_MEMBER) are handled
# exclusively by connected_flow.connection.on_bot_added, registered in
# connecting.py. That single handler covers bot-added/promoted (join prompt,
# pending completion), bot-demoted (admin-rights-lost warning to mod channel),
# and bot-removed/kicked (federation group auto-deactivation). No second
# ChatMemberHandler is registered here to avoid PTB group-0 shadowing.

__handlers__ = [
    ChatJoinRequestHandler(on_join_request),
    ChatMemberHandler(on_join_request_approved, ChatMemberHandler.CHAT_MEMBER),
    MessageHandler(filters.StatusUpdate.NEW_CHAT_MEMBERS, on_new_member),
    MessageHandler(filters.StatusUpdate.LEFT_CHAT_MEMBER, on_left_member),
    MessageHandler(filters.StatusUpdate.MIGRATE, on_chat_migration),
]
