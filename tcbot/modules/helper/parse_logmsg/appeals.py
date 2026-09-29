# © Copyright 2024 - 2026 Transsion Core
# © Copyright 2024 - 2026 Dizzy
# © Copyright 2026 Ave Labs

"""Appeal audit-log builders: submission cards, decisions, and appeal unbans."""

from __future__ import annotations

from typing import TYPE_CHECKING

from tcbot import cfg
from tcbot.modules.helper.parse_logmsg.core import LogBuilder
from tcbot.utils.formatter import code, user_ref
from tcbot.utils.time_and_date import fmt_dt

if TYPE_CHECKING:
    from datetime import datetime


def appeal_received_log(
    target_id: int,
    target_fname: str,
    ban_id: str,
    appeal_link: str,
) -> str:
    """Review card posted to APPEAL_DISCUSSION_TOPIC."""
    b = LogBuilder(f"New {cfg.community_name} Appeal Request").raw(
        f"User: {user_ref(target_id, target_fname)} \\(ID: {code(str(target_id))}\\)"
    )
    b.code_field("Ban ID", ban_id)
    if appeal_link:
        b.link_field("Appeal", "View", appeal_link)
    else:
        b.field("Appeal", "N/A")
    return (
        b.date(label="Submitted")
        .section()
        .raw("This appeal is pending review\\.")
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
    submitted_str = fmt_dt(submitted_at) if submitted_at else "N/A"
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
        # * submitted_str arrives pre-escaped from fmt_dt: pass it through
        # * instead of escaping twice like the default field() does.
        .field("Submitted", submitted_str, escape=False)
        .raw(f"{decision_label}: {user_ref(admin_id, admin_fname)}")
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
