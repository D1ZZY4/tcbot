# © Copyright 2024 - 2026 Transsion Core
# © Copyright 2024 - 2026 Dizzy
# © Copyright 2026 Aveum Apps

"""Log-message template builders for all moderation actions, appeals, and role changes."""

from __future__ import annotations

from tcbot import cfg
from tcbot.database.roles_db import ROLE_LABEL as _ROLE_LABELS
from tcbot.modules.helper.formatter import esc, link, mention
from tcbot.utils.timedate_format import fmt_dt, utc_now

# ──────────────────────────── Ban logs ──────────────────────────── #


def ban_log(
    target_id: int,
    target_fname: str,
    admin_id: int,
    admin_fname: str,
    reason: str,
    ban_id: str,
    proof_lnk: str | None = None,
    timestamp=None,
) -> str:
    ts = timestamp if timestamp is not None else utc_now()
    dt = fmt_dt(ts)
    proof_part = f'\n<a href="{proof_lnk}">View Proof</a>' if proof_lnk else ""
    return (
        f"New {cfg.community_name} Ban\n\n"
        f"Admin: {mention(admin_id, admin_fname)}\n\n"
        f"User: {mention(target_id, target_fname)}\n"
        f"User ID: {target_id}\n"
        f"Ban ID: {ban_id}\n"
        f"Reason: {esc(reason)}\n\n"
        f"Commit at: {dt}"
        f"{proof_part}"
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
    original_ts,
    proof_lnk: str | None = None,
    prev_proof_lnk: str | None = None,
    update_count: int = 0,
) -> str:
    original_dt = fmt_dt(original_ts)
    update_str = fmt_dt(utc_now())
    prev_part = (
        f'\nPrevious Proof: <a href="{prev_proof_lnk}">Click Here</a>'
        if prev_proof_lnk
        else ""
    )
    proof_part = f'\n<a href="{proof_lnk}">View Proof</a>' if proof_lnk else ""
    return (
        f"Update {cfg.community_name} Ban\n\n"
        f"Admin: {mention(new_admin_id, new_admin_fname)}\n"
        f"Previous Admin: {mention(old_admin_id, old_admin_fname)}\n\n"
        f"User: {mention(target_id, target_fname)}\n"
        f"User ID: {target_id}\n"
        f"Ban ID: {ban_id}\n"
        f"Reason: {esc(reason)}\n\n"
        f"Commit at: {original_dt}\n"
        f"Update at: {update_str}"
        f"{prev_part}"
        f"{proof_part}"
    )


# ───────────────────────── Proof captions ───────────────────────── #


def proof_caption_new(
    target_id: int,
    admin_id: int,
    admin_fname: str,
    timestamp,
) -> str:
    dt = fmt_dt(timestamp)
    return (
        f"ID: {target_id}\n\n"
        f"Admin: {mention(admin_id, admin_fname)}\n"
        f"Admin ID: {admin_id}\n\n"
        f"Commit at: {dt}"
    )


