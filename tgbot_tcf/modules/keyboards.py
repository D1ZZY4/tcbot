# © Copyright 2024 - 2026 Transsion Core
# © Copyright 2024 - 2026 Dizzy
# © Copyright 2026 Aveum Apps
"""Reusable inline-keyboard factories.

Every keyboard the bot sends is constructed here so layout, callback-data
naming, and PROMPT Feature 26 row rules (two buttons per row, related
actions in the same row, single Back/Cancel may stand alone) live in one
place that is easy to audit and change.
"""
from __future__ import annotations

from telegram import InlineKeyboardButton, InlineKeyboardMarkup


# -------------------------------------------------------------- start menu

def start_menu() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(
        [
            [
                InlineKeyboardButton("About", callback_data="menu_about"),
                InlineKeyboardButton("Help", callback_data="menu_help"),
            ],
            [
                InlineKeyboardButton("Groups", callback_data="menu_groups"),
                InlineKeyboardButton("Additional", callback_data="menu_additional"),
            ],
            [InlineKeyboardButton("Information", callback_data="menu_information")],
            [InlineKeyboardButton("Privacy", callback_data="menu_privacy")],
        ]
    )


def back_to_start() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(
        [[InlineKeyboardButton("Back", callback_data="menu_back_start")]]
    )


def info_main() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(
        [
            [
                InlineKeyboardButton("Admins", callback_data="info_admins"),
                InlineKeyboardButton("Connected Chats", callback_data="info_chats"),
            ],
            [InlineKeyboardButton("Back", callback_data="menu_back_start")],
        ]
    )


def back_to_information() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(
        [[InlineKeyboardButton("Back", callback_data="menu_information")]]
    )


def privacy_menu() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(
        [
            [InlineKeyboardButton("Privacy Policy", callback_data="menu_privacy_policy")],
            [InlineKeyboardButton("Back", callback_data="menu_back_start")],
        ]
    )


def back_to_privacy() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(
        [[InlineKeyboardButton("Back", callback_data="menu_privacy")]]
    )


# ----------------------------------------------------------------- help menu

def help_modules(rows: list[list[tuple[str, str]]], with_back_to_start: bool) -> InlineKeyboardMarkup:
    keyboard = [
        [InlineKeyboardButton(label, callback_data=cb) for label, cb in row]
        for row in rows
    ]
    if with_back_to_start:
        keyboard.append([InlineKeyboardButton("Back", callback_data="menu_back_start")])
    return InlineKeyboardMarkup(keyboard)


def help_detail(*, with_main_menu_button: bool) -> InlineKeyboardMarkup:
    rows = [[InlineKeyboardButton("Back", callback_data="menu_help_main")]]
    if with_main_menu_button:
        rows.append(
            [InlineKeyboardButton("Main Menu", callback_data="menu_back_start")]
        )
    return InlineKeyboardMarkup(rows)


# ---------------------------------------------------------------- affiliation

def affiliation_prompt() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(
        [
            [
                InlineKeyboardButton("Join Transsion Core", callback_data="tc_join"),
                InlineKeyboardButton("Cancel", callback_data="tc_cancel"),
            ]
        ]
    )


# ---------------------------------------------------------------------- bans

def proof_cancel() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(
        [[InlineKeyboardButton("Cancel", callback_data="cancel_proof")]]
    )


def ban_log_new(*, target_id: int, proof_link: str, appeal_url: str) -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(
        [
            [InlineKeyboardButton(f"Proof {target_id}", url=proof_link)],
            [InlineKeyboardButton("Submit Appeal", url=appeal_url)],
        ]
    )


def ban_log_update(
    *, target_id: int, proof_link: str, previous_proof_link: str, appeal_url: str
) -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(
        [
            [
                InlineKeyboardButton(f"Proof {target_id}", url=proof_link),
                InlineKeyboardButton(f"Previous Proof {target_id}", url=previous_proof_link),
            ],
            [InlineKeyboardButton("Submit Appeal", url=appeal_url)],
        ]
    )


def submit_appeal(appeal_url: str) -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(
        [[InlineKeyboardButton("Submit Appeal", url=appeal_url)]]
    )


def view_proof(proof_link: str) -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(
        [[InlineKeyboardButton("View Proof", url=proof_link)]]
    )


# ------------------------------------------------------------------- appeals

def appeal_cancel() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(
        [[InlineKeyboardButton("Cancel", callback_data="cancel_appeal")]]
    )


def appeal_review(ban_id: str) -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(
        [
            [
                InlineKeyboardButton("Approve", callback_data=f"appeal_approve_{ban_id}"),
                InlineKeyboardButton("Reject", callback_data=f"appeal_reject_{ban_id}"),
            ]
        ]
    )


# ----------------------------------------------------------- promo requests

def promotion_request(request_id: str) -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(
        [
            [
                InlineKeyboardButton(
                    "Approve", callback_data=f"approve_promote_{request_id}"
                ),
                InlineKeyboardButton(
                    "Reject", callback_data=f"reject_promote_{request_id}"
                ),
            ]
        ]
    )


# --------------------------------------------------------------- links menu

def federation_links() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(
        [
            [
                InlineKeyboardButton(
                    "Main Channel", url="https://t.me/TranssionCoreFederation"
                ),
                InlineKeyboardButton(
                    "Discussion Group",
                    url="https://t.me/TranssionCoreFederationGroup",
                ),
            ],
            [
                InlineKeyboardButton(
                    "Logs Channel", url="https://t.me/TranssionCoreFederationLogs"
                ),
                InlineKeyboardButton(
                    "Exec Group", url="https://t.me/+A105pfnCvkhiZWM1"
                ),
            ],
            [
                InlineKeyboardButton(
                    "TRAVEL (Dev Community)", url="http://t.me/+S2C_ppFvHlAwMzNl"
                ),
            ],
        ]
    )


# ----------------------------------------------------- welcome group helper

def what_is_tcf(about_url: str) -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(
        [[InlineKeyboardButton("What is TCF?", url=about_url)]]
    )
