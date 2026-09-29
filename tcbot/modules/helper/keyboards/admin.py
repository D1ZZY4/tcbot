# © Copyright 2024 - 2026 Transsion Core
# © Copyright 2024 - 2026 Dizzy
# © Copyright 2026 Ave Labs

"""Promotion and demotion keyboards."""

from __future__ import annotations

from telegram import InlineKeyboardButton, InlineKeyboardMarkup
from telegram.constants import KeyboardButtonStyle

from tcbot import database as db
from tcbot.utils.i18n import t


def promote_role_kb(
    target_id: int,
    available_roles: list[str],
    locale: str | None = None,
) -> InlineKeyboardMarkup:
    """Role picker for /tcpromote without a role argument.

    Labels render from ROLE_LABEL verbatim: ranks are canonical English
    identifiers like commands, per the translator contract.
    """
    buttons = [
        InlineKeyboardButton(
            db.users_roles.ROLE_LABEL[r],
            callback_data=f"promo_role:{r}:{target_id}",
            style=KeyboardButtonStyle.PRIMARY,
        )
        for r in available_roles
        if r in db.users_roles.ROLE_LABEL
    ]
    rows: list[list[InlineKeyboardButton]] = [
        buttons[i : i + 2] for i in range(0, len(buttons), 2)
    ]
    rows.append(
        [
            InlineKeyboardButton(
                t("button.cancel", locale, plain=True),
                callback_data=f"promo_role_cancel:{target_id}",
            )
        ]
    )
    return InlineKeyboardMarkup(rows)


def demote_confirm_kb(
    target_id: int, locale: str | None = None
) -> InlineKeyboardMarkup:
    """Demotion confirmation: Confirm plus Cancel."""
    return InlineKeyboardMarkup(
        [
            [
                InlineKeyboardButton(
                    t("button.confirm", locale, plain=True),
                    callback_data=f"demote_confirm:{target_id}",
                    style=KeyboardButtonStyle.DANGER,
                ),
                InlineKeyboardButton(
                    t("button.cancel", locale, plain=True),
                    callback_data=f"demote_cancel:{target_id}",
                ),
            ]
        ]
    )


def promo_decision_kb(
    request_id: str, locale: str | None = None
) -> InlineKeyboardMarkup:
    """Approve/Reject keyboard for promotion review cards."""
    return InlineKeyboardMarkup(
        [
            [
                InlineKeyboardButton(
                    t("button.approve", locale, plain=True),
                    callback_data=f"promo_approve:{request_id}",
                    style=KeyboardButtonStyle.SUCCESS,
                ),
                InlineKeyboardButton(
                    t("button.reject", locale, plain=True),
                    callback_data=f"promo_reject:{request_id}",
                    style=KeyboardButtonStyle.DANGER,
                ),
            ]
        ]
    )
