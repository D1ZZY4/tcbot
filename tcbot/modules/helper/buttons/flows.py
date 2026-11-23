# © Copyright 2024 - 2026 Transsion Core
# © Copyright 2024 - 2026 Dizzy
# © Copyright 2026 Ave Labs

"""Step buttons for the moderation, proof, and connect flows."""

from __future__ import annotations

from telegram import InlineKeyboardButton, InlineKeyboardMarkup
from telegram.constants import KeyboardButtonStyle

from tcbot.utils.i18n import t

# * Single owner for every flow-step keyboard. Flow classes keep thin
# * delegating methods so call sites stay unchanged while markup lives here.


def reason_step_btn(
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
            style=KeyboardButtonStyle.DANGER,
        )
    )
    return InlineKeyboardMarkup([buttons])


def proof_step_btn(
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
            style=KeyboardButtonStyle.SUCCESS,
        )
    )
    buttons.append(
        InlineKeyboardButton(
            t("button.cancel", locale, plain=True),
            callback_data=f"{action}_cancel",
            style=KeyboardButtonStyle.DANGER,
        )
    )
    return InlineKeyboardMarkup([buttons])


def connect_verify_btn(
    step: int,
    verify_callback: str,
    join_callback: str,
    cancel_callback: str,
    locale: str | None = None,
    *,
    total_steps: int = 6,
) -> InlineKeyboardMarkup:
    """Verification wizard: a navigation row plus a separate Cancel row.

    Prev returns to the previous page, Next advances, and Connect appears only
    on the last page. Keeping navigation and Cancel on separate rows makes the
    owner's path obvious and keeps a mis-tap on Cancel away from Next.
    """
    navigation: list[InlineKeyboardButton] = []
    if step > 0:
        navigation.append(
            InlineKeyboardButton(
                t("button.prev", locale, plain=True),
                callback_data=f"{verify_callback}_{step - 1}",
                style=KeyboardButtonStyle.SUCCESS,
            )
        )
    if step >= total_steps - 1:
        navigation.append(
            InlineKeyboardButton(
                t("button.connect", locale, plain=True),
                callback_data=join_callback,
                style=KeyboardButtonStyle.PRIMARY,
            )
        )
    else:
        navigation.append(
            InlineKeyboardButton(
                t("button.next", locale, plain=True),
                callback_data=f"{verify_callback}_{step + 1}",
                style=KeyboardButtonStyle.SUCCESS,
            )
        )
    return InlineKeyboardMarkup(
        [
            navigation,
            [
                InlineKeyboardButton(
                    t("button.cancel", locale, plain=True),
                    callback_data=cancel_callback,
                    style=KeyboardButtonStyle.DANGER,
                )
            ],
        ]
    )


def connect_join_btn(
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
                    style=KeyboardButtonStyle.DANGER,
                ),
            ]
        ]
    )
