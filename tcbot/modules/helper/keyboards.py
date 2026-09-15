# © Copyright 2024 - 2026 Transsion Core
# © Copyright 2024 - 2026 Dizzy
# © Copyright 2026 Ave Labs

"""All inline-keyboard factory functions used across moderation, appeal, and admin flows."""

from __future__ import annotations

import logging
from typing import TYPE_CHECKING

from telegram import InlineKeyboardButton, InlineKeyboardMarkup
from telegram.constants import KeyboardButtonStyle

from tcbot import cfg
from tcbot import database as db
from tcbot.modules.helper.parse_link import appeal_deep_link
from tcbot.utils.i18n import t
from tcbot.utils.pagination import nav_row

if TYPE_CHECKING:
    from collections.abc import Sequence

log = logging.getLogger(__name__)

# * Semantic button colors (PTB 22.7+, Bot API style field; older clients
# * render the same buttons without color, so styling is purely additive):
# * SUCCESS marks a final approval, DANGER a rejection or destructive
# * confirm, PRIMARY a continue/select step into a flow. Cancel, Back,
# * navigation, menus, toggles, and URL buttons stay unstyled (neutral).
# * See docs/reference/keyboard-styles.md for the full convention.


def _https_url(url: str, label: str) -> str | None:
    """Return ``url`` only for http(s) community links.

    Operator-supplied env URLs reach ``InlineKeyboardButton(url=...)``
    verbatim; a non-http(s) value would fail late at the Telegram API.
    Reject it here so the button is omitted and the misconfiguration is
    visible in logs instead of a broken menu.
    """
    if url and url.startswith(("https://", "http://")):
        return url
    if url:
        log.warning("Ignoring non-http(s) community URL for %s: %s", label, url)
    return None


# ──────────────────────────── Ban flow ──────────────────────────── #


def ban_log_new(
    target_id: int,
    proof_link: str,
    appeal_url: str,
    locale: str | None = None,
) -> InlineKeyboardMarkup:
    """Ban-log keyboard with explicit appeal URL."""
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
    """Return the ban-log keyboard with a previous-proof button and explicit appeal URL."""
    # * One URL button per row (keyboard-styles "Detail view" convention):
    # * proof labels embed the target ID, so two of them side by side
    # * truncate on narrow clients.
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

    URL buttons are omitted individually when their link is unavailable;
    the Cancel / Continue decision row is always present.
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
    """Single Submit Appeal URL button, or None when the bot username is unknown."""
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


# ─────────────── Mute / Kick / Warn proof button ────────────────── #


def action_proof_kb(
    target_id: int,
    proof_link: str | None,
    locale: str | None = None,
) -> InlineKeyboardMarkup | None:
    """Single-button keyboard with a proof URL, or None when no proof link is available."""
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


# ───────────────────────── Admin promotion ──────────────────────── #


