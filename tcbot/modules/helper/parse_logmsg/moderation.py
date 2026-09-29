# © Copyright 2024 - 2026 Transsion Core
# © Copyright 2024 - 2026 Dizzy
# © Copyright 2026 Ave Labs

"""Moderation audit-log builders: bans, proofs, mutes, kicks, warns, unbans."""

from __future__ import annotations

from typing import TYPE_CHECKING

from tcbot import cfg
from tcbot.modules.helper.parse_logmsg.core import LogBuilder
from tcbot.utils.formatter import code, esc, link

if TYPE_CHECKING:
    from datetime import datetime


def ban_log(
    target_id: int,
    target_fname: str,
    admin_id: int,
    admin_fname: str,
    reason: str,
    ban_id: str,
    timestamp: datetime | None = None,
) -> str:
    """Return a new federation-ban audit-log message."""
    return (
        LogBuilder(f"New {cfg.community_name} Ban")
        .mention_field("Admin", admin_id, admin_fname)
        .section()
        .mention_field("User", target_id, target_fname)
        .code_field("User ID", target_id)
        .code_field("Ban ID", ban_id)
        .field("Reason", reason)
        .section()
        .date(timestamp, label="Commit at")
        .build()
    )


def ban_update_log(
    target_id: int,
    target_fname: str,
    new_admin_id: int,
    new_admin_fname: str,
    old_admin_id: int,
    old_admin_fname: str,
    reason: str,
    ban_id: str,
    original_ts: datetime,
) -> str:
    """Update-ban audit-log message."""
    return (
        LogBuilder(f"Update {cfg.community_name} Ban")
        .mention_field("Admin", new_admin_id, new_admin_fname)
        .mention_field("Previous Admin", old_admin_id, old_admin_fname)
        .section()
        .mention_field("User", target_id, target_fname)
        .code_field("User ID", target_id)
        .code_field("Ban ID", ban_id)
        .field("Reason", reason)
        .section()
        .date(original_ts, label="Commit at")
        .date(label="Update at")
        .build()
    )


def proof_caption_new(
    target_id: int,
    admin_id: int,
    admin_fname: str,
    timestamp: datetime,
) -> str:
    """Caption used on the initial proof message."""
    return (
        LogBuilder(f"ID: {target_id}")
        .section()
        .mention_field("Admin", admin_id, admin_fname)
        .code_field("Admin ID", admin_id)
        .section()
        .date(timestamp, label="Commit at")
        .build()
    )


def proof_caption_update(
    target_id: int,
    admin_id: int,
    admin_fname: str,
    original_ts: datetime,
    prev_proof_lnk: str | None = None,
) -> str:
    """Caption used when the proof message is updated."""
    b = (
        LogBuilder(f"ID: {target_id}")
        .section()
        .mention_field("Admin", admin_id, admin_fname)
        .code_field("Admin ID", admin_id)
    )
    if prev_proof_lnk:
        b.section().field("Previous", link("Click Here", prev_proof_lnk), escape=False)
    return (
        b.section().date(original_ts, label="Commit at").date(label="Update at").build()
    )


def mute_log(
    target_id: int,
    target_fname: str,
    admin_id: int,
    admin_fname: str,
    reason: str,
    duration_str: str,
) -> str:
    """Federation-mute audit-log message."""
    return (
        LogBuilder(f"{cfg.community_name} Muted")
        .mention_field("Admin", admin_id, admin_fname)
        .mention_field("User", target_id, target_fname)
        .code_field("User ID", target_id)
        .field("Reason", reason)
        .field("Duration", duration_str)
        .section()
        .date()
        .build()
    )


def unmute_log(
    target_id: int,
    target_fname: str,
    admin_id: int,
    admin_fname: str,
) -> str:
    """Federation-unmute audit-log message."""
    return (
        LogBuilder(f"{cfg.community_name} Federation Unmute")
        .mention_field("Admin", admin_id, admin_fname)
        .mention_field("User", target_id, target_fname)
        .code_field("User ID", target_id)
        .section()
        .date()
        .build()
    )


def kick_log(
    target_id: int,
    target_fname: str,
    admin_id: int,
    admin_fname: str,
    reason: str,
    chat_id: int,
    chat_title: str,
) -> str:
    """Kick audit-log message."""
    return (
        LogBuilder(f"{cfg.community_name} Kicked")
        .mention_field("Admin", admin_id, admin_fname)
        .mention_field("User", target_id, target_fname)
        .code_field("User ID", target_id)
        .field("Reason", reason)
        .raw(f"Group: {esc(chat_title)} \\({code(str(chat_id))}\\)")
        .section()
        .date()
        .build()
    )


def resetwarns_log(
    target_id: int,
    target_fname: str,
    admin_id: int,
    admin_fname: str,
    removed: int,
    chat_id: int,
    chat_title: str,
) -> str:
    """Reset-warns audit-log message."""
    return (
        LogBuilder(f"{cfg.community_name} Reset Warns")
        .mention_field("Admin", admin_id, admin_fname)
        .mention_field("User", target_id, target_fname)
        .code_field("User ID", target_id)
        .field("Warnings cleared", str(removed))
        .raw(f"Group: {esc(chat_title)} \\({code(str(chat_id))}\\)")
        .section()
        .date()
        .build()
    )


def warn_log(
    target_id: int,
    target_fname: str,
    admin_id: int,
    admin_fname: str,
    reason: str,
    count: int,
    warn_limit: int,
    chat_id: int,
    chat_title: str,
) -> str:
    """Warn audit-log message."""
    return (
        LogBuilder(f"{cfg.community_name} Warn")
        .mention_field("Admin", admin_id, admin_fname)
        .mention_field("User", target_id, target_fname)
        .code_field("User ID", target_id)
        .field("Reason", reason)
        .field("Warnings", f"{count}/{warn_limit}")
        .raw(f"Group: {esc(chat_title)} \\({code(str(chat_id))}\\)")
        .section()
        .date()
        .build()
    )


def unwarn_log(
    target_id: int,
    target_fname: str,
    admin_id: int,
    admin_fname: str,
    new_count: int,
    warn_limit: int,
    chat_id: int,
    chat_title: str,
) -> str:
    """Unwarn audit-log message."""
    return (
        LogBuilder(f"{cfg.community_name} Unwarn")
        .mention_field("Admin", admin_id, admin_fname)
        .mention_field("User", target_id, target_fname)
        .code_field("User ID", target_id)
        .field("Warnings now", f"{new_count}/{warn_limit}")
        .raw(f"Group: {esc(chat_title)} \\({code(str(chat_id))}\\)")
        .section()
        .date()
        .build()
    )


def unban_log(
    target_id: int,
    target_fname: str,
    admin_id: int,
    admin_fname: str,
    ban_id: str,
    reason: str | None = None,
) -> str:
    """Unban audit-log message."""
    b = (
        LogBuilder(f"{cfg.community_name} Unban")
        .mention_field("Admin", admin_id, admin_fname)
        .mention_field("User", target_id, target_fname)
        .code_field("User ID", target_id)
        .code_field("Ban ID", ban_id)
    )
    if reason:
        b.field("Unban Reason", reason)
    return b.section().date().build()
