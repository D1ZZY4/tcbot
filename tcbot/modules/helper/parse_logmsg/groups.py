# © Copyright 2024 - 2026 Transsion Core
# © Copyright 2024 - 2026 Dizzy
# © Copyright 2026 Ave Labs

"""Group and broadcast audit-log builders: connections, removals, broadcasts."""

from __future__ import annotations

from tcbot import cfg
from tcbot.modules.helper.parse_logmsg.core import LogBuilder
from tcbot.utils.formatter import code, esc, link, safe_username, user_ref

_MAX_BROADCAST_PREVIEW_LEN: int = 100


def group_connected_log(
    chat_id: int,
    chat_title: str,
    owner_id: int,
    owner_fname: str,
    chat_username: str | None = None,
) -> str:
    """Return a new federation-connected-group audit-log message."""
    uname = safe_username(chat_username)
    if uname:
        group_display = link(chat_title, f"https://t.me/{uname}")
    else:
        group_display = esc(chat_title)
    return (
        LogBuilder(f"New {cfg.community_name} Connected Group")
        .raw(f"Group: {group_display}")
        .code_field("ID", chat_id)
        .section()
        .mention_field("Added by Owner", owner_id, owner_fname)
        .code_field("ID", owner_id)
        .section()
        .date()
        .build()
    )


def group_connection_rejected_log(
    chat_id: int,
    chat_title: str,
    owner_id: int,
    owner_fname: str,
) -> str:
    """Connection-rejected audit-log message."""
    return (
        LogBuilder(f"{cfg.community_name} Connection Rejected")
        .raw(f"Group: {esc(chat_title)} \\(ID: {chat_id}\\)")
        .section()
        .raw(
            f"Rejected by Owner: {user_ref(owner_id, owner_fname)} \\(ID: {code(str(owner_id))}\\)"
        )
        .section()
        .date()
        .build()
    )


def group_disconnected_log(
    chat_id: int,
    chat_title: str,
    actor_id: int,
    actor_fname: str,
) -> str:
    """Group-disconnected audit-log message."""
    return (
        LogBuilder(f"{cfg.community_name} Group Disconnected")
        .field("Group", chat_title)
        .code_field("ID", chat_id)
        .section()
        .mention_field("Removed by", actor_id, actor_fname)
        .code_field("ID", actor_id)
        .section()
        .date()
        .build()
    )


def group_bot_removed_log(
    chat_id: int,
    chat_title: str,
) -> str:
    """Audit-log written when the bot is removed from a connected group."""
    return (
        LogBuilder(f"{cfg.community_name} Group Removed Bot")
        .field("Group", chat_title)
        .code_field("ID", chat_id)
        .section()
        .date()
        .build()
    )


def broadcast_log(
    admin_id: int,
    admin_fname: str,
    message_preview: str,
    success: int,
    failed: int,
) -> str:
    """Broadcast audit-log message."""
    preview = message_preview[:_MAX_BROADCAST_PREVIEW_LEN]
    return (
        LogBuilder(f"{cfg.community_name} Broadcast Sent")
        .mention_field("Admin", admin_id, admin_fname)
        .field("Message", preview)
        .section()
        .field("Groups reached", str(success))
        .field("Failed groups", str(failed))
        .section()
        .date()
        .build()
    )
