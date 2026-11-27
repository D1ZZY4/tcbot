# © Copyright 2024 - 2026 Transsion Core
# © Copyright 2024 - 2026 Dizzy
# © Copyright 2026 Ave Labs

"""Audit-log builders for moderation, appeal, role, and group events."""

from __future__ import annotations

from typing import TYPE_CHECKING

from tcbot import cfg
from tcbot import database as db
from tcbot.modules.helper.rich.formats import divider, heading, paragraph
from tcbot.modules.helper.rich.style import bold as rich_bold
from tcbot.modules.helper.rich.table import table
from tcbot.utils.i18n import code, esc, link, safe_username, user_ref
from tcbot.utils.logger import get_logger
from tcbot.utils.time_and_date import fmt_date, fmt_time, utc_now

if TYPE_CHECKING:
    from datetime import datetime

log = get_logger(__name__)

# * Caps the broadcast log preview to one line of the operator's message.
_MAX_BROADCAST_PREVIEW_LEN: int = 100
# * Enough for a reviewer to judge an appeal when the forwarded original
# * could not be posted to the appeals destination.
_APPEAL_EXCERPT_MAX: int = 600

# ───────────────────────── Audit-log builder ────────────────────────── #


class LogBuilder:
    """Fluent builder for audit-log messages rendered as rich tables.

    Every label/value pair is a row in a compact two-column Field/Value table,
    the same layout used by the profile, statistics, and ban-detail panels.
    Trusted markup from mention, code, and link helpers stays live in cells;
    untrusted values are escaped once by the owning helper. Headings, section
    dividers, and free-form notes render as their own rich blocks.
    """

    __slots__ = ("_items",)

    def __init__(self, title: str) -> None:
        """Start a new log message with the given title header.

        The title is escaped by ``heading()`` so callers can pass raw config or
        user-facing strings without breaking the rich markup sent to the log.
        """
        self._items: list[tuple[str, str | list[str]]] = [
            ("heading", heading(str(title)))
        ]

    def detail_field(self, label: str, rendered: str) -> LogBuilder:
        """Append a trusted rich value under ``label`` as one table row."""
        self._items.append(("row", [rich_bold(label), rendered]))
        return self

    def field(
        self,
        label: str,
        value: object,
        *,
        escape: bool = True,
    ) -> LogBuilder:
        """Append one Field/Value row. The value is escaped by default."""
        v = esc(str(value)) if escape else str(value)
        return self.detail_field(label, v)

    def code_field(self, label: str, value: object) -> LogBuilder:
        """Append one Field/Value row whose value is an inline code span."""
        return self.detail_field(label, code(str(value)))

    def mention_field(
        self, label: str, user_id: int, name: str, username: str | None = None
    ) -> LogBuilder:
        """Append one Field/Value row whose value is a user mention."""
        return self.detail_field(label, user_ref(user_id, name, username))

    def link_field(self, label: str, text: str, url: str) -> LogBuilder:
        """Append one Field/Value row whose value is a hyperlink."""
        return self.detail_field(label, link(text, url))

    def raw(self, text: str) -> LogBuilder:
        """Append a free-form rich paragraph. Caller owns any inline markup."""
        self._items.append(("raw", paragraph(text)))
        return self

    def section(self) -> LogBuilder:
        """Insert a rich divider between field tables."""
        self._items.append(("divider", divider()))
        return self

    def date(self, ts: datetime | None = None, *, label: str = "Date") -> LogBuilder:
        """Append separate Date/Time rows. Defaults to utc_now().

        Date and time are never joined into one value: each gets its own row so
        log readers can scan either independently.
        """
        value = ts if ts is not None else utc_now()
        self.detail_field(label, fmt_date(value))
        return self.detail_field("Time", fmt_time(value))

    def build(self) -> str:
        """Return the assembled rich message with fields grouped into tables."""
        parts: list[str] = []
        rows: list[list[str]] = []

        def flush() -> None:
            if rows:
                parts.append(
                    table(
                        ["Field", "Value"],
                        rows,
                        compact=True,
                        striped=True,
                        raw_cells=True,
                    )
                )
                rows.clear()

        for kind, content in self._items:
            if kind == "row" and isinstance(content, list):
                rows.append(content)
                continue
            flush()
            if isinstance(content, str):
                parts.append(content)
        flush()
        return "\n".join(parts)

    def __str__(self) -> str:
        """Delegate to build so str(builder) works naturally."""
        return self.build()


# ──────────────────────── Moderation logs ─────────────────────── #


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


def _proof_table(rows: list[list[str]]) -> str:
    """Render the proof metadata as a compact Field/Value rich table.

    A Telegram caption only accepts inline text, so the table is a separate
    block directly after the slideshow rather than a figcaption child.
    """
    return table(
        ["Field", "Value"],
        rows,
        compact=True,
        striped=True,
        raw_cells=True,
    )


