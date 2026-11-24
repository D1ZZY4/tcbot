# © Copyright 2024 - 2026 Transsion Core
# © Copyright 2024 - 2026 Dizzy
# © Copyright 2026 Ave Labs

"""Inline keyboard labels, callback data, styles, and row layouts."""

from __future__ import annotations

import asyncio
from typing import Any, cast

from pyrogram.enums import ButtonStyle as KeyboardButtonStyle

from tcbot.modules.helper import buttons as btn
from tcbot.modules.helper.buttons import menus as menu_btn
from tcbot.modules.helper.buttons import rules as rule_btn
from tcbot.modules.helper.buttons.common import close_btn
from tcbot.modules.helper.messages import links as community_links


def test_every_open_in_pm_button_shares_the_start_menu_link() -> None:
    direct = btn.open_pm_btn("tcbot", "menu", "en-US")
    group = btn.group_start_btn("tcbot", "en-US")
    assert direct is not None
    url = direct.inline_keyboard[0][0].url
    assert url == "https://t.me/tcbot?start=menu"
    assert btn.open_pm_btn("", "menu", "en-US") is None
    chosen = btn.open_pm_btn("tcbot", "tcrules", "en-US")
    assert chosen is not None
    assert chosen.inline_keyboard[0][0].url == "https://t.me/tcbot?start=tcrules"
    assert group.inline_keyboard[0][0].url == url
    assert [b.callback_data for b in group.inline_keyboard[1]] == ["help_menu_group"]


def _cells(markup):  # type: ignore[no-untyped-def]
    """Flatten a markup into (text, callback_data, url, style) rows for assertions."""
    return [
        [(b.text, b.callback_data, b.url, b.to_dict().get("style")) for b in row]
        for row in markup.inline_keyboard
    ]


def test_promote_role_btn_pairs_roles_plus_cancel() -> None:
    rows = _cells(btn.promote_role_btn(7, ["admin", "developer", "moderator"]))
    assert rows[0] == [
        ("Admin", "promo_role:admin:7", None, KeyboardButtonStyle.PRIMARY),
        ("Developer", "promo_role:developer:7", None, KeyboardButtonStyle.PRIMARY),
    ]
    assert rows[1] == [
        ("Moderator", "promo_role:moderator:7", None, KeyboardButtonStyle.PRIMARY)
    ]
    assert rows[2] == [
        ("🗶 Cancel", "promo_role_cancel:7", None, KeyboardButtonStyle.DANGER)
    ]


def test_promote_role_btn_skips_unknown_roles() -> None:
    rows = _cells(btn.promote_role_btn(7, ["admin", "nope"]))
    assert len(rows) == 2
    assert rows[0][0][1] == "promo_role:admin:7"


def test_demote_confirm_btn_marks_confirm_danger() -> None:
    rows = _cells(btn.demote_confirm_btn(7))
    assert rows == [
        [
            ("🗸 Confirm", "demote_confirm:7", None, KeyboardButtonStyle.DANGER),
            ("🗶 Cancel", "demote_cancel:7", None, KeyboardButtonStyle.DANGER),
        ]
    ]


def test_promo_decision_btn_success_and_danger() -> None:
    rows = _cells(btn.promo_decision_btn("r1"))
    assert rows == [
        [
            ("🗸 Approve", "promo_approve:r1", None, KeyboardButtonStyle.SUCCESS),
            ("🗶 Reject", "promo_reject:r1", None, KeyboardButtonStyle.DANGER),
        ]
    ]


def test_checkme_ban_btn_rows_and_links() -> None:
    rows = _cells(btn.checkme_ban_btn("bot", "a" * 10, "https://t.me/x/1"))
    assert rows[0][0][:2] == ("↧ Details", "checkme_detail:" + "a" * 10)
    assert rows[0][1][2] == "https://t.me/x/1"
    assert rows[1][0][2] == "https://t.me/bot?start=appeal_" + "a" * 10
    assert all(cell[3] == KeyboardButtonStyle.PRIMARY for row in rows for cell in row)


