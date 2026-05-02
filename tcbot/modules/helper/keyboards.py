# © Copyright 2024 - 2026 Transsion Core
# © Copyright 2024 - 2026 Dizzy
# © Copyright 2026 Aveum Apps
"""All inline keyboard builders – no emojis in button labels."""
from __future__ import annotations

from telegram import InlineKeyboardButton, InlineKeyboardMarkup


## ---------------------------------------------------------------------------
## Ban flow
## ---------------------------------------------------------------------------

def cancel_proof_kb() -> InlineKeyboardMarkup:
    """Single Cancel button shown while waiting for proof."""
    return InlineKeyboardMarkup([[
        InlineKeyboardButton("Cancel", callback_data="cancel_proof"),
    ]])


def ban_log_kb(
    target_id: int,
    proof_lnk: str,
    bot_username: str,
    ban_id: str,
) -> InlineKeyboardMarkup:
    """Two-row keyboard on NEW ban log: Proof button + Submit Appeal button."""
    appeal_url = f"https://t.me/{bot_username}?start=appeal_{ban_id}"
    return InlineKeyboardMarkup([
        [InlineKeyboardButton(f"Proof {target_id}", url=proof_lnk)],
        [InlineKeyboardButton("Submit Appeal", url=appeal_url)],
    ])


def ban_log_update_kb(
    target_id: int,
    proof_lnk: str,
    prev_proof_lnk: str,
    bot_username: str,
    ban_id: str,
) -> InlineKeyboardMarkup:
    """Three-button keyboard on UPDATE ban log."""
    appeal_url = f"https://t.me/{bot_username}?start=appeal_{ban_id}"
    return InlineKeyboardMarkup([
        [
            InlineKeyboardButton(f"Proof {target_id}", url=proof_lnk),
            InlineKeyboardButton(f"Previous Proof {target_id}", url=prev_proof_lnk),
        ],
        [InlineKeyboardButton("Submit Appeal", url=appeal_url)],
    ])


## ---------------------------------------------------------------------------
## Appeal flow
## ---------------------------------------------------------------------------

def appeal_cancel_kb() -> InlineKeyboardMarkup:
    """Single Cancel button shown during appeal instruction."""
    return InlineKeyboardMarkup([[
        InlineKeyboardButton("Cancel", callback_data="cancel_appeal"),
    ]])


def appeal_review_kb(ban_id: str) -> InlineKeyboardMarkup:
    """Approve / Reject buttons posted in APPEAL_DISCUSSION_TOPIC (thread 11)."""
    return InlineKeyboardMarkup([[
        InlineKeyboardButton("Approve", callback_data=f"appeal_approve_{ban_id}"),
        InlineKeyboardButton("Reject", callback_data=f"appeal_reject_{ban_id}"),
    ]])


## ---------------------------------------------------------------------------
## Admin promotion
## ---------------------------------------------------------------------------

def promo_decision_kb(request_id: str) -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup([[
        InlineKeyboardButton("Approve", callback_data=f"promo_approve:{request_id}"),
        InlineKeyboardButton("Reject", callback_data=f"promo_reject:{request_id}"),
    ]])


## ---------------------------------------------------------------------------
## Group affiliation (in-group prompt)
## ---------------------------------------------------------------------------

def join_group_kb() -> InlineKeyboardMarkup:
    """Shown in the group when bot is first added."""
    return InlineKeyboardMarkup([[
        InlineKeyboardButton("Join Transsion Core", callback_data="tc_join"),
        InlineKeyboardButton("Cancel", callback_data="tc_cancel"),
    ]])


## ---------------------------------------------------------------------------
## Legacy (kept for backward compat)
## ---------------------------------------------------------------------------

def join_decision_kb(chat_id: int) -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup([[
        InlineKeyboardButton("Accept", callback_data=f"join_accept:{chat_id}"),
        InlineKeyboardButton("Reject", callback_data=f"join_reject:{chat_id}"),
    ]])


## ---------------------------------------------------------------------------
## Check-me / baninfo
## ---------------------------------------------------------------------------

