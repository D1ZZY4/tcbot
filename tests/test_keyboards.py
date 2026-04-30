# © Copyright 2024 - 2026 Transsion Core
# © Copyright 2024 - 2026 Dizzy
# © Copyright 2026 Aveum Apps
"""Tests for the inline keyboard factories in :mod:`tgbot_tcf.modules.keyboards`.

PROMPT Feature 26 requires the layouts below; these tests guard the row
shape and callback-data naming.
"""
from __future__ import annotations

from telegram import InlineKeyboardMarkup

from tgbot_tcf.modules import keyboards


def _rows(markup: InlineKeyboardMarkup) -> list[list[dict[str, str | None]]]:
    return [
        [
            {
                "text": btn.text,
                "callback_data": btn.callback_data,
                "url": btn.url,
            }
            for btn in row
        ]
        for row in markup.inline_keyboard
    ]


def test_start_menu_layout() -> None:
    rows = _rows(keyboards.start_menu())
    assert len(rows) == 4
    assert [b["text"] for b in rows[0]] == ["About", "Help"]
    assert rows[0][0]["callback_data"] == "menu_about"
    assert rows[1][1]["callback_data"] == "menu_additional"
    assert rows[2][0]["callback_data"] == "menu_information"
    assert rows[3][0]["callback_data"] == "menu_privacy"


def test_back_to_start_is_single_back_button() -> None:
    rows = _rows(keyboards.back_to_start())
    assert rows == [[{"text": "Back", "callback_data": "menu_back_start", "url": None}]]


def test_appeal_review_callback_data_includes_ban_id() -> None:
    rows = _rows(keyboards.appeal_review("ban_42_1714"))
    assert rows[0][0]["callback_data"] == "appeal_approve_ban_42_1714"
    assert rows[0][1]["callback_data"] == "appeal_reject_ban_42_1714"


def test_promotion_request_callback_data_includes_request_id() -> None:
    rows = _rows(keyboards.promotion_request("req-uuid"))
    assert rows[0][0]["callback_data"] == "approve_promote_req-uuid"
    assert rows[0][1]["callback_data"] == "reject_promote_req-uuid"


def test_ban_log_new_has_two_rows_with_proof_and_appeal() -> None:
    rows = _rows(
        keyboards.ban_log_new(
            target_id=99,
            proof_link="https://t.me/c/1234/5",
            appeal_url="https://t.me/bot?start=appeal_99_1",
        )
    )
    assert rows[0][0]["text"] == "Proof 99"
    assert rows[0][0]["url"] == "https://t.me/c/1234/5"
    assert rows[1][0]["text"] == "Submit Appeal"
    assert rows[1][0]["url"] == "https://t.me/bot?start=appeal_99_1"


def test_ban_log_update_includes_previous_proof_button() -> None:
    rows = _rows(
        keyboards.ban_log_update(
            target_id=99,
            proof_link="https://t.me/c/1234/5",
            previous_proof_link="https://t.me/c/1234/4",
            appeal_url="https://t.me/bot?start=appeal_99_2",
        )
    )
    assert [b["text"] for b in rows[0]] == ["Proof 99", "Previous Proof 99"]
    assert rows[1][0]["text"] == "Submit Appeal"


def test_help_modules_optional_back_to_start() -> None:
    sample_rows = [[("A", "help_a"), ("B", "help_b")]]
    rows_no_back = _rows(keyboards.help_modules(sample_rows, with_back_to_start=False))
    assert len(rows_no_back) == 1
    rows_with_back = _rows(
        keyboards.help_modules(sample_rows, with_back_to_start=True)
    )
    assert rows_with_back[-1][0]["callback_data"] == "menu_back_start"
