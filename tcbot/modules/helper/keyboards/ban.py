# © Copyright 2024 - 2026 Transsion Core
# © Copyright 2024 - 2026 Dizzy
# © Copyright 2026 Ave Labs

"""Ban, proof, and generic detail keyboards."""

from __future__ import annotations

from telegram import InlineKeyboardButton, InlineKeyboardMarkup
from telegram.constants import KeyboardButtonStyle

from tcbot.modules.helper.messages import appeal_deep_link
from tcbot.utils.i18n import t


def ban_log_kb(
    target_id: int,
    proof_link: str,
    appeal_url: str,
    locale: str | None = None,
    *,
    previous_proof_link: str | None = None,
) -> InlineKeyboardMarkup:
    """Ban-log keyboard with proof and appeal URL buttons, one per row.

    ``previous_proof_link`` adds the update-flow previous-proof row. One URL
    button per row: proof labels embed the target ID, so two of them side
    by side truncate on narrow clients.
    """
    rows = [
        [
            InlineKeyboardButton(
                t("button.proof_id", locale, id=target_id, plain=True),
                url=proof_link,
                style=KeyboardButtonStyle.PRIMARY,
            )
        ],
    ]
    if previous_proof_link:
        rows.append(
            [
                InlineKeyboardButton(
                    t("button.prev_proof_id", locale, id=target_id, plain=True),
                    url=previous_proof_link,
                    style=KeyboardButtonStyle.PRIMARY,
                )
            ]
        )
    if appeal_url:
        rows.append(
            [
                InlineKeyboardButton(
                    t("button.submit_appeal", locale, plain=True),
                    url=appeal_url,
                    style=KeyboardButtonStyle.PRIMARY,
                )
            ]
        )
    return InlineKeyboardMarkup(rows)


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


def join_ban_kb(
    log_url: str | None,
    proof_url: str | None,
    appeal_url: str | None,
    locale: str | None = None,
) -> InlineKeyboardMarkup | None:
    """Join-ban notice keyboard: log and proof first, appeal below.

    A missing link drops its button instead of leaving a dead URL, and the
    evidence row is omitted when neither reference exists. The appeal stays
    on its own row so the destructive action is never adjacent to the
    evidence links.
    """
    rows: list[list[InlineKeyboardButton]] = []
    evidence: list[InlineKeyboardButton] = []
    if log_url:
        evidence.append(
            InlineKeyboardButton(t("button.view_log", locale, plain=True), url=log_url)
        )
    if proof_url:
        evidence.append(
            InlineKeyboardButton(
                t("button.view_proof", locale, plain=True), url=proof_url
            )
        )
    if evidence:
        rows.append(evidence)
    if appeal_url:
        rows.append(
            [
                InlineKeyboardButton(
                    t("button.submit_appeal", locale, plain=True),
                    url=appeal_url,
                    style=KeyboardButtonStyle.PRIMARY,
                )
            ]
        )
    return InlineKeyboardMarkup(rows) if rows else None


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