def proof_caption_new(
    target_id: int,
    admin_id: int,
    admin_fname: str,
    timestamp: datetime,
) -> str:
    """Render the initial proof metadata as a rich table below the slideshow."""
    return _proof_table(
        [
            [rich_bold("ID"), code(str(target_id))],
            [rich_bold("Admin"), esc(admin_fname)],
            [rich_bold("Admin ID"), code(str(admin_id))],
            [rich_bold("Commit date"), fmt_date(timestamp)],
            [rich_bold("Commit time"), fmt_time(timestamp)],
        ]
    )


def proof_caption_update(
    target_id: int,
    admin_id: int,
    admin_fname: str,
    original_ts: datetime,
    prev_proof_lnk: str | None = None,
) -> str:
    """Render replacement proof metadata as a rich table."""
    rows = [
        [rich_bold("ID"), code(str(target_id))],
        [rich_bold("Admin"), esc(admin_fname)],
        [rich_bold("Admin ID"), code(str(admin_id))],
    ]
    if prev_proof_lnk:
        rows.append([rich_bold("Previous"), link("View", prev_proof_lnk)])
    updated_at = utc_now()
    rows.extend(
        [
            [rich_bold("Commit date"), fmt_date(original_ts)],
            [rich_bold("Commit time"), fmt_time(original_ts)],
            [rich_bold("Update date"), fmt_date(updated_at)],
            [rich_bold("Update time"), fmt_time(updated_at)],
        ]
    )
    return _proof_table(rows)


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
        .detail_field("Group", f"{esc(chat_title)} ({code(str(chat_id))})")
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
        .detail_field("Group", f"{esc(chat_title)} ({code(str(chat_id))})")
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
        .detail_field("Group", f"{esc(chat_title)} ({code(str(chat_id))})")
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
        .detail_field("Group", f"{esc(chat_title)} ({code(str(chat_id))})")
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


# ──────────────────────── Appeals logs ─────────────────────── #


def appeal_received_log(
    target_id: int,
    target_fname: str,
    ban_id: str,
    appeal_link: str,
    *,
    appeal_excerpt: str = "",
) -> str:
    """Review card posted to MAIN_GROUP and the appeals destination.

    The forwarded original message is the usual path to the appeal text. If
    that forward failed, the excerpt keeps the reviewers from deciding a
    request they never saw.
    """
    b = LogBuilder(f"New {cfg.community_name} Appeal Request").detail_field(
        "User",
        f"{user_ref(target_id, target_fname)} (ID: {code(str(target_id))})",
    )
    b.code_field("Ban ID", ban_id)
    if appeal_link:
        b.link_field("Appeal", "View", appeal_link)
    elif appeal_excerpt:
        b.field("Appeal text", appeal_excerpt[:_APPEAL_EXCERPT_MAX])
    else:
        b.field("Appeal", "N/A")
    return (
        b.date(label="Submitted")
        .section()
        .raw("This appeal is pending review.")
        .build()
    )


def appeal_submitted_log(
    target_id: int,
    target_fname: str,
    ban_id: str,
    appeal_link: str,
) -> str:
    """Return the initial log message to post to LOG_CHANNEL when an appeal is submitted."""
    b = (
        LogBuilder(f"New {cfg.community_name} Appeal Submitted")
        .mention_field("User", target_id, target_fname)
        .code_field("ID", target_id)
        .section()
        .code_field("Ban ID", ban_id)
    )
    if appeal_link:
        b.link_field("Appeal", "View", appeal_link)
    else:
        b.field("Appeal", "N/A")
    return b.section().date(label="Submitted").build()


def _appeal_decision_edit(
    title: str,
    decision_label: str,
    target_id: int,
    target_fname: str,
    admin_id: int,
    admin_fname: str,
    ban_id: str,
    appeal_link: str = "",
    submitted_at: datetime | None = None,
) -> str:
    submitted_date = fmt_date(submitted_at) if submitted_at else "N/A"
    submitted_time = fmt_time(submitted_at) if submitted_at else "N/A"
    b = (
        LogBuilder(title)
        .mention_field("User", target_id, target_fname)
        .code_field("ID", target_id)
        .section()
        .code_field("Ban ID", ban_id)
    )
    if appeal_link:
        b.link_field("Appeal", "View", appeal_link)
    else:
        b.field("Appeal", "N/A")
    return (
        b.section()
        # * The values are pre-formatted digits: pass them through instead
        # * of escaping twice like the default field() does.
        .field("Submitted date", submitted_date, escape=False)
        .field("Submitted time", submitted_time, escape=False)
        .detail_field(decision_label, user_ref(admin_id, admin_fname))
        .date(label=f"{decision_label} at")
        .build()
    )


def appeal_approved_edit(
    target_id: int,
    target_fname: str,
    admin_id: int,
    admin_fname: str,
    ban_id: str,
    appeal_link: str = "",
    submitted_at: datetime | None = None,
) -> str:
    """Edited version of the submitted log shown when an appeal is approved."""
    return _appeal_decision_edit(
        f"{cfg.community_name} Appeal Approved",
        "Approved by",
        target_id,
        target_fname,
        admin_id,
        admin_fname,
        ban_id,
        appeal_link,
        submitted_at,
    )


