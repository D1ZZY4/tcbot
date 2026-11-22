# © Copyright 2024 - 2026 Transsion Core
# © Copyright 2024 - 2026 Dizzy
# © Copyright 2026 Ave Labs

"""Appeal submit-prompt and staff review buttons."""

from __future__ import annotations

from telegram import InlineKeyboardButton, InlineKeyboardMarkup
from telegram.constants import KeyboardButtonStyle

from tcbot.utils.i18n import t


def appeal_cancel_btn(
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
                    style=KeyboardButtonStyle.DANGER,
                )
            ]
        ]
    )


def appeal_review_btn(
    ban_id: str, review_message_id: int, locale: str | None = None
) -> InlineKeyboardMarkup:
    """Approve / Reject keyboard bound to the review card it belongs to.

    The card id rides in the callback payload so a card left behind by an
    earlier appeal cannot decide the appeal that replaced it.
    """
    # * Underscore separators match the review handler pattern.
    suffix = f"{ban_id}_{review_message_id}"
    return InlineKeyboardMarkup(
        [
            [
                InlineKeyboardButton(
                    t("button.approve", locale, plain=True),
                    callback_data=f"appeal_approve_{suffix}",
                    style=KeyboardButtonStyle.SUCCESS,
                ),
                InlineKeyboardButton(
                    t("button.reject", locale, plain=True),
                    callback_data=f"appeal_reject_{suffix}",
                    style=KeyboardButtonStyle.DANGER,
                ),
            ]
        ]
    )
