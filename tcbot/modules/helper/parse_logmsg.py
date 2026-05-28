# © Copyright 2024 - 2026 Transsion Core
# © Copyright 2024 - 2026 Dizzy
# © Copyright 2026 Aveum Apps

"""Log-message template builders for moderation, appeals, role changes, and groups."""

from __future__ import annotations

from datetime import datetime

from tcbot import cfg
from tcbot.database.roles_db import ROLE_LABEL as _ROLE_LABELS
from tcbot.modules.helper.formatter import code, esc, link, mention
from tcbot.utils.timedate_format import fmt_dt, utc_now

# ─────────────────────────── LogBuilder ─────────────────────────── #
# * Fluent builder for HTML audit-log messages with consistent layout.
# * Title is rendered on its own line, separated from fields by a blank line.
# * All `field(...)` values are HTML-escaped by default — pass `escape=False`
# *   only when interpolating already-trusted markup (e.g. mention/link/code).
# * Use `.section()` to start a new logical block (adds a blank separator).


class LogBuilder:
    """Fluent builder for HTML audit-log messages used by the parse_logmsg helpers."""

    __slots__ = ("_lines",)

    def __init__(self, title: str) -> None:
        self._lines: list[str] = [str(title), ""]

    def field(
        self,
        label: str,
        value: object,
        *,
        escape: bool = True,
    ) -> LogBuilder:
        """Append a `Label: value` line. The value is HTML-escaped by default."""
        v = esc(str(value)) if escape else str(value)
        self._lines.append(f"{label}: {v}")
        return self

    def code_field(self, label: str, value: object) -> LogBuilder:
        """Append a `Label: <code>value</code>` line."""
        self._lines.append(f"{label}: {code(str(value))}")
        return self

    def mention_field(self, label: str, user_id: int, name: str) -> LogBuilder:
        """Append a `Label: mention(user_id, name)` line."""
        self._lines.append(f"{label}: {mention(user_id, name)}")
        return self

    def link_field(self, label: str, text: str, url: str) -> LogBuilder:
        """Append a `Label: <a href=url>text</a>` line."""
        self._lines.append(f"{label}: {link(text, url)}")
        return self

    def raw(self, text: str) -> LogBuilder:
        """Append a raw HTML line. Caller is responsible for escaping user input."""
        self._lines.append(text)
        return self

    def section(self) -> LogBuilder:
        """Insert a blank separator line between sections."""
        self._lines.append("")
        return self

    def user_block(
        self,
        target_id: int,
        target_fname: str,
        *,
        user_label: str = "User",
        id_label: str = "User ID",
    ) -> LogBuilder:
        """Append the canonical `Label: mention` + `User ID: <id>` pair."""
        self._lines.append(f"{user_label}: {mention(target_id, target_fname)}")
        self._lines.append(f"{id_label}: {target_id}")
        return self

    def actor_block(
        self,
        actor_id: int,
        actor_fname: str,
        *,
        label: str = "Admin",
        id_label: str = "ID",
    ) -> LogBuilder:
        """Append the canonical `Label: mention` + `ID: <id>` pair for an actor."""
        self._lines.append(f"{label}: {mention(actor_id, actor_fname)}")
        self._lines.append(f"{id_label}: {actor_id}")
        return self

    def date(self, ts: datetime | None = None, *, label: str = "Date") -> LogBuilder:
        """Append a `Label: dd-mm-yyyy | HH:MM` line. Defaults to utc_now()."""
        self._lines.append(f"{label}: {fmt_dt(ts if ts is not None else utc_now())}")
        return self

    def build(self) -> str:
        """Return the assembled HTML message."""
        return "\n".join(self._lines)

    def __str__(self) -> str:
        return self.build()


# ──────────────────────────── Ban logs ──────────────────────────── #


def ban_log(
    target_id: int,
    target_fname: str,
    admin_id: int,
    admin_fname: str,
    reason: str,
    ban_id: str,
    proof_lnk: str | None = None,
    timestamp: datetime | None = None,
) -> str:
    """New federation-ban audit-log message."""
    b = (
        LogBuilder(f"New {cfg.community_name} Ban")
        .mention_field("Admin", admin_id, admin_fname)
        .section()
        .mention_field("User", target_id, target_fname)
        .field("User ID", target_id, escape=False)
        .field("Ban ID", ban_id, escape=False)
        .field("Reason", reason)
        .section()
        .date(timestamp, label="Commit at")
    )
    if proof_lnk:
        b.raw(f'<a href="{proof_lnk}">View Proof</a>')
    return b.build()


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
    proof_lnk: str | None = None,
    prev_proof_lnk: str | None = None,
    update_count: int = 0,
) -> str:
    """Update-ban audit-log message."""
    b = (
        LogBuilder(f"Update {cfg.community_name} Ban")
        .mention_field("Admin", new_admin_id, new_admin_fname)
        .mention_field("Previous Admin", old_admin_id, old_admin_fname)
        .section()
        .mention_field("User", target_id, target_fname)
        .field("User ID", target_id, escape=False)
        .field("Ban ID", ban_id, escape=False)
        .field("Reason", reason)
        .section()
        .date(original_ts, label="Commit at")
        .date(label="Update at")
    )
    if prev_proof_lnk:
        b.raw(f'Previous Proof: <a href="{prev_proof_lnk}">Click Here</a>')
    if proof_lnk:
        b.raw(f'<a href="{proof_lnk}">View Proof</a>')
    return b.build()


