# © Copyright 2024 - 2026 Transsion Core
# © Copyright 2024 - 2026 Dizzy
# © Copyright 2026 Ave Labs

"""Ban, proof, and generic detail keyboards."""

from __future__ import annotations

from telegram import InlineKeyboardButton, InlineKeyboardMarkup
from telegram.constants import KeyboardButtonStyle

from tcbot.modules.helper.parse_link import appeal_deep_link
from tcbot.utils.i18n import t


def ban_log_new(
    target_id: int,
    proof_link: str,
    appeal_url: str,
    locale: str | None = None,
) -> InlineKeyboardMarkup:
    """Ban-log keyboard with proof and appeal URL buttons, one per row."""
    return InlineKeyboardMarkup(
        [
            [
                InlineKeyboardButton(
                    t("button.proof_id", locale, id=target_id, plain=True),
                    url=proof_link,
                    style=KeyboardButtonStyle.PRIMARY,
                )
            ],
            [
                InlineKeyboardButton(
                    t("button.submit_appeal", locale, plain=True),
                    url=appeal_url,
                    style=KeyboardButtonStyle.PRIMARY,
                )
            ],
        ]
    )


def ban_log_update(
    target_id: int,
    proof_link: str,
    previous_proof_link: str,
    appeal_url: str,
    locale: str | None = None,
) -> InlineKeyboardMarkup:
    """Ban-log keyboard with current plus previous proof buttons.

    One URL button per row: proof labels embed the target ID, so two of
    them side by side truncate on narrow clients.
    """
    return InlineKeyboardMarkup(
        [
            [
                InlineKeyboardButton(
                    t("button.proof_id", locale, id=target_id, plain=True),
                    url=proof_link,
                    style=KeyboardButtonStyle.PRIMARY,
                )
            ],
            [
                InlineKeyboardButton(
                    t("button.prev_proof_id", locale, id=target_id, plain=True),
                    url=previous_proof_link,
                    style=KeyboardButtonStyle.PRIMARY,
                )
            ],
            [
                InlineKeyboardButton(
                    t("button.submit_appeal", locale, plain=True),
                    url=appeal_url,
                    style=KeyboardButtonStyle.PRIMARY,
                )
            ],
        ]
    )


def ban_update_confirm_kb(
    log_url: str | None,
    proof_url: str | None,
    locale: str | None = None,
) -> InlineKeyboardMarkup:
    """Re-ban confirmation: View Log / View Proof URLs, then Cancel / Continue.

    URL buttons drop out individually when their link is missing; the
    Cancel / Continue decision row is always present.
    """
    rows: list[list[InlineKeyboardButton]] = []
    links = []
    if log_url:
        links.append(
            InlineKeyboardButton(t("button.view_log", locale, plain=True), url=log_url)
        )
    if proof_url:
        links.append(
            InlineKeyboardButton(
                t("button.view_proof", locale, plain=True), url=proof_url
            )
        )
    if links:
        rows.append(links)
    rows.append(
        [
            InlineKeyboardButton(
                t("button.cancel", locale, plain=True), callback_data="ban_cancel"
            ),
            InlineKeyboardButton(
                t("button.continue", locale, plain=True),
                callback_data="ban_continue",
                style=KeyboardButtonStyle.PRIMARY,
            ),
        ]
    )
    return InlineKeyboardMarkup(rows)


def appeal_button_kb(
    bot_username: str,
    ban_id: str,
    locale: str | None = None,
) -> InlineKeyboardMarkup | None:
    """Single Submit Appeal URL button, or None when the username is unknown."""
    if not bot_username:
        return None
    return InlineKeyboardMarkup(
        [
            [
                InlineKeyboardButton(
                    t("button.submit_appeal", locale, plain=True),
                    url=appeal_deep_link(bot_username, ban_id),
                    style=KeyboardButtonStyle.PRIMARY,
                )
            ]
        ]
    )


def action_proof_kb(
    target_id: int,
    proof_link: str | None,
    locale: str | None = None,
) -> InlineKeyboardMarkup | None:
    """Single proof URL button, or None when no proof link is available."""
    if not proof_link:
        return None
    return InlineKeyboardMarkup(
        [
            [
                InlineKeyboardButton(
                    t("button.proof_id", locale, id=target_id, plain=True),
                    url=proof_link,
                    style=KeyboardButtonStyle.PRIMARY,
                )
            ]
        ]
    )


def detail_kb(
    *,
    back_callback: str,
    proof_link: str | None = None,
    appeal_link: str | None = None,
    locale: str | None = None,
) -> InlineKeyboardMarkup:
    """Proof/appeal URL row(s) plus a tagged back button."""
    rows: list[list[InlineKeyboardButton]] = []
    if proof_link:
        rows.append(
            [
                InlineKeyboardButton(
                    t("button.view_proof", locale, plain=True),
                    url=proof_link,
                    style=KeyboardButtonStyle.PRIMARY,
                )
            ]
        )
    if appeal_link:
        rows.append(
            [
                InlineKeyboardButton(
                    t("button.view_appeal", locale, plain=True),
                    url=appeal_link,
                    style=KeyboardButtonStyle.PRIMARY,
                )
            ]
        )
    rows.append(
        [
            InlineKeyboardButton(
                t("button.back", locale, plain=True),
                callback_data=back_callback,
            )
        ]
    )
    return InlineKeyboardMarkup(rows)