def test_checkme_ban_btn_without_username_is_none() -> None:
    assert btn.checkme_ban_btn("", "a" * 10) is None


def test_appeal_button_btn_guards() -> None:
    assert btn.appeal_button_btn("", "a" * 10) is None
    rows = _cells(btn.appeal_button_btn("bot", "a" * 10))
    assert rows[0][0][2] == "https://t.me/bot?start=appeal_" + "a" * 10


def test_action_proof_btn_guards() -> None:
    assert btn.action_proof_btn(1, None) is None
    rows = _cells(btn.action_proof_btn(1, "https://t.me/x/1"))
    assert rows == [
        [("🖈 Proof 1", None, "https://t.me/x/1", KeyboardButtonStyle.PRIMARY)]
    ]


def test_ban_update_confirm_btn_rows_callbacks_and_links() -> None:
    rows = _cells(
        btn.ban_update_confirm_btn("https://t.me/x/log", "https://t.me/x/proof")
    )
    assert rows[0] == [
        ("↝ View Log", None, "https://t.me/x/log", KeyboardButtonStyle.PRIMARY),
        ("🖈 View Proof", None, "https://t.me/x/proof", KeyboardButtonStyle.PRIMARY),
    ]
    assert rows[1] == [
        ("🗶 Cancel", "ban_cancel", None, KeyboardButtonStyle.DANGER),
        ("↦ Continue", "ban_continue", None, KeyboardButtonStyle.PRIMARY),
    ]


def test_ban_update_confirm_btn_omits_missing_urls() -> None:
    rows = _cells(btn.ban_update_confirm_btn(None, None))
    assert rows == [
        [
            ("🗶 Cancel", "ban_cancel", None, KeyboardButtonStyle.DANGER),
            ("↦ Continue", "ban_continue", None, KeyboardButtonStyle.PRIMARY),
        ]
    ]
    rows = _cells(btn.ban_update_confirm_btn("https://t.me/x/log", None))
    assert [c[0] for c in rows[0]] == ["↝ View Log"]
    assert len(rows) == 2


def test_groups_menu_pairs_toggle_with_back() -> None:
    rows = _cells(btn.groups_menu_btn(detailed=True))
    assert rows == [
        [
            ("↥ Simple", "menu_groups_simple", None, KeyboardButtonStyle.PRIMARY),
            ("⤎ Back", "back_to_start", None, KeyboardButtonStyle.SUCCESS),
        ]
    ]


def test_module_help_btn_pairs_sections_back_last() -> None:
    rows = _cells(btn.module_help_btn([("A", "a"), ("B", "b"), ("C", "c")], "back"))
    assert [c[0] for c in rows[0]] == ["A", "B"]
    assert [c[0] for c in rows[1]] == ["C"]
    assert rows[2] == [("⤎ Back", "back", None, KeyboardButtonStyle.SUCCESS)]


def test_additional_menu_uses_one_destination_per_row(
    monkeypatch: Any,
) -> None:
    """Channel, group plus appeals, logs, and Back each get their own row."""

    async def _resolve(_bot: Any, chat_id: int) -> str:
        return f"https://t.me/c/{chat_id}"

    monkeypatch.setattr(community_links, "resolve", _resolve)
    markup = asyncio.run(menu_btn.additional_menu_btn(cast("Any", None), "en-US"))
    rows = [[cell[0] for cell in row] for row in _cells(markup)]

    assert rows[0] == ["🕬 Main Channel"]
    assert rows[1] == ["🗪 Discussion Group", "🗫 Appeals Channel"]
    assert rows[2] == ["↝ Logs Channel"]
    assert rows[3] == ["⤎ Back"]