# ───────────────────────── Proof captions ───────────────────────── #


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
        .field("Admin ID", admin_id, escape=False)
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
        .field("Admin ID", admin_id, escape=False)
    )
    if prev_proof_lnk:
        b.section().raw(f'Previous: <a href="{prev_proof_lnk}">Click Here</a>')
    return (
        b.section().date(original_ts, label="Commit at").date(label="Update at").build()
    )


# ──────────────────────────── Mute logs ─────────────────────────── #


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
        .field("User ID", target_id, escape=False)
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
        .field("User ID", target_id, escape=False)
        .section()
        .date()
        .build()
    )


# ──────────────────────────── Kick log ──────────────────────────── #


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
        .field("User ID", target_id, escape=False)
        .field("Reason", reason)
        .raw(f"Group: {esc(chat_title)} ({code(str(chat_id))})")
        .section()
        .date()
        .build()
    )


# ─────────────────────────── Warn logs ──────────────────────────── #


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
        .field("User ID", target_id, escape=False)
        .field("Reason", reason)
        .field("Warnings", f"{count}/{warn_limit}", escape=False)
        .raw(f"Group: {esc(chat_title)} ({code(str(chat_id))})")
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
        .field("User ID", target_id, escape=False)
        .field("Warnings now", f"{new_count}/{warn_limit}", escape=False)
        .raw(f"Group: {esc(chat_title)} ({code(str(chat_id))})")
        .section()
        .date()
        .build()
    )


# ──────────────────────────── Unban log ─────────────────────────── #


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
        .field("User ID", target_id, escape=False)
    )
    if reason:
        b.field("Unban Reason", reason)
    return b.section().date().build()


# ─────────────────────────── Appeal logs ────────────────────────── #


def appeal_received_log(
    target_id: int,
    target_fname: str,
    ban_id: str,
    appeal_link: str,
) -> str:
    """Review card posted to APPEAL_DISCUSSION_TOPIC."""
    b = LogBuilder(f"New {cfg.community_name} Appeal Request").raw(
        f"User: {mention(target_id, target_fname)} (ID: {target_id})"
    )
    b.field("Ban ID", ban_id, escape=False)
    if appeal_link:
        b.link_field("Appeal", "View", appeal_link)
    else:
        b.field("Appeal", "N/A", escape=False)
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
    """Initial log posted to LOG_CHANNEL when an appeal is submitted."""
    b = (
        LogBuilder(f"New {cfg.community_name} Appeal Submitted")
        .mention_field("User", target_id, target_fname)
        .field("ID", target_id, escape=False)
        .section()
        .field("Ban ID", ban_id, escape=False)
    )
    if appeal_link:
        b.link_field("Appeal", "View", appeal_link)
    else:
        b.field("Appeal", "N/A", escape=False)
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
    submitted_str = fmt_dt(submitted_at) if submitted_at else "N/A"
    b = (
        LogBuilder(title)
        .mention_field("User", target_id, target_fname)
        .field("ID", target_id, escape=False)
        .section()
        .field("Ban ID", ban_id, escape=False)
    )
    if appeal_link:
        b.link_field("Appeal", "View", appeal_link)
    else:
        b.field("Appeal", "N/A", escape=False)
    return (
        b.section()
        .field("Submitted", submitted_str, escape=False)
        .raw(f"{decision_label}: {mention(admin_id, admin_fname)}")
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
        .field("User ID", target_id, escape=False)
        .field("Ban ID", ban_id, escape=False)
        .section()
        .date()
        .build()
    )


# ──────────────────── Role / Admin management ───────────────────── #


def _role_title(role: str) -> str:
    """Return the human-readable label for a role string."""
    return _ROLE_LABELS.get(role, role.capitalize())


