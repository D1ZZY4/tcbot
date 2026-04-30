# © Copyright 2024 - 2026 Transsion Core
# © Copyright 2024 - 2026 Dizzy
# © Copyright 2026 Aveum Apps

"""
Builders for messages posted to the federation log channel.
Every log entry must:

* Begin with a bold title line that names the event.
* Be followed by the branding line ``M.BRANDING_LINE`` exactly as defined in
  the PROMPT specification.
* Use HTML safely (links built through ``user_link``).
* Render UTC timestamps as ``DD-MM-YYYY | HH:MM`` via ``fmt_now`` /
  ``fmt_dt``.

Centralising these builders here keeps log copy consistent and makes it
trivial to audit every message that the bot sends to the channel.
"""
from __future__ import annotations

from datetime import datetime

from ..utils.format import fmt_dt, fmt_now, user_link
from .messages import M


# ---------------------------------------------------------------- affiliations

def new_affiliated_group(
    *,
    title: str,
    chat_id: int,
    owner_id: int,
    owner_name: str,
) -> str:
    return (
        "<b>New Affiliated Group</b>\n"
        f"{M.BRANDING_LINE}\n\n"
        f"Group: {title} (ID: {chat_id})\n"
        f"Added by Owner: {user_link(owner_id, owner_name)} (ID: {owner_id})\n\n"
        f"Date: {fmt_now()}"
    )


def affiliation_rejected(
    *, title: str, chat_id: int, owner_id: int, owner_name: str
) -> str:
    return (
        "<b>Affiliation Rejected &amp; Left</b>\n"
        f"{M.BRANDING_LINE}\n\n"
        f"Group: {title} (ID: {chat_id})\n"
        f"Rejected by Owner: {user_link(owner_id, owner_name)} (ID: {owner_id})\n\n"
        f"Date: {fmt_now()}"
    )


def group_disaffiliated(
    *, title: str, chat_id: int, by_user_id: int, by_user_name: str
) -> str:
    return (
        "<b>Group Disaffiliated</b>\n"
        f"{M.BRANDING_LINE}\n\n"
        f"Group: {title} (ID: {chat_id})\n"
        f"Removed by: {user_link(by_user_id, by_user_name)} (ID: {by_user_id})\n\n"
        f"Date: {fmt_now()}"
    )


def group_removed_bot(*, title: str, chat_id: int) -> str:
    return (
        "<b>Group Removed Bot</b>\n"
        f"{M.BRANDING_LINE}\n\n"
        f"Group: {title} (ID: {chat_id})\n\n"
        f"Date: {fmt_now()}"
    )


def group_perms_lost(*, title: str, chat_id: int) -> str:
    """Logged when the bot lost required admin permissions in an active group."""
    return (
        "<b>Group Permissions Lost</b>\n"
        f"{M.BRANDING_LINE}\n\n"
        f"Group: {title} (ID: {chat_id})\n"
        "The bot no longer holds the required admin permissions "
        "(delete messages, ban users, invite users).\n\n"
        f"Date: {fmt_now()}"
    )


# ---------------------------------------------------------------------- bans

def new_ban(
    *,
    admin_id: int,
    admin_name: str,
    target_id: int,
    target_name: str,
    reason: str,
    timestamp: datetime,
) -> str:
    return (
        "<b>New Transsion Core Ban</b>\n"
        f"{M.BRANDING_LINE}\n\n"
        f"Admin: {user_link(admin_id, admin_name)}\n\n"
        f"User: {user_link(target_id, target_name)}\n"
        f"User ID: {target_id}\n"
        f"Reason: {reason}\n\n"
        f"Commit at: {fmt_dt(timestamp)}"
    )


def updated_ban(
    *,
    admin_id: int,
    admin_name: str,
    previous_admin_id: int,
    previous_admin_name: str,
    target_id: int,
    target_name: str,
    reason: str,
    original_timestamp: datetime,
    update_timestamp: datetime,
) -> str:
    return (
        "<b>New Transsion Core Ban (Update)</b>\n"
        f"{M.BRANDING_LINE}\n\n"
        f"Admin: {user_link(admin_id, admin_name)}\n"
        f"Previous Admin: {user_link(previous_admin_id, previous_admin_name)}\n\n"
        f"User: {user_link(target_id, target_name)}\n"
        f"User ID: {target_id}\n"
        f"Reason: {reason}\n\n"
        f"Commit at: {fmt_dt(original_timestamp)}\n"
        f"Update at: {fmt_dt(update_timestamp)}"
    )