def test_main_menu_options_are_primary() -> None:
    rows = _cells(btn.main_menu_btn())
    options = [c for row in rows for c in row]
    assert [c[0] for c in options] == [
        "◈ About",
        "ⓘ Help",
        "☶ Additional",
        "◈ Privacy",
        "⌘ Language",
    ]
    assert all(c[3] == KeyboardButtonStyle.PRIMARY for c in options)
    assert rows[-1] == [
        ("⌘ Language", "language_menu", None, KeyboardButtonStyle.PRIMARY)
    ]


def test_appeal_review_btn_matches_handler_pattern() -> None:
    """Both verdict buttons name the review card the handler must match."""
    rows = _cells(btn.appeal_review_btn("abc123", 77, "en-US"))
    callbacks = [rows[0][0][1], rows[0][1][1]]
    assert callbacks == ["appeal_approve_abc123_77", "appeal_reject_abc123_77"]
    for callback in callbacks:
        assert isinstance(callback, str)
        assert callback.startswith(("appeal_approve_", "appeal_reject_"))
        assert ":" not in callback
        assert callback.rsplit("_", 1)[1].isdigit()


def test_check_back_markup_is_profile_back_row() -> None:
    assert _cells(btn.check_back_markup(7)) == [
        [("⤎ Back", "check_main:7", None, KeyboardButtonStyle.SUCCESS)]
    ]


def test_check_paged_markup_stacks_nav_above_back() -> None:
    nav = btn.check_back_row(7)
    back = btn.check_warns_back_row(7)
    assert _cells(btn.check_paged_markup(nav, back)) == [
        [("⤎ Back", "check_main:7", None, KeyboardButtonStyle.SUCCESS)],
        [("⤎ Back", "check_warns:7", None, KeyboardButtonStyle.SUCCESS)],
    ]
    assert _cells(btn.check_paged_markup(None, back)) == [
        [("⤎ Back", "check_warns:7", None, KeyboardButtonStyle.SUCCESS)]
    ]


def test_proof_done_is_success_and_cancel_stays_neutral() -> None:
    rows = _cells(btn.proof_step_btn("ban", skip_allowed=False))
    assert rows == [
        [
            ("🗸 Done", "ban_done_proof", None, KeyboardButtonStyle.SUCCESS),
            ("🗶 Cancel", "ban_cancel", None, KeyboardButtonStyle.DANGER),
        ]
    ]


def test_rules_editor_colors_commit_and_destruction() -> None:
    panel = _cells(rule_btn.editor_panel_btn(has_content=True))
    flat = {cell[1]: cell[3] for row in panel for cell in row}
    assert flat["rules_publish"] == KeyboardButtonStyle.SUCCESS
    assert flat["rules_discard"] == KeyboardButtonStyle.DANGER

    categories = _cells(
        rule_btn.categories_btn([{"category_key": "spam", "title": "Spam"}])
    )
    flat_categories = {cell[1]: cell[3] for row in categories for cell in row}
    assert flat_categories["rules_cat_del:spam"] == KeyboardButtonStyle.DANGER
    assert flat_categories["rules_cat_up:spam"] == KeyboardButtonStyle.PRIMARY

    confirm = _cells(rule_btn.confirm_btn("yes", "no"))
    assert confirm[0][0][3] == KeyboardButtonStyle.DANGER
    assert confirm[0][1][3] == KeyboardButtonStyle.DANGER


def test_close_button_dismisses_a_panel() -> None:
    button = close_btn("en-US")
    assert button.text == "🗶 Close"
    assert button.callback_data == "close_msg"
    assert button.to_dict().get("style") == KeyboardButtonStyle.DANGER

    rows = _cells(btn.stats_main_btn())
    callbacks = [cell[1] for row in rows for cell in row]
    assert "close_msg" in callbacks


def test_selected_language_is_success() -> None:
    rows = _cells(
        btn.language_list_btn(
            "user", [("English", "en-US"), ("Indonesia", "id-ID")], selected="id-ID"
        )
    )
    assert rows[0][0][3] == KeyboardButtonStyle.PRIMARY
    assert rows[1][0][3] == KeyboardButtonStyle.SUCCESS
