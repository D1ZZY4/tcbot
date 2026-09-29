# © Copyright 2024 - 2026 Transsion Core
# © Copyright 2024 - 2026 Dizzy
# © Copyright 2026 Ave Labs

"""Appeal submit-prompt and staff review keyboards."""

from __future__ import annotations

from telegram import InlineKeyboardButton, InlineKeyboardMarkup
from telegram.constants import KeyboardButtonStyle

from tcbot.utils.i18n import t


def appeal_cancel_kb(
    label: str | None = None,
    callback: str = "cancel_appeal",
    locale: str | None = None,
) -> InlineKeyboardMarkup:
    """Single-button keyboard attached to the appeal instruction prompt."""
    return InlineKeyboardMarkup(
        [
            [
                InlineKeyboardButton(
                    label
                    if label is not None
                    else t("button.cancel", locale, plain=True),
                    callback_data=callback,
                )
            ]
        ]
    )


def appeal_review_kb(ban_id: str, locale: str | None = None) -> InlineKeyboardMarkup:
    """Approve / Reject keyboard on the staff review card."""
    # * Underscore separators match the review handler pattern.
    return InlineKeyboardMarkup(
        [
            [
                InlineKeyboardButton(
                    t("button.approve", locale, plain=True),
                    callback_data=f"appeal_approve_{ban_id}",
                    style=KeyboardButtonStyle.SUCCESS,
                ),
                InlineKeyboardButton(
                    t("button.reject", locale, plain=True),
                    callback_data=f"appeal_reject_{ban_id}",
                    style=KeyboardButtonStyle.DANGER,
                ),
            ]
        ]
    )