def unban(
    *,
    admin_id: int,
    admin_name: str,
    target_id: int,
    target_name: str,
    reason: str | None = None,
) -> str:
    reason_line = f"\nUnban Reason: {reason}" if reason else ""
    return (
        "<b>Transsion Core Unban</b>\n"
        f"{M.BRANDING_LINE}\n\n"
        f"Admin: {user_link(admin_id, admin_name)}\n\n"
        f"User: {user_link(target_id, target_name)}\n"
        f"User ID: {target_id}{reason_line}\n\n"
        f"Date: {fmt_now()}"
    )


def enforcement_summary(*, success: int, failure: int, action: str = "Enforced") -> str:
    """Append a one-line cross-group enforcement summary to a log message."""
    return (
        f"\n\n{action} in {success} group(s); failed in {failure} group(s)."
    )


# ------------------------------------------------------------------- appeals

def appeal_submitted(
    *,
    user_id: int,
    user_name: str,
    ban_id: str,
    appeal_link: str,
    submitted_at: datetime,
) -> str:
    return (
        "<b>New Appeal Submitted</b>\n"
        f"{M.BRANDING_LINE}\n\n"
        f"User: {user_link(user_id, user_name)} (ID: {user_id})\n"
        f"Ban ID: {ban_id}\n"
        f'Appeal: <a href="{appeal_link}">{appeal_link}</a>\n\n'
        f"Date: {fmt_dt(submitted_at)}"
    )


def appeal_approved(
    *,
    user_id: int,
    user_name: str,
    ban_id: str,
    reviewer_id: int,
    reviewer_name: str,
) -> str:
    return (
        "<b>Appeal Approved</b>\n"
        f"{M.BRANDING_LINE}\n\n"
        f"User: {user_link(user_id, user_name)} (ID: {user_id})\n"
        f"Ban ID: {ban_id}\n"
        f"Approved by: {user_link(reviewer_id, reviewer_name)}\n\n"
        f"Date: {fmt_now()}"
    )


def appeal_rejected(
    *,
    user_id: int,
    user_name: str,
    ban_id: str,
    reviewer_id: int,
    reviewer_name: str,
) -> str:
    return (
        "<b>Appeal Rejected</b>\n"
        f"{M.BRANDING_LINE}\n\n"
        f"User: {user_link(user_id, user_name)} (ID: {user_id})\n"
        f"Ban ID: {ban_id}\n"
        f"Rejected by: {user_link(reviewer_id, reviewer_name)}\n\n"
        f"Date: {fmt_now()}"
    )


# -------------------------------------------------------------- admin events

def admin_promoted(
    *,
    target_id: int,
    target_name: str,
    promoted_by_id: int,
    promoted_by_name: str,
) -> str:
    return (
        "<b>New Transsion Core Admin Promoted</b>\n"
        f"{M.BRANDING_LINE}\n\n"
        f"Admin: {user_link(target_id, target_name)}\n"
        f"ID: {target_id}\n\n"
        f"Promoted by Owner: "
        f"{user_link(promoted_by_id, promoted_by_name)}\n"
        f"ID: {promoted_by_id}\n\n"
        f"Date: {fmt_now()}"
    )


def admin_demoted(
    *,
    target_id: int,
    target_name: str,
    demoted_by_id: int,
    demoted_by_name: str,
) -> str:
    return (
        "<b>Transsion Core Admin Demoted</b>\n"
        f"{M.BRANDING_LINE}\n\n"
        f"Admin: {user_link(target_id, target_name)} (ID: {target_id})\n\n"
        f"Demoted by Owner: "
        f"{user_link(demoted_by_id, demoted_by_name)}\n"
        f"ID: {demoted_by_id}\n\n"
        f"Date: {fmt_now()}"
    )


