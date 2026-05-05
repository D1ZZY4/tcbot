# © Copyright 2024 - 2026 Transsion Core
# © Copyright 2024 - 2026 Dizzy
# © Copyright 2026 Aveum Apps
## Inline keyboard builders

from __future__ import annotations

from telegram import InlineKeyboardButton, InlineKeyboardMarkup

from tcbot.database.roles_db import ROLE_LABEL as _ROLE_LABELS


## ── Ban flow ─────────────────────────────────────────────────────────────────


def cancel_proof_kb() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(
        [
            [
                InlineKeyboardButton("Cancel", callback_data="cancel_proof"),
            ]
        ]
    )


def ban_log_new(
    target_id: int,
    proof_link: str,
    appeal_url: str,
) -> InlineKeyboardMarkup:
    """Ban-log keyboard with explicit appeal URL."""
    return InlineKeyboardMarkup([
        [InlineKeyboardButton(f"Proof {target_id}", url=proof_link)],
        [InlineKeyboardButton("Submit Appeal",       url=appeal_url)],
    ])


def ban_log_update(
    target_id: int,
    proof_link: str,
    previous_proof_link: str,
    appeal_url: str,
) -> InlineKeyboardMarkup:
    """Updated ban-log keyboard with previous-proof button and explicit appeal URL."""
    return InlineKeyboardMarkup([
        [
            InlineKeyboardButton(f"Proof {target_id}",          url=proof_link),
            InlineKeyboardButton(f"Previous Proof {target_id}", url=previous_proof_link),
        ],
        [InlineKeyboardButton("Submit Appeal", url=appeal_url)],
    ])


## ── Appeal flow ──────────────────────────────────────────────────────────────


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


## ── Admin promotion ──────────────────────────────────────────────────────────


def promote_role_kb(target_id: int, available_roles: list[str]) -> InlineKeyboardMarkup:
    """Role selection keyboard shown when /tcpromote is used without a role argument."""
    buttons = [
        InlineKeyboardButton(_ROLE_LABELS[r], callback_data=f"promo_role:{r}:{target_id}")
        for r in available_roles
        if r in _ROLE_LABELS
    ]
    rows: list[list[InlineKeyboardButton]] = [
        buttons[i : i + 2] for i in range(0, len(buttons), 2)
    ]
    rows.append([InlineKeyboardButton("Cancel", callback_data=f"promo_role_cancel:{target_id}")])
    return InlineKeyboardMarkup(rows)


def demote_confirm_kb(target_id: int) -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup([
        [
            InlineKeyboardButton("Confirm", callback_data=f"demote_confirm:{target_id}"),
            InlineKeyboardButton("Cancel",  callback_data=f"demote_cancel:{target_id}"),
        ]
    ])


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


## ── Group connect prompt ─────────────────────────────────────────────────────


def join_group_kb() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(
        [
            [
                InlineKeyboardButton("Connect", callback_data="tc_join"),
                InlineKeyboardButton("Cancel", callback_data="tc_cancel"),
            ]
        ]
    )


## ── Check-me / baninfo ───────────────────────────────────────────────────────


def checkme_ban_kb(
    bot_username: str,
    ban_id: str,
    proof_link: str | None = None,
) -> InlineKeyboardMarkup:
    """Summary view keyboard — Details | Proof (row 1), Appeal (row 2)."""
    appeal_url = f"https://t.me/{bot_username}?start=appeal_{ban_id}"
    row1 = [InlineKeyboardButton("Details", callback_data=f"checkme_detail:{ban_id}")]
    if proof_link:
        row1.append(InlineKeyboardButton("Proof", url=proof_link))
    return InlineKeyboardMarkup([
        row1,
        [InlineKeyboardButton("Appeal", url=appeal_url)],
    ])


def checkme_detail_back_kb(
    ban_id: str,
    proof_link: str | None = None,
) -> InlineKeyboardMarkup:
    """Detail view keyboard — optional Proof (row 1), Back (row 2)."""
    rows = []
    if proof_link:
        rows.append([InlineKeyboardButton("Proof", url=proof_link)])
    rows.append([InlineKeyboardButton("« Back", callback_data=f"checkme_back:{ban_id}")])
    return InlineKeyboardMarkup(rows)