def promoted(
    target_id: int,
    target_fname: str,
    role: str,
    by_id: int,
    by_fname: str,
) -> str:
    """Promotion audit-log: a user receives `role` from another user."""
    role_label = _role_title(role)
    return (
        LogBuilder(f"New {cfg.community_name} {role_label} Promoted")
        .mention_field(role_label, target_id, target_fname)
        .field("ID", target_id, escape=False)
        .section()
        .mention_field("Promoted by", by_id, by_fname)
        .field("ID", by_id, escape=False)
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
    *,
    trigger: str | None = None,
) -> str:
    """
    Demotion audit-log.

    * Manual: trigger=None → "{community} {Role} Demoted"
    * Auto-demote on ban/kick: trigger="ban" or "kick" → "{community} Auto-Demote"
    """
    role_label = _role_title(role)
    if trigger is None:
        return (
            LogBuilder(f"{cfg.community_name} {role_label} Demoted")
            .mention_field("User", target_id, target_fname)
            .field("ID", target_id, escape=False)
            .field("Role removed", role_label, escape=False)
            .section()
            .mention_field("Demoted by", by_id, by_fname)
            .field("ID", by_id, escape=False)
            .section()
            .date()
            .build()
        )

    trigger_label = {"ban": "Banned", "kick": "Kicked"}.get(
        trigger, trigger.capitalize()
    )
    return (
        LogBuilder(f"{cfg.community_name} Auto-Demote")
        .mention_field("User", target_id, target_fname)
        .field("ID", target_id, escape=False)
        .field("Role removed", role_label, escape=False)
        .field("Trigger", trigger_label, escape=False)
        .section()
        .mention_field("By", by_id, by_fname)
        .field("ID", by_id, escape=False)
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
        .field("ID", new_owner_id, escape=False)
        .section()
        .mention_field("Previous Owner", old_owner_id, old_owner_fname)
        .field("ID", old_owner_id, escape=False)
        .section()
        .date()
        .build()
    )


# ────────────────────── Promotion request logs ──────────────────── #


def promote_request_log(
    user_id: int,
    user_fname: str,
    username: str | None,
    request_id: str,
) -> str:
    """Promotion-request audit-log message sent to the Founder."""
    uname_part = f"@{username}" if username else "N/A"
    return (
        LogBuilder(f"{cfg.community_name} Promotion Request")
        .mention_field("User", user_id, user_fname)
        .field("ID", user_id, escape=False)
        .field("Username", uname_part)
        .section()
        .field("Request ID", request_id, escape=False)
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
        .field("ID", target_id, escape=False)
        .section()
        .mention_field("Promoted by", admin_id, admin_fname)
        .field("ID", admin_id, escape=False)
        .section()
        .field("Request ID", request_id, escape=False)
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
        .field("ID", target_id, escape=False)
        .section()
        .mention_field("Rejected by", admin_id, admin_fname)
        .field("ID", admin_id, escape=False)
        .section()
        .field("Request ID", request_id, escape=False)
        .date()
        .build()
    )


# ────────────────────── Group connection logs ───────────────────── #


def group_connected_log(
    chat_id: int,
    chat_title: str,
    owner_id: int,
    owner_fname: str,
    chat_username: str | None = None,
) -> str:
    """New federation-connected-group audit-log message."""
    if chat_username:
        group_display = (
            f'<a href="https://t.me/{esc(chat_username)}">{esc(chat_title)}</a>'
        )
    else:
        group_display = esc(chat_title)
    return (
        LogBuilder(f"New {cfg.community_name} Connected Group")
        .raw(f"Group: {group_display}")
        .field("ID", chat_id, escape=False)
        .section()
        .mention_field("Added by Owner", owner_id, owner_fname)
        .field("ID", owner_id, escape=False)
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
        .raw(f"Group: {esc(chat_title)} (ID: {chat_id})")
        .section()
        .raw(f"Rejected by Owner: {mention(owner_id, owner_fname)} (ID: {owner_id})")
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
        .field("ID", chat_id, escape=False)
        .section()
        .mention_field("Removed by", actor_id, actor_fname)
        .field("ID", actor_id, escape=False)
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
        .field("ID", chat_id, escape=False)
        .section()
        .date()
        .build()
    )


# ───────────────────────── Broadcast logs ───────────────────────── #


def broadcast_log(
    admin_id: int,
    admin_fname: str,
    message_preview: str,
    success: int,
    failed: int,
) -> str:
    """Broadcast audit-log message."""
    preview = message_preview[:100]
    return (
        LogBuilder(f"{cfg.community_name} Broadcast Sent")
        .mention_field("Admin", admin_id, admin_fname)
        .field("Message", preview)
        .section()
        .field("Groups reached", success, escape=False)
        .field("Failed groups", failed, escape=False)
        .section()
        .date()
        .build()
    )