def ownership_transferred(
    *,
    new_owner_id: int,
    new_owner_name: str,
    old_owner_id: int,
    old_owner_name: str,
) -> str:
    return (
        "<b>Transsion Core Ownership Transferred</b>\n"
        f"{M.BRANDING_LINE}\n\n"
        f"New Owner: {user_link(new_owner_id, new_owner_name)} (ID: {new_owner_id})\n"
        f"Previous Owner: "
        f"{user_link(old_owner_id, old_owner_name)} (ID: {old_owner_id})\n\n"
        f"Date: {fmt_now()}"
    )


def promotion_request_sent(
    *,
    requested_by_id: int,
    requested_by_name: str,
    target_id: int,
    target_name: str,
) -> str:
    return (
        "<b>Promotion Request Sent</b>\n"
        f"{M.BRANDING_LINE}\n\n"
        f"Requested by: {user_link(requested_by_id, requested_by_name)}\n"
        f"ID: {requested_by_id}\n\n"
        f"Target: {user_link(target_id, target_name)}\n"
        f"ID: {target_id}\n\n"
        f"Date: {fmt_now()}"
    )


def promotion_request_notification(
    *,
    request_id: str,
    requested_by_id: int,
    requested_by_name: str,
    target_id: int,
    target_name: str,
) -> str:
    return (
        "<b>New Promotion Request</b>\n"
        f"{M.BRANDING_LINE}\n\n"
        f"Requested by: {user_link(requested_by_id, requested_by_name)}\n"
        f"ID: {requested_by_id}\n\n"
        f"Target: {user_link(target_id, target_name)}\n"
        f"ID: {target_id}\n"
        f"Request ID: {request_id}\n\n"
        f"Date: {fmt_now()}"
    )


def promotion_request_rejected_log(
    *, request_id: str, reviewer_id: int, reviewer_name: str
) -> str:
    return (
        "<b>Promotion Request Rejected</b>\n"
        f"{M.BRANDING_LINE}\n\n"
        f"Rejected by Owner: {user_link(reviewer_id, reviewer_name)}\n"
        f"ID: {reviewer_id}\n"
        f"Request ID: {request_id}\n\n"
        f"Date: {fmt_now()}"
    )


# ------------------------------------------------------------------ broadcast

def broadcast_log(
    *,
    admin_id: int,
    admin_name: str,
    text: str,
    success: int,
    failure: int,
) -> str:
    return (
        "<b>Broadcast Sent</b>\n"
        f"{M.BRANDING_LINE}\n\n"
        f"Admin: {user_link(admin_id, admin_name)}\n"
        f"Message: {text[:100]}\n\n"
        f"Groups reached: {success}\n"
        f"Failed groups: {failure}\n\n"
        f"Date: {fmt_now()}"
    )


# ----------------------------------------------------- appeal review (group)

def appeal_review_message(
    *,
    user_id: int,
    user_name: str,
    ban_id: str,
    appeal_link: str,
    submitted_at: datetime,
) -> str:
    return (
        "<b>New Appeal Request</b>\n\n"
        f"User: {user_link(user_id, user_name)} (ID: {user_id})\n"
        f"Ban ID: {ban_id}\n"
        f'Appeal: <a href="{appeal_link}">{appeal_link}</a>\n\n'
        f"Submitted: {fmt_dt(submitted_at)}\n"
        f"{M.APPEAL_PENDING_REVIEW}"
    )


# -------------------------------------------------------------- proof captions

def proof_caption_new(
    *,
    target_id: int,
    admin_id: int,
    admin_name: str,
    timestamp: datetime,
) -> str:
    return (
        f"ID: {target_id}\n\n"
        f"Admin: {user_link(admin_id, admin_name)}\n"
        f"Admin ID: {admin_id}\n\n"
        f"Commit at: {fmt_dt(timestamp)}"
    )


def proof_caption_update(
    *,
    target_id: int,
    admin_id: int,
    admin_name: str,
    previous_proof_link: str,
    original_timestamp: datetime,
    update_timestamp: datetime,
) -> str:
    return (
        f"ID: {target_id}\n\n"
        f"Admin: {user_link(admin_id, admin_name)}\n"
        f"Admin ID: {admin_id}\n\n"
        f'Previous: <a href="{previous_proof_link}">Click Here</a>\n\n'
        f"Commit at: {fmt_dt(original_timestamp)}\n"
        f"Update at: {fmt_dt(update_timestamp)}"
    )