def baninfo_proof_kb(proof_lnk: str) -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(
        [
            [
                InlineKeyboardButton("View Proof", url=proof_lnk),
            ]
        ]
    )


## ── Start / Help menus ───────────────────────────────────────────────────────


def main_menu_kb() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(
        [
            [
                InlineKeyboardButton("About", callback_data="menu_about"),
                InlineKeyboardButton("Help",  callback_data="menu_help"),
            ],
            [InlineKeyboardButton("Additional", callback_data="menu_additional")],
            [InlineKeyboardButton("Privacy",    callback_data="menu_privacy")],
        ]
    )


def group_start_kb(bot_username: str) -> InlineKeyboardMarkup:
    """Keyboard for /start sent inside a group — sends user to PM."""
    pm_url = f"https://t.me/{bot_username}?start=menu"
    return InlineKeyboardMarkup(
        [
            [InlineKeyboardButton("Open in PM ↗", url=pm_url)],
            [InlineKeyboardButton("Help",          callback_data="menu_help_group")],
        ]
    )


def help_modules(
    rows: list[list[tuple[str, str]]],
    *,
    with_back_to_start: bool = False,
) -> InlineKeyboardMarkup:
    """Build a help menu keyboard from (text, callback_data) tuples.

    Args:
        rows: Each inner list is a button row; each element is (text, callback_data).
        with_back_to_start: Append a Back button pointing to the start menu.
    """
    kb_rows = [
        [InlineKeyboardButton(text, callback_data=cb) for text, cb in row]
        for row in rows
    ]
    if with_back_to_start:
        kb_rows.append([InlineKeyboardButton("« Back", callback_data="menu_back_start")])
    return InlineKeyboardMarkup(kb_rows)


def _build_topic_rows(topics: list[tuple[str, str]]) -> list[list[InlineKeyboardButton]]:
    """Pair topics into two-column rows, with any odd item on its own row."""
    rows: list[list[InlineKeyboardButton]] = []
    it = iter(topics)
    for a, b in zip(it, it):
        rows.append([
            InlineKeyboardButton(a[0], callback_data=a[1]),
            InlineKeyboardButton(b[0], callback_data=b[1]),
        ])
    for item in list(it):
        rows.append([InlineKeyboardButton(item[0], callback_data=item[1])])
    return rows


def help_topics_menu_kb(topics: list[tuple[str, str]]) -> InlineKeyboardMarkup:
    """Help index when reached via the start menu — includes « Back to start."""
    rows = _build_topic_rows(topics)
    rows.append([InlineKeyboardButton("« Back", callback_data="menu_back_start")])
    return InlineKeyboardMarkup(rows)


def help_topics_kb(topics: list[tuple[str, str]]) -> InlineKeyboardMarkup:
    """Help index when reached via /help command (PM or group) — no back to start."""
    return InlineKeyboardMarkup(_build_topic_rows(topics))


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
                InlineKeyboardButton("« Back", callback_data="menu_back_start"),
            ]
        ]
    )


def back_to_help_kb() -> InlineKeyboardMarkup:
    """Back to help index — used from menu-path topics (goes to menu_help)."""
    return InlineKeyboardMarkup(
        [
            [
                InlineKeyboardButton("« Back", callback_data="menu_help"),
            ]
        ]
    )


def back_to_help_cmd_kb() -> InlineKeyboardMarkup:
    """Back to help index — used from command-path topics (goes to helpcmd_idx)."""
    return InlineKeyboardMarkup(
        [
            [
                InlineKeyboardButton("« Back", callback_data="helpcmd_idx"),
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
            [InlineKeyboardButton("« Back", callback_data="menu_back_start")],
        ]
    )


def back_to_privacy_kb() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(
        [
            [
                InlineKeyboardButton("« Back", callback_data="menu_privacy"),
            ]
        ]
    )