def checkme_appeal_kb(bot_username: str, ban_id: str) -> InlineKeyboardMarkup:
    url = f"https://t.me/{bot_username}?start=appeal_{ban_id}"
    return InlineKeyboardMarkup([[
        InlineKeyboardButton("Submit Appeal", url=url),
    ]])


def baninfo_proof_kb(proof_lnk: str) -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup([[
        InlineKeyboardButton("View Proof", url=proof_lnk),
    ]])


## ---------------------------------------------------------------------------
## Start / Help menus
## ---------------------------------------------------------------------------

def main_menu_kb() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup([
        [
            InlineKeyboardButton("About", callback_data="menu_about"),
            InlineKeyboardButton("Help", callback_data="menu_help"),
        ],
        [
            InlineKeyboardButton("Groups", callback_data="menu_groups:0"),
            InlineKeyboardButton("Additional", callback_data="menu_additional"),
        ],
        [InlineKeyboardButton("Information", callback_data="menu_information")],
        [InlineKeyboardButton("Privacy", callback_data="menu_privacy")],
    ])


def help_topics_kb() -> InlineKeyboardMarkup:
    topics = [
        ("Ban", "help_ban"),
        ("Unban", "help_unban"),
        ("Check Ban", "help_check"),
        ("Ban Info", "help_baninfo"),
        ("Promote/Demote", "help_admins"),
        ("Transfer Owner", "help_transfer"),
        ("Broadcast", "help_broadcast"),
        ("Appeal", "help_appeal"),
        ("Group Affiliation", "help_connect"),
        ("Disaffiliate", "help_disconnect"),
        ("Cleanup", "help_cleanup"),
        ("Join/Leave", "help_joinleave"),
        ("Statistics", "help_stats"),
    ]
    rows: list[list] = []
    it = iter(topics)
    for a, b in zip(it, it):
        rows.append([
            InlineKeyboardButton(a[0], callback_data=a[1]),
            InlineKeyboardButton(b[0], callback_data=b[1]),
        ])
    ## Odd item (Statistics)
    remainder = list(it)
    for item in remainder:
        rows.append([InlineKeyboardButton(item[0], callback_data=item[1])])
    rows.append([InlineKeyboardButton("Back", callback_data="menu_back_start")])
    return InlineKeyboardMarkup(rows)


def back_to_start_kb() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup([[
        InlineKeyboardButton("Back", callback_data="menu_back_start"),
    ]])


def back_to_help_kb() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup([[
        InlineKeyboardButton("Back", callback_data="menu_help"),
    ]])


def info_sub_kb() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup([
        [
            InlineKeyboardButton("Admins", callback_data="info_admins:0"),
            InlineKeyboardButton("Connected Chats", callback_data="info_chats:0"),
        ],
        [InlineKeyboardButton("Back", callback_data="menu_back_start")],
    ])


def info_list_nav_kb(page: int, total_pages: int, prefix: str, back_cb: str) -> InlineKeyboardMarkup:
    nav = []
    if page > 0:
        nav.append(InlineKeyboardButton("Prev", callback_data=f"{prefix}:{page - 1}"))
    if page < total_pages - 1:
        nav.append(InlineKeyboardButton("Next", callback_data=f"{prefix}:{page + 1}"))
    rows = []
    if nav:
        rows.append(nav)
    rows.append([InlineKeyboardButton("Back", callback_data=back_cb)])
    return InlineKeyboardMarkup(rows)


def privacy_kb() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup([
        [InlineKeyboardButton("Privacy Policy", callback_data="menu_privacy_policy")],
        [InlineKeyboardButton("Back", callback_data="menu_back_start")],
    ])


def back_to_privacy_kb() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup([[
        InlineKeyboardButton("Back", callback_data="menu_privacy"),
    ]])


## ---------------------------------------------------------------------------
## Legacy compat aliases
## ---------------------------------------------------------------------------

def confirm_ban_kb(key: str) -> InlineKeyboardMarkup:
    return cancel_proof_kb()


def appeal_confirm_kb(ban_id: str) -> InlineKeyboardMarkup:
    return appeal_cancel_kb()


def back_to_menu_kb() -> InlineKeyboardMarkup:
    return back_to_start_kb()
