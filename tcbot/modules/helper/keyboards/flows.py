# © Copyright 2024 - 2026 Transsion Core
# © Copyright 2024 - 2026 Dizzy
# © Copyright 2026 Ave Labs

"""Step keyboards for the moderation, proof, and connect flows."""

from __future__ import annotations

from telegram import InlineKeyboardButton, InlineKeyboardMarkup
from telegram.constants import KeyboardButtonStyle

from tcbot.utils.i18n import t

# * Single owner for every flow-step keyboard. Flow classes keep thin
# * delegating methods so call sites stay unchanged while markup lives here.


def reason_step_kb(
    action: str, *, skip_allowed: bool = True, locale: str | None = None
) -> InlineKeyboardMarkup:
    """Reason step: optional Skip plus Cancel."""
    buttons: list[InlineKeyboardButton] = []
    if skip_allowed:
        buttons.append(
            InlineKeyboardButton(
                t("button.skip", locale, plain=True),
                callback_data=f"{action}_skip_reason",
                style=KeyboardButtonStyle.PRIMARY,
            )
        )
    buttons.append(
        InlineKeyboardButton(
            t("button.cancel", locale, plain=True),
            callback_data=f"{action}_cancel",
        )
    )
    return InlineKeyboardMarkup([buttons])


def proof_step_kb(
    action: str, *, skip_allowed: bool = True, locale: str | None = None
) -> InlineKeyboardMarkup:
    """Proof step: optional Skip, Done flush, Cancel."""
    buttons: list[InlineKeyboardButton] = []
    if skip_allowed:
        buttons.append(
            InlineKeyboardButton(
                t("button.skip", locale, plain=True),
                callback_data=f"{action}_skip_proof",
                style=KeyboardButtonStyle.PRIMARY,
            )
        )
    buttons.append(
        InlineKeyboardButton(
            t("button.done", locale, plain=True),
            callback_data=f"{action}_done_proof",
        )
    )
    buttons.append(
        InlineKeyboardButton(
            t("button.cancel", locale, plain=True),
            callback_data=f"{action}_cancel",
        )
    )
    return InlineKeyboardMarkup([buttons])


def connect_join_kb(
    join_callback: str, cancel_callback: str, locale: str | None = None
) -> InlineKeyboardMarkup:
    """Connect / Cancel keyboard attached to the join prompt."""
    return InlineKeyboardMarkup(
        [
            [
                InlineKeyboardButton(
                    t("button.connect", locale, plain=True),
                    callback_data=join_callback,
                    style=KeyboardButtonStyle.PRIMARY,
                ),
                InlineKeyboardButton(
                    t("button.cancel", locale, plain=True),
                    callback_data=cancel_callback,
                ),
            ]
        ]
    )