def proof_caption_update(
    target_id: int,
    admin_id: int,
    admin_fname: str,
    original_ts,
    prev_proof_lnk: str | None = None,
) -> str:
    original_dt = fmt_dt(original_ts)
    update_dt = fmt_dt(utc_now())
    prev_part = (
        f'\n\nPrevious: <a href="{prev_proof_lnk}">Click Here</a>'
        if prev_proof_lnk
        else ""
    )
    return (
        f"ID: {target_id}\n\n"
        f"Admin: {mention(admin_id, admin_fname)}\n"
        f"Admin ID: {admin_id}"
        f"{prev_part}\n\n"
        f"Commit at: {original_dt}\n"
        f"Update at: {update_dt}"
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
    dt = fmt_dt(utc_now())
    return (
        f"{cfg.community_name} Muted\n\n"
        f"Admin: {mention(admin_id, admin_fname)}\n"
        f"User: {mention(target_id, target_fname)}\n"
        f"User ID: {target_id}\n"
        f"Reason: {esc(reason)}\n"
        f"Duration: {esc(duration_str)}\n\n"
        f"Date: {dt}"
    )


def unmute_log(
    target_id: int,
    target_fname: str,
    admin_id: int,
    admin_fname: str,
) -> str:
    dt = fmt_dt(utc_now())
    return (
        f"{cfg.community_name} Federation Unmute\n\n"
        f"Admin: {mention(admin_id, admin_fname)}\n"
        f"User: {mention(target_id, target_fname)}\n"
        f"User ID: {target_id}\n\n"
        f"Date: {dt}"
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
    dt = fmt_dt(utc_now())
    return (
        f"{cfg.community_name} Kicked\n\n"
        f"Admin: {mention(admin_id, admin_fname)}\n"
        f"User: {mention(target_id, target_fname)}\n"
        f"User ID: {target_id}\n"
        f"Reason: {esc(reason)}\n"
        f"Group: {esc(chat_title)} (<code>{chat_id}</code>)\n\n"
        f"Date: {dt}"
    )


# ──────────────────────────── Warn log ──────────────────────────── #


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
    dt = fmt_dt(utc_now())
    return (
        f"{cfg.community_name} Warn\n\n"
        f"Admin: {mention(admin_id, admin_fname)}\n"
        f"User: {mention(target_id, target_fname)}\n"
        f"User ID: {target_id}\n"
        f"Reason: {esc(reason)}\n"
        f"Warnings: {count}/{warn_limit}\n"
        f"Group: {esc(chat_title)} (<code>{chat_id}</code>)\n\n"
        f"Date: {dt}"
    )


# ─────────────────────────── Unwarn log ─────────────────────────── #


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
    dt = fmt_dt(utc_now())
    return (
        f"{cfg.community_name} Unwarn\n\n"
        f"Admin: {mention(admin_id, admin_fname)}\n"
        f"User: {mention(target_id, target_fname)}\n"
        f"User ID: {target_id}\n"
        f"Warnings now: {new_count}/{warn_limit}\n"
        f"Group: {esc(chat_title)} (<code>{chat_id}</code>)\n\n"
        f"Date: {dt}"
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
    dt = fmt_dt(utc_now())
    reason_part = f"\nUnban Reason: {esc(reason)}" if reason else ""
    return (
        f"{cfg.community_name} Unban\n\n"
        f"Admin: {mention(admin_id, admin_fname)}\n"
        f"User: {mention(target_id, target_fname)}\n"
        f"User ID: {target_id}"
        f"{reason_part}\n\n"
        f"Date: {dt}"
    )


# ─────────────────────────── Appeal logs ────────────────────────── #


def appeal_received_log(
    target_id: int,
    target_fname: str,
    ban_id: str,
    appeal_link: str,
) -> str:
    """Review card posted to APPEAL_DISCUSSION_TOPIC (thread 11)."""
    dt = fmt_dt(utc_now())
    return (
        f"New {cfg.community_name} Appeal Request\n\n"
        f"User: {mention(target_id, target_fname)} (ID: {target_id})\n"
        f"Ban ID: {ban_id}\n"
        f"Appeal: {link('View', appeal_link) if appeal_link else 'N/A'}\n"
        f"Submitted: {dt}\n\n"
        f"This appeal is pending review."
    )


def appeal_submitted_log(
    target_id: int,
    target_fname: str,
    ban_id: str,
    appeal_link: str,
) -> str:
    """Initial log posted to LOG_CHANNEL when appeal is submitted."""
    dt = fmt_dt(utc_now())
    return (
        f"New {cfg.community_name} Appeal Submitted\n\n"
        f"User: {mention(target_id, target_fname)}\n"
        f"ID: {target_id}\n\n"
        f"Ban ID: {ban_id}\n"
        f"Appeal: {link('View', appeal_link) if appeal_link else 'N/A'}\n\n"
        f"Submitted: {dt}"
    )


def appeal_approved_edit(
    target_id: int,
    target_fname: str,
    admin_id: int,
    admin_fname: str,
    ban_id: str,
    appeal_link: str = "",
    submitted_at=None,
) -> str:
    """Edited version of the submitted log - shown when appeal is approved."""
    submitted_str = fmt_dt(submitted_at) if submitted_at else "N/A"
    approved_str = fmt_dt(utc_now())
    return (
        f"{cfg.community_name} Appeal Approved\n\n"
        f"User: {mention(target_id, target_fname)}\n"
        f"ID: {target_id}\n\n"
        f"Ban ID: {ban_id}\n"
        f"Appeal: {link('View', appeal_link) if appeal_link else 'N/A'}\n\n"
        f"Submitted: {submitted_str}\n"
        f"Approved by: {mention(admin_id, admin_fname)}\n"
        f"Approved at: {approved_str}"
    )


def appeal_rejected_edit(
    target_id: int,
    target_fname: str,
    admin_id: int,
    admin_fname: str,
    ban_id: str,
    appeal_link: str = "",
    submitted_at=None,
) -> str:
    """Edited version of the submitted log - shown when appeal is rejected."""
    submitted_str = fmt_dt(submitted_at) if submitted_at else "N/A"
    rejected_str = fmt_dt(utc_now())
    return (
        f"{cfg.community_name} Appeal Rejected\n\n"
        f"User: {mention(target_id, target_fname)}\n"
        f"ID: {target_id}\n\n"
        f"Ban ID: {ban_id}\n"
        f"Appeal: {link('View', appeal_link) if appeal_link else 'N/A'}\n\n"
        f"Submitted: {submitted_str}\n"
        f"Rejected by: {mention(admin_id, admin_fname)}\n"
        f"Rejected at: {rejected_str}"
    )


def appeal_unban_log(
    target_id: int,
    target_fname: str,
    admin_id: int,
    admin_fname: str,
    ban_id: str,
) -> str:
    """Separate unban log posted to LOG_CHANNEL when appeal is approved."""
    dt = fmt_dt(utc_now())
    return (
        f"{cfg.community_name} Unban (via Appeal)\n\n"
        f"Admin: {mention(admin_id, admin_fname)}\n"
        f"User: {mention(target_id, target_fname)}\n"
        f"User ID: {target_id}\n"
        f"Ban ID: {ban_id}\n\n"
        f"Date: {dt}"
    )


# ────────────────────── Admin management logs ───────────────────── #


def admin_promoted(
    target_id: int,
    target_fname: str,
    admin_id: int,
    admin_fname: str,
) -> str:
    dt = fmt_dt(utc_now())
    return (
        f"New {cfg.community_name} Admin Promoted\n\n"
        f"Admin: {mention(target_id, target_fname)}\n"
        f"ID: {target_id}\n\n"
        f"Promoted by Owner: {mention(admin_id, admin_fname)}\n"
        f"ID: {admin_id}\n\n"
        f"Date: {dt}"
    )


def admin_demoted(
    target_id: int,
    target_fname: str,
    admin_id: int,
    admin_fname: str,
) -> str:
    dt = fmt_dt(utc_now())
    return (
        f"{cfg.community_name} Admin Demoted\n\n"
        f"Admin: {mention(target_id, target_fname)}\n"
        f"ID: {target_id}\n\n"
        f"Demoted by Owner: {mention(admin_id, admin_fname)}\n"
        f"ID: {admin_id}\n\n"
        f"Date: {dt}"
    )


def ownership_transferred(
    new_owner_id: int,
    new_owner_fname: str,
    old_owner_id: int,
    old_owner_fname: str,
) -> str:
    dt = fmt_dt(utc_now())
    return (
        f"{cfg.community_name} Ownership Transferred\n\n"
        f"New Owner: {mention(new_owner_id, new_owner_fname)}\n"
        f"ID: {new_owner_id}\n\n"
        f"Previous Owner: {mention(old_owner_id, old_owner_fname)}\n"
        f"ID: {old_owner_id}\n\n"
        f"Date: {dt}"
    )


def promo_request_log(
    user_id: int,
    user_fname: str,
    username: str | None,
    request_id: str,
) -> str:
    dt = fmt_dt(utc_now())
    uname_part = f"@{username}" if username else "N/A"
    return (
        f"{cfg.community_name} Promotion Request\n\n"
        f"User: {mention(user_id, user_fname)}\n"
        f"ID: {user_id}\n"
        f"Username: {uname_part}\n\n"
        f"Request ID: {request_id}\n"
        f"Date: {dt}"
    )


def promo_approved_log(
    target_id: int,
    target_fname: str,
    admin_id: int,
    admin_fname: str,
    request_id: str,
) -> str:
    dt = fmt_dt(utc_now())
    return (
        f"New {cfg.community_name} Admin Promoted\n\n"
        f"Admin: {mention(target_id, target_fname)}\n"
        f"ID: {target_id}\n\n"
        f"Promoted by Owner: {mention(admin_id, admin_fname)}\n"
        f"ID: {admin_id}\n\n"
        f"Request ID: {request_id}\n"
        f"Date: {dt}"
    )


def promo_rejected_log(
    target_id: int,
    target_fname: str,
    admin_id: int,
    admin_fname: str,
    request_id: str,
) -> str:
    dt = fmt_dt(utc_now())
    return (
        f"{cfg.community_name} Promotion Request Rejected\n\n"
        f"User: {mention(target_id, target_fname)}\n"
        f"ID: {target_id}\n\n"
        f"Rejected by: {mention(admin_id, admin_fname)}\n"
        f"ID: {admin_id}\n\n"
        f"Date: {dt}"
    )


# ────────────────────── Group connection logs ───────────────────── #


def group_connected_log(
    chat_id: int,
    chat_title: str,
    owner_id: int,
    owner_fname: str,
    chat_username: str | None = None,
) -> str:
    dt = fmt_dt(utc_now())
    if chat_username:
        group_display = (
            f'<a href="https://t.me/{esc(chat_username)}">{esc(chat_title)}</a>'
        )
    else:
        group_display = esc(chat_title)
    return (
        f"New {cfg.community_name} Connected Group\n\n"
        f"Group: {group_display}\n"
        f"ID: {chat_id}\n\n"
        f"Added by Owner: {mention(owner_id, owner_fname)}\n"
        f"ID: {owner_id}\n\n"
        f"Date: {dt}"
    )


def group_connection_rejected_log(
    chat_id: int,
    chat_title: str,
    owner_id: int,
    owner_fname: str,
) -> str:
    dt = fmt_dt(utc_now())
    return (
        f"{cfg.community_name} Connection Rejected\n\n"
        f"Group: {esc(chat_title)} (ID: {chat_id})\n\n"
        f"Rejected by Owner: {mention(owner_id, owner_fname)} (ID: {owner_id})\n\n"
        f"Date: {dt}"
    )


def group_disconnected_log(
    chat_id: int,
    chat_title: str,
    actor_id: int,
    actor_fname: str,
) -> str:
    dt = fmt_dt(utc_now())
    return (
        f"{cfg.community_name} Group Disconnected\n\n"
        f"Group: {esc(chat_title)}\n"
        f"ID: {chat_id}\n\n"
        f"Removed by: {mention(actor_id, actor_fname)}\n"
        f"ID: {actor_id}\n\n"
        f"Date: {dt}"
    )


def group_bot_removed_log(
    chat_id: int,
    chat_title: str,
) -> str:
    dt = fmt_dt(utc_now())
    return (
        f"{cfg.community_name} Group Removed Bot\n\n"
        f"Group: {esc(chat_title)}\n"
        f"ID: {chat_id}\n\n"
        f"Date: {dt}"
    )


def broadcast_log(
    admin_id: int,
    admin_fname: str,
    message_preview: str,
    success: int,
    failed: int,
) -> str:
    dt = fmt_dt(utc_now())
    preview = message_preview[:100]
    return (
        f"{cfg.community_name} Broadcast Sent\n\n"
        f"Admin: {mention(admin_id, admin_fname)}\n"
        f"Message: {esc(preview)}\n\n"
        f"Groups reached: {success}\n"
        f"Failed groups: {failed}\n\n"
        f"Date: {dt}"
    )


# ────────────────────── Role management logs ────────────────────── #


def role_assigned(
    target_id: int,
    target_fname: str,
    role: str,
    admin_id: int,
    admin_fname: str,
) -> str:
    dt = fmt_dt(utc_now())
    role_label = _ROLE_LABELS.get(role, role.capitalize())
    return (
        f"New {cfg.community_name} {role_label} Assigned\n\n"
        f"{role_label}: {mention(target_id, target_fname)}\n"
        f"ID: {target_id}\n\n"
        f"Assigned by: {mention(admin_id, admin_fname)}\n"
        f"ID: {admin_id}\n\n"
        f"Date: {dt}"
    )


def role_removed(
    target_id: int,
    target_fname: str,
    role: str,
    admin_id: int,
    admin_fname: str,
) -> str:
    dt = fmt_dt(utc_now())
    role_label = _ROLE_LABELS.get(role, role.capitalize())
    return (
        f"{cfg.community_name} Role Removed\n\n"
        f"User: {mention(target_id, target_fname)}\n"
        f"ID: {target_id}\n"
        f"Role removed: {role_label}\n\n"
        f"Removed by: {mention(admin_id, admin_fname)}\n"
        f"ID: {admin_id}\n\n"
        f"Date: {dt}"
    )


def role_auto_demoted(
    target_id: int,
    target_fname: str,
    role: str,
    admin_id: int,
    admin_fname: str,
    action: str,
) -> str:
    dt = fmt_dt(utc_now())
    role_label = _ROLE_LABELS.get(role, role.capitalize())
    action_label = "Banned" if action == "ban" else "Kicked"
    return (
        f"{cfg.community_name} Auto-Demote\n\n"
        f"User: {mention(target_id, target_fname)}\n"
        f"ID: {target_id}\n"
        f"Role removed: {role_label}\n"
        f"Trigger: {action_label}\n\n"
        f"By: {mention(admin_id, admin_fname)}\n"
        f"ID: {admin_id}\n\n"
        f"Date: {dt}"
    )