def appeal_rejected_edit(
    target_id: int,
    target_fname: str,
    admin_id: int,
    admin_fname: str,
    ban_id: str,
    appeal_link: str = "",
    submitted_at: datetime | None = None,
) -> str:
    """Edited version of the submitted log shown when an appeal is rejected."""
    return _appeal_decision_edit(
        f"{cfg.community_name} Appeal Rejected",
        "Rejected by",
        target_id,
        target_fname,
        admin_id,
        admin_fname,
        ban_id,
        appeal_link,
        submitted_at,
    )


def appeal_unban_log(
    target_id: int,
    target_fname: str,
    admin_id: int,
    admin_fname: str,
    ban_id: str,
) -> str:
    """Separate unban log posted to LOG_CHANNEL when an appeal is approved."""
    return (
        LogBuilder(f"{cfg.community_name} Unban (via Appeal)")
        .mention_field("Admin", admin_id, admin_fname)
        .mention_field("User", target_id, target_fname)
        .code_field("User ID", target_id)
        .code_field("Ban ID", ban_id)
        .section()
        .date()
        .build()
    )


# ──────────────────────── Roles logs ─────────────────────── #


def promoted(
    target_id: int,
    target_fname: str,
    role: str,
    by_id: int,
    by_fname: str,
) -> str:
    """Unified promotion audit-log for Admin / Developer / Moderator.

    Single shape: the role is shown as a field below the user, not in the title.
    """
    role_label = db.users_roles.role_label(role)
    return (
        LogBuilder(f"New {cfg.community_name} Promoted")
        .mention_field("User", target_id, target_fname)
        .code_field("User ID", target_id)
        .field("Role", role_label)
        .section()
        .mention_field("Promoted by", by_id, by_fname)
        .code_field("ID", by_id)
        .section()
        .date()
        .build()
    )


def demoted(
    target_id: int,
    target_fname: str,
    role: str,
    by_id: int,
    by_fname: str,
) -> str:
    """Unified demotion audit-log: manual demote and ban/kick demote share one format."""
    role_label = db.users_roles.role_label(role)
    return (
        LogBuilder(f"{cfg.community_name} Demoted")
        .mention_field("User", target_id, target_fname)
        .code_field("User ID", target_id)
        .field("Role removed", role_label)
        .section()
        .mention_field("Demoted by", by_id, by_fname)
        .code_field("ID", by_id)
        .section()
        .date()
        .build()
    )


def ownership_transferred(
    new_owner_id: int,
    new_owner_fname: str,
    old_owner_id: int,
    old_owner_fname: str,
) -> str:
    """Ownership transfer audit-log."""
    return (
        LogBuilder(f"{cfg.community_name} Ownership Transferred")
        .mention_field("New Owner", new_owner_id, new_owner_fname)
        .code_field("ID", new_owner_id)
        .section()
        .mention_field("Previous Owner", old_owner_id, old_owner_fname)
        .code_field("ID", old_owner_id)
        .section()
        .date()
        .build()
    )


def promote_request_log(
    user_id: int,
    user_fname: str,
    username: str | None,
    request_id: str,
) -> str:
    """Promotion-request audit-log message sent to the Owner."""
    uname_part = f"@{username}" if username else "N/A"
    return (
        LogBuilder(f"{cfg.community_name} Promotion Request")
        .mention_field("User", user_id, user_fname)
        .code_field("ID", user_id)
        .field("Username", uname_part)
        .section()
        .code_field("Request ID", request_id)
        .date()
        .build()
    )


def promote_approved_log(
    target_id: int,
    target_fname: str,
    admin_id: int,
    admin_fname: str,
    request_id: str,
) -> str:
    """Audit-log written when a promotion request is approved."""
    return (
        LogBuilder(f"New {cfg.community_name} Admin Promoted")
        .mention_field("Admin", target_id, target_fname)
        .code_field("ID", target_id)
        .section()
        .mention_field("Promoted by", admin_id, admin_fname)
        .code_field("ID", admin_id)
        .section()
        .code_field("Request ID", request_id)
        .date()
        .build()
    )


def promote_rejected_log(
    target_id: int,
    target_fname: str,
    admin_id: int,
    admin_fname: str,
    request_id: str,
) -> str:
    """Audit-log written when a promotion request is rejected."""
    return (
        LogBuilder(f"{cfg.community_name} Promotion Request Rejected")
        .mention_field("User", target_id, target_fname)
        .code_field("ID", target_id)
        .section()
        .mention_field("Rejected by", admin_id, admin_fname)
        .code_field("ID", admin_id)
        .section()
        .code_field("Request ID", request_id)
        .date()
        .build()
    )


# ──────────────────────── Groups logs ─────────────────────── #


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
        .detail_field("Group", group_display)
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
        .detail_field("Group", f"{esc(chat_title)} (ID: {code(str(chat_id))})")
        .section()
        .detail_field(
            "Rejected by Owner",
            f"{user_ref(owner_id, owner_fname)} (ID: {code(str(owner_id))})",
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
