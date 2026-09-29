# © Copyright 2024 - 2026 Transsion Core
# © Copyright 2024 - 2026 Dizzy
# © Copyright 2026 Ave Labs

"""Role audit-log builders: promotions, demotions, ownership, requests."""

from __future__ import annotations

from tcbot import cfg
from tcbot import database as db
from tcbot.modules.helper.parse_logmsg.core import LogBuilder


def _role_title(role: str) -> str:
    """Return the human-readable label for a role string."""
    return db.users_roles.ROLE_LABEL.get(role, role.capitalize())


def promoted(
    target_id: int,
    target_fname: str,
    role: str,
    by_id: int,
    by_fname: str,
) -> str:
    """Unified promotion audit-log for Admin / Developer / Tester.

    Single shape: the role is shown as a field below the user, not in the title.
    """
    role_label = _role_title(role)
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
    """Unified demotion audit-log: manual demote and ban/kick auto-demote share one format."""
    role_label = _role_title(role)
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
    """Promotion-request audit-log message sent to the Founder."""
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