def promote_role_kb(
    target_id: int,
    available_roles: list[str],
    locale: str | None = None,
) -> InlineKeyboardMarkup:
    """Role selection keyboard shown when /tcpromote is used without a role argument.

    Role labels render from ROLE_LABEL verbatim (operational exception to
    catalog localization): ranks are canonical English identifiers like
    commands, per the translator contract.
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
    """Confirm/Cancel keyboard for the demotion confirmation flow."""
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
    """Approve/Reject keyboard for promotion request review cards."""
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


# ───────────────────────────── Check-me ────────────────────────── #


def checkme_ban_kb(
    bot_username: str,
    ban_id: str,
    proof_link: str | None = None,
    locale: str | None = None,
) -> InlineKeyboardMarkup | None:
    """Summary view keyboard - Details | Proof (row 1), Appeal (row 2)."""
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
    """Detail view keyboard - optional Proof (row 1), Back (row 2)."""
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


# ─────────────────────── Start / Help menus ─────────────────────── #


def main_menu_kb(locale: str | None = None) -> InlineKeyboardMarkup:
    """Top-level start-menu keyboard: About, Help, Additional, Privacy, Language."""
    return InlineKeyboardMarkup(
        [
            [
                InlineKeyboardButton(
                    t("button.about", locale, plain=True),
                    callback_data="about_menu",
                    style=KeyboardButtonStyle.PRIMARY,
                ),
                InlineKeyboardButton(
                    t("button.help", locale, plain=True),
                    callback_data="help_menu",
                    style=KeyboardButtonStyle.PRIMARY,
                ),
            ],
            [
                InlineKeyboardButton(
                    t("button.additional", locale, plain=True),
                    callback_data="additional_menu",
                    style=KeyboardButtonStyle.PRIMARY,
                ),
                InlineKeyboardButton(
                    t("button.privacy", locale, plain=True),
                    callback_data="privacy_menu",
                    style=KeyboardButtonStyle.PRIMARY,
                ),
            ],
            [
                InlineKeyboardButton(
                    t("button.language", locale, plain=True),
                    callback_data="language_menu",
                    style=KeyboardButtonStyle.PRIMARY,
                )
            ],
        ]
    )


def group_start_kb(
    bot_username: str, locale: str | None = None
) -> InlineKeyboardMarkup:
    """Keyboard for /start sent inside a group - sends user to PM."""
    rows: list[list[InlineKeyboardButton]] = []
    if bot_username:
        rows.append(
            [
                InlineKeyboardButton(
                    t("button.open_pm", locale, plain=True),
                    url=f"https://t.me/{bot_username}?start=menu",
                    style=KeyboardButtonStyle.PRIMARY,
                )
            ]
        )
    rows.append(
        [
            InlineKeyboardButton(
                t("button.help", locale, plain=True),
                callback_data="help_menu_group",
                style=KeyboardButtonStyle.PRIMARY,
            )
        ]
    )
    return InlineKeyboardMarkup(rows)


def _build_topic_rows(
    topics: list[tuple[str, str]],
    *,
    style: KeyboardButtonStyle | None = None,
) -> list[list[InlineKeyboardButton]]:
    """Pair topics into two-column rows, with any odd item on its own row."""
    rows: list[list[InlineKeyboardButton]] = []
    for i in range(0, len(topics), 2):
        chunk = topics[i : i + 2]
        rows.append(
            [
                InlineKeyboardButton(text, callback_data=cb, style=style)
                for text, cb in chunk
            ]
        )
    return rows


def help_topics_menu_kb(
    topics: list[tuple[str, str]], locale: str | None = None
) -> InlineKeyboardMarkup:
    """Help index when reached via the start menu - includes « Back to start."""
    rows = _build_topic_rows(topics, style=KeyboardButtonStyle.PRIMARY)
    rows.append(
        [
            InlineKeyboardButton(
                t("button.back", locale, plain=True), callback_data="back_to_start"
            )
        ]
    )
    return InlineKeyboardMarkup(rows)


def help_topics_kb(topics: list[tuple[str, str]]) -> InlineKeyboardMarkup:
    """Help index when reached via /help command (PM or group) - no back to start."""
    return InlineKeyboardMarkup(
        _build_topic_rows(topics, style=KeyboardButtonStyle.PRIMARY)
    )


def back_to_start_kb(locale: str | None = None) -> InlineKeyboardMarkup:
    """Single Back button that returns the user to the start menu."""
    return InlineKeyboardMarkup(
        [
            [
                InlineKeyboardButton(
                    t("button.back", locale, plain=True),
                    callback_data="back_to_start",
                ),
            ]
        ]
    )


def back_to_help_kb(locale: str | None = None) -> InlineKeyboardMarkup:
    """Back to help index - used from menu-path topics (goes to help_menu)."""
    return InlineKeyboardMarkup(
        [
            [
                InlineKeyboardButton(
                    t("button.back", locale, plain=True), callback_data="help_menu"
                ),
            ]
        ]
    )


def back_to_help_cmd_kb(locale: str | None = None) -> InlineKeyboardMarkup:
    """Back to help index - used from command-path topics (goes to helpc_main)."""
    return InlineKeyboardMarkup(
        [
            [
                InlineKeyboardButton(
                    t("button.back", locale, plain=True), callback_data="helpc_main"
                ),
            ]
        ]
    )


def privacy_kb(locale: str | None = None) -> InlineKeyboardMarkup:
    """Privacy section keyboard: policy link + Back to start."""
    return InlineKeyboardMarkup(
        [
            [
                InlineKeyboardButton(
                    t("button.privacy_policy", locale, plain=True),
                    callback_data="privacy_policy_menu",
                    style=KeyboardButtonStyle.PRIMARY,
                )
            ],
            [
                InlineKeyboardButton(
                    t("button.back", locale, plain=True),
                    callback_data="back_to_start",
                )
            ],
        ]
    )


def privacy_policy_sections_kb(
    section_labels: list[str], locale: str | None = None
) -> InlineKeyboardMarkup:
    """Policy index keyboard: one button per section + Back to privacy data."""
    pairs: list[tuple[str, str]] = [
        (label, f"privacy_section_{idx}") for idx, label in enumerate(section_labels)
    ]
    rows = _build_topic_rows(pairs, style=KeyboardButtonStyle.PRIMARY)
    rows.append(
        [
            InlineKeyboardButton(
                t("button.back", locale, plain=True), callback_data="privacy_menu"
            )
        ]
    )
    return InlineKeyboardMarkup(rows)


def back_to_privacy_policy_kb(locale: str | None = None) -> InlineKeyboardMarkup:
    """Back to privacy policy section index from an individual section view."""
    return InlineKeyboardMarkup(
        [
            [
                InlineKeyboardButton(
                    t("button.back", locale, plain=True),
                    callback_data="privacy_policy_menu",
                )
            ]
        ]
    )


# ─────────────────── Additional / Groups menus ──────────────────── #


def additional_menu_kb(locale: str | None = None) -> InlineKeyboardMarkup:
    """Return the community links menu shown from the start menu.

    Each button row is only included when the corresponding env var URL is
    non-empty (COMMUNITY_CHANNEL_URL, COMMUNITY_GROUP_URL, COMMUNITY_LOGS_URL,
    COMMUNITY_EXEC_URL, COMMUNITY_TRAVEL_URL).  Rows with no configured URL are
    silently omitted so the keyboard stays clean for deployments that do not
    configure every link.
    """
    rows: list[list[InlineKeyboardButton]] = []

    channel_url = _https_url(cfg.community_channel_url, "channel")
    group_url = _https_url(cfg.community_group_url, "group")
    channel_btn = (
        InlineKeyboardButton(
            t("button.main_channel", locale, plain=True),
            url=channel_url,
            style=KeyboardButtonStyle.PRIMARY,
        )
        if channel_url
        else None
    )
    group_btn = (
        InlineKeyboardButton(
            t("button.discussion_group", locale, plain=True),
            url=group_url,
            style=KeyboardButtonStyle.PRIMARY,
        )
        if group_url
        else None
    )
    if channel_btn or group_btn:
        rows.append([b for b in (channel_btn, group_btn) if b is not None])

    logs_url = _https_url(cfg.community_logs_url, "logs")
    exec_url = _https_url(cfg.community_exec_url, "exec")
    logs_btn = (
        InlineKeyboardButton(
            t("button.logs_channel", locale, plain=True),
            url=logs_url,
            style=KeyboardButtonStyle.PRIMARY,
        )
        if logs_url
        else None
    )
    exec_btn = (
        InlineKeyboardButton(
            t("button.exec_group", locale, plain=True),
            url=exec_url,
            style=KeyboardButtonStyle.PRIMARY,
        )
        if exec_url
        else None
    )
    if logs_btn or exec_btn:
        rows.append([b for b in (logs_btn, exec_btn) if b is not None])

    travel_url = _https_url(cfg.community_travel_url, "travel")
    if travel_url:
        rows.append(
            [
                InlineKeyboardButton(
                    t("button.travel", locale, plain=True),
                    url=travel_url,
                    style=KeyboardButtonStyle.PRIMARY,
                )
            ]
        )

    rows.append(
        [
            InlineKeyboardButton(
                t("button.back", locale, plain=True), callback_data="back_to_start"
            )
        ]
    )
    return InlineKeyboardMarkup(rows)


def groups_menu_kb(
    *, detailed: bool, locale: str | None = None
) -> InlineKeyboardMarkup:
    """Detailed/Simple toggle keyboard for the start-menu groups list."""
    toggle = InlineKeyboardButton(
        t("button.simple", locale, plain=True)
        if detailed
        else t("button.details_toggle", locale, plain=True),
        callback_data="menu_groups_simple" if detailed else "menu_groups_details",
        style=KeyboardButtonStyle.PRIMARY,
    )
    back = InlineKeyboardButton(
        t("button.back", locale, plain=True), callback_data="back_to_start"
    )
    return InlineKeyboardMarkup([[toggle, back]])


def tcgroups_kb(*, detailed: bool, locale: str | None = None) -> InlineKeyboardMarkup:
    """Toggle keyboard for the /tcgroups command: Simple/Details switch."""
    label = (
        t("button.simple", locale, plain=True)
        if detailed
        else t("button.details_toggle", locale, plain=True)
    )
    callback = "groups_simple" if detailed else "groups_details"
    return InlineKeyboardMarkup(
        [
            [
                InlineKeyboardButton(
                    label,
                    callback_data=callback,
                    style=KeyboardButtonStyle.PRIMARY,
                )
            ]
        ]
    )


# ─────────────────── Paginated drill-down lists ─────────────────── #


def paged_drill_kb(
    items: Sequence[tuple[str, str]],
    *,
    page: int,
    total_pages: int,
    nav_prefix: str,
    back_callback: str,
    extra_rows: Sequence[Sequence[InlineKeyboardButton]] | None = None,
    per_row: int = 3,
    locale: str | None = None,
) -> InlineKeyboardMarkup:
    """Numbered drill-in grid plus nav row, optional extra rows, and back.

    ``items`` carries (label, callback_data) per drill-in button; labels are
    caller-chosen (page-relative ``1..N`` or absolute record numbers) while
    the grid shape is shared. Single owner for the numbered-grid look (also
    the one place numbered buttons gain their PRIMARY style), used by the
    stats and check drill-downs instead of three local copies.
    """
    rows: list[list[InlineKeyboardButton]] = [
        [
            InlineKeyboardButton(
                label, callback_data=cb, style=KeyboardButtonStyle.PRIMARY
            )
            for label, cb in items[i : i + per_row]
        ]
        for i in range(0, len(items), per_row)
    ]
    nav = nav_row(page, total_pages, nav_prefix, locale)
    if nav:
        rows.append(nav)
    if extra_rows:
        rows.extend([list(row) for row in extra_rows])
    rows.append(
        [
            InlineKeyboardButton(
                t("button.back", locale, plain=True), callback_data=back_callback
            )
        ]
    )
    return InlineKeyboardMarkup(rows)


# ─────────────────── Flow-step keyboards ─────────────────── #
# * Single source for every step keyboard in the moderation, proof,
# * connect, stats, and check flows. Flow classes keep thin delegating
# * methods so call sites stay unchanged while the markup lives here.


def reason_step_kb(
    action: str, *, skip_allowed: bool = True, locale: str | None = None
) -> InlineKeyboardMarkup:
    """Reason-step keyboard: optional Skip plus Cancel."""
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
    """Proof-step keyboard: optional Skip, Done flush, Cancel."""
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
    """Connect / Cancel inline keyboard attached to the join prompt."""
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


def stats_back_row(locale: str | None = None) -> list[InlineKeyboardButton]:
    """Single Back button row returning to the stats main menu."""
    return [
        InlineKeyboardButton(
            t("button.back", locale, plain=True), callback_data="stats_main"
        )
    ]


def stats_main_kb(
    *, show_users: bool = False, locale: str | None = None
) -> InlineKeyboardMarkup:
    """Top-level ``/tcstats`` menu: Staff / Bans / Chats drill-downs.

    The ``Users`` list carries every cached user ID, so its button is shown
    only to the Owner/Founder (row 3); everyone else gets rows 1-2 only.
    The ``stats_users`` callbacks enforce the same gate, so a stale or
    crafted tap without the button still cannot open the list.
    """
    rows = [
        [
            InlineKeyboardButton(
                t("stats.button.roster", locale, plain=True),
                callback_data="stats_admins",
                style=KeyboardButtonStyle.PRIMARY,
            ),
            InlineKeyboardButton(
                t("stats.button.bans", locale, plain=True),
                callback_data="stats_bans:0",
                style=KeyboardButtonStyle.PRIMARY,
            ),
        ],
        [
            InlineKeyboardButton(
                t("stats.button.chats", locale, plain=True),
                callback_data="stats_chats:0",
                style=KeyboardButtonStyle.PRIMARY,
            ),
        ],
    ]
    if show_users:
        rows.append(
            [
                InlineKeyboardButton(
                    t("stats.button.users", locale, plain=True),
                    callback_data="stats_users:0",
                    style=KeyboardButtonStyle.PRIMARY,
                )
            ]
        )
    return InlineKeyboardMarkup(rows)


def stats_back_kb(locale: str | None = None) -> InlineKeyboardMarkup:
    """Single Back button returning to the stats main menu."""
    return InlineKeyboardMarkup([stats_back_row(locale)])


def stats_list_kb(
    page: int,
    total_pages: int,
    n_items: int,
    cb_prefix: str,
    item_cb_prefix: str,
    *,
    extra_row: list[InlineKeyboardButton] | None = None,
    item_ids: list[str] | None = None,
    locale: str | None = None,
) -> InlineKeyboardMarkup:
    """Compose nav + numbered detail buttons + optional extra row + back.

    ``item_ids`` carries one stable entity ID per button (user ID, chat ID,
    or ban ID). Detail handlers verify the resolved record still carries
    that ID so a list mutation between render and tap cannot silently show
    a different record. Older buttons without the segment keep working.
    """

    def _callback(i: int) -> str:
        base = f"{item_cb_prefix}:{page}:{i}"
        if item_ids is not None and i < len(item_ids):
            return f"{base}:{item_ids[i]}"
        return base

    return paged_drill_kb(
        [(str(i + 1), _callback(i)) for i in range(n_items)],
        page=page,
        total_pages=total_pages,
        nav_prefix=cb_prefix,
        back_callback="stats_main",
        extra_rows=[extra_row] if extra_row is not None else None,
        per_row=3,
        locale=locale,
    )


def stats_search_panel_kb(locale: str | None = None) -> InlineKeyboardMarkup:
    """Search panel keyboard: Cancel only."""
    return InlineKeyboardMarkup(
        [
            [
                InlineKeyboardButton(
                    t("button.cancel", locale, plain=True),
                    callback_data="stats_search_cancel",
                )
            ]
        ]
    )


def stats_search_row(locale: str | None = None) -> list[InlineKeyboardButton]:
    """Single Search button row opening the bans search panel."""
    return [
        InlineKeyboardButton(
            t("button.search", locale, plain=True),
            callback_data="stats_bans_search",
            style=KeyboardButtonStyle.PRIMARY,
        ),
    ]


def stats_search_results_kb(
    n: int, locale: str | None = None, *, item_ids: list[str] | None = None
) -> InlineKeyboardMarkup:
    """Numbered search-result buttons plus New Search / Cancel row.

    ``item_ids`` carries one stable ban ID per button; the detail handler
    verifies the resolved record still carries that ID so a list mutation
    between render and tap cannot silently show a different ban. Older
    buttons without the segment keep working.
    """
    num_btns = [
        InlineKeyboardButton(
            str(i + 1),
            callback_data=(
                f"stats_search_item:{i}:{item_ids[i]}"
                if item_ids is not None and i < len(item_ids)
                else f"stats_search_item:{i}"
            ),
            style=KeyboardButtonStyle.PRIMARY,
        )
        for i in range(n)
    ]
    rows: list[list[InlineKeyboardButton]] = [
        num_btns[i : i + 3] for i in range(0, len(num_btns), 3)
    ]
    rows.append(
        [
            InlineKeyboardButton(
                t("button.new_search", locale, plain=True),
                callback_data="stats_bans_search",
                style=KeyboardButtonStyle.PRIMARY,
            ),
            InlineKeyboardButton(
                t("button.cancel", locale, plain=True),
                callback_data="stats_search_cancel",
            ),
        ]
    )
    return InlineKeyboardMarkup(rows)


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


# * Per-group warn button titles embed the group name; truncate so a long
# * group title cannot blow up the button layout.
_WARN_GROUP_TITLE_MAX: int = 24


def check_warn_groups_kb(
    target_id: int,
    groups: list[tuple[str, int, int]],
    locale: str | None = None,
) -> InlineKeyboardMarkup:
    """Warns-by-group list: one drill-in button per group plus back row.

    ``groups`` carries (title, warn_count, chat_id) per group.
    """
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
    """Check-profile dashboard: Bans/Appeals, Warnings, Kicks/Mutes buttons."""
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


# ───────────────────────── Appeal flow ─────────────────────────── #


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
    """Approve / Reject keyboard attached to the staff review card."""
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


# ───────────────────── Module help sub-menu ─────────────────────── #


def module_help_kb(
    section_buttons: list[tuple[str, str]],
    back_callback: str,
    locale: str | None = None,
) -> InlineKeyboardMarkup:
    """Per-module help view: pair sub-section buttons + Back, with Back last."""
    rows = _build_topic_rows(section_buttons, style=KeyboardButtonStyle.PRIMARY)
    rows.append(
        [
            InlineKeyboardButton(
                t("button.back", locale, plain=True), callback_data=back_callback
            )
        ]
    )
    return InlineKeyboardMarkup(rows)


def back_to_module_kb(
    module_callback: str, locale: str | None = None
) -> InlineKeyboardMarkup:
    """Single « Back button that returns to the module help view."""
    return InlineKeyboardMarkup(
        [
            [
                InlineKeyboardButton(
                    t("button.back", locale, plain=True),
                    callback_data=module_callback,
                )
            ]
        ]
    )


# ───────────────────────── Language menu ────────────────────────── #


def language_list_kb(
    scope: str,
    items: list[tuple[str, str]],
    *,
    back_label: str | None = None,
    back_callback: str | None = None,
    selected: str | None = None,
    locale: str | None = None,
) -> InlineKeyboardMarkup:
    """Language options: one button per locale plus an optional Back row.

    ``items`` carries (display_name, locale_code) and each button sends
    ``lang:set:<scope>:<locale>``. The ``selected`` locale (the current
    setting) gets a ``✓`` text prefix, which is a plain check character,
    not an emoji. The Back row (only when ``back_callback`` is given)
    sends that callback verbatim, so the start-menu path can return to
    ``back_to_start`` while the command path omits it. The Back label
    renders from the button catalog in ``locale`` unless ``back_label``
    overrides it explicitly.
    """
    rows = [
        [
            InlineKeyboardButton(
                f"✓ {name}" if code == selected else name,
                callback_data=f"lang:set:{scope}:{code}",
                style=KeyboardButtonStyle.PRIMARY,
            )
        ]
        for name, code in items
    ]
    if back_callback is not None:
        label = (
            back_label
            if back_label is not None
            else t("button.back", locale, plain=True)
        )
        rows.append([InlineKeyboardButton(label, callback_data=back_callback)])
    return InlineKeyboardMarkup(rows)
