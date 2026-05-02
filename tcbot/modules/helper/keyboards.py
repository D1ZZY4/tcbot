# © Copyright 2024 - 2026 Transsion Core
# © Copyright 2024 - 2026 Dizzy
# © Copyright 2026 Aveum Apps
"""Inline keyboard builders."""

from __future__ import annotations

from telegram import InlineKeyboardButton, InlineKeyboardMarkup


## ---------------------------------------------------------------------------
## Ban flow
## ---------------------------------------------------------------------------


def cancel_proof_kb() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(
        [
            [
                InlineKeyboardButton("Cancel", callback_data="cancel_proof"),
            ]
        ]
    )


def ban_log_kb(
    target_id: int,
    proof_lnk: str,
    bot_username: str,
    ban_id: str,
) -> InlineKeyboardMarkup:
    appeal_url = f"https://t.me/{bot_username}?start=appeal{ban_id}"
    return InlineKeyboardMarkup(
        [
            [InlineKeyboardButton(f"Proof {target_id}", url=proof_lnk)],
            [InlineKeyboardButton("Submit Appeal", url=appeal_url)],
        ]
    )


def ban_log_update_kb(
    target_id: int,
    proof_lnk: str,
    prev_proof_lnk: str,
    bot_username: str,
    ban_id: str,
) -> InlineKeyboardMarkup:
    appeal_url = f"https://t.me/{bot_username}?start=appeal{ban_id}"
    return InlineKeyboardMarkup(
        [
            [
                InlineKeyboardButton(f"Proof {target_id}", url=proof_lnk),
                InlineKeyboardButton(f"Previous Proof {target_id}", url=prev_proof_lnk),
            ],
            [InlineKeyboardButton("Submit Appeal", url=appeal_url)],
        ]
    )


## ---------------------------------------------------------------------------
## Appeal flow
## ---------------------------------------------------------------------------


def appeal_cancel_kb() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(
        [
            [
                InlineKeyboardButton("Cancel", callback_data="cancel_appeal"),
            ]
        ]
    )


def appeal_review_kb(ban_id: str) -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(
        [
            [
                InlineKeyboardButton(
                    "Approve", callback_data=f"appeal_approve_{ban_id}"
                ),
                InlineKeyboardButton("Reject", callback_data=f"appeal_reject_{ban_id}"),
            ]
        ]
    )


## ---------------------------------------------------------------------------
## Admin promotion
## ---------------------------------------------------------------------------


def promo_decision_kb(request_id: str) -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(
        [
            [
                InlineKeyboardButton(
                    "Approve", callback_data=f"promo_approve:{request_id}"
                ),
                InlineKeyboardButton(
                    "Reject", callback_data=f"promo_reject:{request_id}"
                ),
            ]
        ]
    )


## ---------------------------------------------------------------------------
## Group connect prompt (in-group)
## ---------------------------------------------------------------------------


def join_group_kb() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(
        [
            [
                InlineKeyboardButton("Connect", callback_data="tc_join"),
                InlineKeyboardButton("Cancel", callback_data="tc_cancel"),
            ]
        ]
    )


## ---------------------------------------------------------------------------
## Check-me / baninfo
## ---------------------------------------------------------------------------


def checkme_appeal_kb(bot_username: str, ban_id: str) -> InlineKeyboardMarkup:
    url = f"https://t.me/{bot_username}?start=appeal{ban_id}"
    return InlineKeyboardMarkup(
        [
            [
                InlineKeyboardButton("Submit Appeal", url=url),
            ]
        ]
    )


def baninfo_proof_kb(proof_lnk: str) -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(
        [
            [
                InlineKeyboardButton("View Proof", url=proof_lnk),
            ]
        ]
    )


## ---------------------------------------------------------------------------
## Start / Help menus
## ---------------------------------------------------------------------------


def main_menu_kb() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(
        [
            [
                InlineKeyboardButton("About", callback_data="menu_about"),
                InlineKeyboardButton("Help", callback_data="menu_help"),
            ],
            [InlineKeyboardButton("Additional", callback_data="menu_additional")],
            [InlineKeyboardButton("Privacy",    callback_data="menu_privacy")],
        ]
    )


def help_topics_kb(topics: list[tuple[str, str]]) -> InlineKeyboardMarkup:
    rows: list[list] = []
    it = iter(topics)
    for a, b in zip(it, it):
        rows.append(
            [
                InlineKeyboardButton(a[0], callback_data=a[1]),
                InlineKeyboardButton(b[0], callback_data=b[1]),
            ]
        )
    for item in list(it):
        rows.append([InlineKeyboardButton(item[0], callback_data=item[1])])
    rows.append([InlineKeyboardButton("Back", callback_data="menu_back_start")])
    return InlineKeyboardMarkup(rows)


def mute_reason_kb() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(
        [
            [
                InlineKeyboardButton("Skip", callback_data="mute_skip_reason"),
                InlineKeyboardButton("Cancel", callback_data="mute_cancel"),
            ]
        ]
    )


def mute_proof_kb() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(
        [
            [
                InlineKeyboardButton("Skip", callback_data="mute_skip_proof"),
                InlineKeyboardButton("Cancel", callback_data="mute_cancel"),
            ]
        ]
    )


def back_to_start_kb() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(
        [
            [
                InlineKeyboardButton("Back", callback_data="menu_back_start"),
            ]
        ]
    )


def back_to_help_kb() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(
        [
            [
                InlineKeyboardButton("Back", callback_data="menu_help"),
            ]
        ]
    )




def privacy_kb() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(
        [
            [
                InlineKeyboardButton(
                    "Privacy Policy", callback_data="menu_privacy_policy"
                )
            ],
            [InlineKeyboardButton("Back", callback_data="menu_back_start")],
        ]
    )


def back_to_privacy_kb() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(
        [
            [
                InlineKeyboardButton("Back", callback_data="menu_privacy"),
            ]
        ]
    )


## ---------------------------------------------------------------------------
## Legacy compat
## ---------------------------------------------------------------------------


def join_decision_kb(chat_id: int) -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(
        [
            [
                InlineKeyboardButton("Accept", callback_data=f"join_accept:{chat_id}"),
                InlineKeyboardButton("Reject", callback_data=f"join_reject:{chat_id}"),
            ]
        ]
    )


def confirm_ban_kb(key: str) -> InlineKeyboardMarkup:
    return cancel_proof_kb()


def appeal_confirm_kb(ban_id: str) -> InlineKeyboardMarkup:
    return appeal_cancel_kb()


def back_to_menu_kb() -> InlineKeyboardMarkup:
    return back_to_start_kb()
