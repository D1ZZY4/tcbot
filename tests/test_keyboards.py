# © Copyright 2024 - 2026 Transsion Core
# © Copyright 2024 - 2026 Dizzy
# © Copyright 2026 Ave Labs

"""Inline keyboard labels, callback data, styles, and row layouts."""

from __future__ import annotations

from telegram.constants import KeyboardButtonStyle

from tcbot.modules.helper import keyboards as kb


def _cells(markup):  # type: ignore[no-untyped-def]
    """Flatten a markup into (text, callback_data, url, style) rows for assertions."""
    return [
        [(b.text, b.callback_data, b.url, b.to_dict().get("style")) for b in row]
        for row in markup.inline_keyboard
    ]


def test_promote_role_kb_pairs_roles_plus_cancel() -> None:
    rows = _cells(kb.promote_role_kb(7, ["admin", "developer", "tester"]))
    assert rows[0] == [
        ("Admin", "promo_role:admin:7", None, KeyboardButtonStyle.PRIMARY),
        ("Developer", "promo_role:developer:7", None, KeyboardButtonStyle.PRIMARY),
    ]
    assert rows[1] == [
        ("Tester", "promo_role:tester:7", None, KeyboardButtonStyle.PRIMARY)
    ]
    assert rows[2] == [("Cancel", "promo_role_cancel:7", None, None)]


def test_promote_role_kb_skips_unknown_roles() -> None:
    rows = _cells(kb.promote_role_kb(7, ["admin", "nope"]))
    assert len(rows) == 2
    assert rows[0][0][1] == "promo_role:admin:7"


def test_demote_confirm_kb_marks_confirm_danger() -> None:
    rows = _cells(kb.demote_confirm_kb(7))
    assert rows == [
        [
            ("Confirm", "demote_confirm:7", None, KeyboardButtonStyle.DANGER),
            ("Cancel", "demote_cancel:7", None, None),
        ]
    ]


def test_promo_decision_kb_success_and_danger() -> None:
    rows = _cells(kb.promo_decision_kb("r1"))
    assert rows == [
        [
            ("Approve", "promo_approve:r1", None, KeyboardButtonStyle.SUCCESS),
            ("Reject", "promo_reject:r1", None, KeyboardButtonStyle.DANGER),
        ]
    ]


def test_checkme_ban_kb_rows_and_links() -> None:
    rows = _cells(kb.checkme_ban_kb("bot", "a" * 10, "https://t.me/x/1"))
    assert rows[0][0][:2] == ("Details", "checkme_detail:" + "a" * 10)
    assert rows[0][1][2] == "https://t.me/x/1"
    assert rows[1][0][2] == "https://t.me/bot?start=appeal_" + "a" * 10
    assert all(cell[3] == KeyboardButtonStyle.PRIMARY for row in rows for cell in row)


def test_checkme_ban_kb_without_username_is_none() -> None:
    assert kb.checkme_ban_kb("", "a" * 10) is None


def test_appeal_button_kb_guards() -> None:
    assert kb.appeal_button_kb("", "a" * 10) is None
    rows = _cells(kb.appeal_button_kb("bot", "a" * 10))
    assert rows[0][0][2] == "https://t.me/bot?start=appeal_" + "a" * 10


def test_action_proof_kb_guards() -> None:
    assert kb.action_proof_kb(1, None) is None
    rows = _cells(kb.action_proof_kb(1, "https://t.me/x/1"))
    assert rows == [
        [("Proof 1", None, "https://t.me/x/1", KeyboardButtonStyle.PRIMARY)]
    ]


def test_ban_update_confirm_kb_rows_callbacks_and_links() -> None:
    rows = _cells(
        kb.ban_update_confirm_kb("https://t.me/x/log", "https://t.me/x/proof")
    )
    assert rows[0] == [
        ("View Log", None, "https://t.me/x/log", None),
        ("View Proof", None, "https://t.me/x/proof", None),
    ]
    assert rows[1] == [
        ("Cancel", "ban_cancel", None, None),
        ("Continue", "ban_continue", None, KeyboardButtonStyle.PRIMARY),
    ]


def test_ban_update_confirm_kb_omits_missing_urls() -> None:
    rows = _cells(kb.ban_update_confirm_kb(None, None))
    assert rows == [
        [
            ("Cancel", "ban_cancel", None, None),
            ("Continue", "ban_continue", None, KeyboardButtonStyle.PRIMARY),
        ]
    ]
    rows = _cells(kb.ban_update_confirm_kb("https://t.me/x/log", None))
    assert [c[0] for c in rows[0]] == ["View Log"]
    assert len(rows) == 2


def test_groups_menu_pairs_toggle_with_back() -> None:
    rows = _cells(kb.groups_menu_kb(detailed=True))
    assert rows == [
        [
            ("Simple", "menu_groups_simple", None, KeyboardButtonStyle.PRIMARY),
            ("« Back", "back_to_start", None, None),
        ]
    ]


def test_module_help_kb_pairs_sections_back_last() -> None:
    rows = _cells(kb.module_help_kb([("A", "a"), ("B", "b"), ("C", "c")], "back"))
    assert [c[0] for c in rows[0]] == ["A", "B"]
    assert [c[0] for c in rows[1]] == ["C"]
    assert rows[2] == [("« Back", "back", None, None)]


def test_main_menu_options_are_primary() -> None:
    rows = _cells(kb.main_menu_kb())
    options = [c for row in rows for c in row]
    assert [c[0] for c in options] == [
        "About",
        "Help",
        "Additional",
        "Privacy",
        "Language",
    ]
    assert all(c[3] == KeyboardButtonStyle.PRIMARY for c in options)
    assert rows[-1] == [
        ("Language", "language_menu", None, KeyboardButtonStyle.PRIMARY)
    ]
