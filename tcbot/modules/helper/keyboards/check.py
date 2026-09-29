# © Copyright 2024 - 2026 Transsion Core
# © Copyright 2024 - 2026 Dizzy
# © Copyright 2026 Ave Labs

"""Check-profile dashboard, warn lists, and check-me detail keyboards."""

from __future__ import annotations

from telegram import InlineKeyboardButton, InlineKeyboardMarkup
from telegram.constants import KeyboardButtonStyle

from tcbot.modules.helper.parse_link import appeal_deep_link
from tcbot.utils.i18n import t

# * Warn button titles embed the group name; cap it so a long title cannot
# * blow up the button layout.
_WARN_GROUP_TITLE_MAX: int = 24


def check_back_row(
    target_id: int, locale: str | None = None
) -> list[InlineKeyboardButton]:
    """Single Back button row returning to the /check profile."""
    return [
        InlineKeyboardButton(
            t("button.back", locale, plain=True),
            callback_data=f"check_main:{target_id}",
        )
    ]


def check_warns_back_row(
    target_id: int, locale: str | None = None
) -> list[InlineKeyboardButton]:
    """Single Back button row returning to the warns-by-group list."""
    return [
        InlineKeyboardButton(
            t("button.back", locale, plain=True),
            callback_data=f"check_warns:{target_id}",
        )
    ]


def check_warn_groups_kb(
    target_id: int,
    groups: list[tuple[str, int, int]],
    locale: str | None = None,
) -> InlineKeyboardMarkup:
    """Warns-by-group list: one drill-in button per group plus back row."""
    rows: list[list[InlineKeyboardButton]] = [
        [
            InlineKeyboardButton(
                t(
                    "checking.warns.group_button",
                    locale,
                    title=title[:_WARN_GROUP_TITLE_MAX],
                    n=count,
                    plain=True,
                ),
                callback_data=f"check_warn_chat:{target_id}:{cid}:0",
                style=KeyboardButtonStyle.PRIMARY,
            )
        ]
        for title, count, cid in groups
    ]
    rows.append(check_back_row(target_id, locale))
    return InlineKeyboardMarkup(rows)


def check_profile_kb(
    target_id: int,
    *,
    ban_total: int,
    appeal_total: int,
    fed_warn_total: int,
    kick_total: int,
    mute_total: int,
    locale: str | None = None,
) -> InlineKeyboardMarkup:
    """Check-profile dashboard: Bans/Appeals, Warnings, Kicks/Mutes."""
    return InlineKeyboardMarkup(
        [
            [
                InlineKeyboardButton(
                    t("checking.profile.button.bans", locale, n=ban_total, plain=True),
                    callback_data=f"check_bans:{target_id}:0",
                    style=KeyboardButtonStyle.PRIMARY,
                ),
                InlineKeyboardButton(
                    t(
                        "checking.profile.button.appeals",
                        locale,
                        n=appeal_total,
                        plain=True,
                    ),
                    callback_data=f"check_appeals:{target_id}:0",
                    style=KeyboardButtonStyle.PRIMARY,
                ),
            ],
            [
                InlineKeyboardButton(
                    t(
                        "checking.profile.button.warnings",
                        locale,
                        n=fed_warn_total,
                        plain=True,
                    ),
                    callback_data=f"check_warns:{target_id}",
                    style=KeyboardButtonStyle.PRIMARY,
                ),
            ],
            [
                InlineKeyboardButton(
                    t(
                        "checking.profile.button.kicks",
                        locale,
                        n=kick_total,
                        plain=True,
                    ),
                    callback_data=f"check_kicks:{target_id}:0",
                    style=KeyboardButtonStyle.PRIMARY,
                ),
                InlineKeyboardButton(
                    t(
                        "checking.profile.button.mutes",
                        locale,
                        n=mute_total,
                        plain=True,
                    ),
                    callback_data=f"check_mutes:{target_id}:0",
                    style=KeyboardButtonStyle.PRIMARY,
                ),
            ],
        ]
    )


def checkme_ban_kb(
    bot_username: str,
    ban_id: str,
    proof_link: str | None = None,
    locale: str | None = None,
) -> InlineKeyboardMarkup | None:
    """Summary view: Details | Proof on row one, Appeal on row two."""
    if not bot_username:
        return None
    appeal_url = appeal_deep_link(bot_username, ban_id)
    row1 = [
        InlineKeyboardButton(
            t("button.details", locale, plain=True),
            callback_data=f"checkme_detail:{ban_id}",
            style=KeyboardButtonStyle.PRIMARY,
        )
    ]
    if proof_link:
        row1.append(
            InlineKeyboardButton(
                t("button.proof", locale, plain=True),
                url=proof_link,
                style=KeyboardButtonStyle.PRIMARY,
            )
        )
    return InlineKeyboardMarkup(
        [
            row1,
            [
                InlineKeyboardButton(
                    t("button.appeal", locale, plain=True),
                    url=appeal_url,
                    style=KeyboardButtonStyle.PRIMARY,
                )
            ],
        ]
    )


def checkme_detail_back_kb(
    ban_id: str,
    proof_link: str | None = None,
    locale: str | None = None,
) -> InlineKeyboardMarkup:
    """Detail view: optional Proof on row one, Back on row two."""
    rows: list[list[InlineKeyboardButton]] = []
    if proof_link:
        rows.append(
            [
                InlineKeyboardButton(
                    t("button.proof", locale, plain=True),
                    url=proof_link,
                    style=KeyboardButtonStyle.PRIMARY,
                )
            ]
        )
    rows.append(
        [
            InlineKeyboardButton(
                t("button.back", locale, plain=True),
                callback_data=f"checkme_back:{ban_id}",
            )
        ]
    )
    return InlineKeyboardMarkup(rows)
