# © Copyright 2024 - 2026 Transsion Core
# © Copyright 2024 - 2026 Dizzy
# © Copyright 2026 Aveum Apps

"""
Tests for tcbot.modules.helper.keyboards — all keyboard factory functions.
"""

from __future__ import annotations

from telegram import InlineKeyboardMarkup

from tcbot.modules.helper import keyboards


## ── Helper ─────────────────────────────────────────────────────────────

def _rows(kb: InlineKeyboardMarkup) -> list[list[dict]]:
    return [
        [{"text": b.text, "cb": b.callback_data, "url": b.url} for b in row]
        for row in kb.inline_keyboard
    ]


## ── Start / main menu ──────────────────────────────────────────────────────

def test_main_menu_kb_has_three_rows() -> None:
    rows = _rows(keyboards.main_menu_kb())
    assert len(rows) == 3
    assert [b["text"] for b in rows[0]] == ["About", "Help"]
    assert rows[0][0]["cb"] == "menu_about"
    assert rows[0][1]["cb"] == "menu_help"
    assert rows[1][0]["cb"] == "menu_additional"
    assert rows[2][0]["cb"] == "menu_privacy"


def test_back_to_start_kb_single_back_button() -> None:
    rows = _rows(keyboards.back_to_start_kb())
    assert len(rows) == 1 and len(rows[0]) == 1
    assert rows[0][0]["cb"] == "menu_back_start"


## ── Appeal flow ─────────────────────────────────────────────────────────────

def test_appeal_review_kb_callback_data_includes_ban_id() -> None:
    rows = _rows(keyboards.appeal_review_kb("ban_42_1714"))
    assert rows[0][0]["cb"] == "appeal_approve_ban_42_1714"
    assert rows[0][1]["cb"] == "appeal_reject_ban_42_1714"


def test_appeal_cancel_kb_is_single_cancel_button() -> None:
    rows = _rows(keyboards.appeal_cancel_kb())
    assert rows[0][0]["cb"] == "cancel_appeal"


## ── Promo decision ───────────────────────────────────────────────────────────

def test_promo_decision_kb_uses_colon_separator() -> None:
    rows = _rows(keyboards.promo_decision_kb("req-uuid"))
    assert rows[0][0]["cb"] == "promo_approve:req-uuid"
    assert rows[0][1]["cb"] == "promo_reject:req-uuid"


## ── Ban log keyboards (positional args, not keyword-only) ────────────────────

def test_ban_log_new_has_proof_and_appeal_rows() -> None:
    rows = _rows(
        keyboards.ban_log_new(
            99,
            "https://t.me/c/1234/5",
            "https://t.me/bot?start=appeal_99_1",
        )
    )
    assert rows[0][0]["text"] == "Proof 99"
    assert rows[0][0]["url"] == "https://t.me/c/1234/5"
    assert rows[1][0]["text"] == "Submit Appeal"
    assert rows[1][0]["url"] == "https://t.me/bot?start=appeal_99_1"


def test_ban_log_update_has_previous_proof_button() -> None:
    rows = _rows(
        keyboards.ban_log_update(
            99,
            "https://t.me/c/1234/5",
            "https://t.me/c/1234/4",
            "https://t.me/bot?start=appeal_99_2",
        )
    )
    assert [b["text"] for b in rows[0]] == ["Proof 99", "Previous Proof 99"]
    assert rows[1][0]["text"] == "Submit Appeal"


## ── Help menus ───────────────────────────────────────────────────────────────

def test_help_modules_optional_back_to_start() -> None:
    sample = [[("A", "help_a"), ("B", "help_b")]]
    rows_no_back = _rows(keyboards.help_modules(sample, with_back_to_start=False))
    assert len(rows_no_back) == 1

    rows_with_back = _rows(keyboards.help_modules(sample, with_back_to_start=True))
    assert rows_with_back[-1][0]["cb"] == "menu_back_start"
    assert "Back" in rows_with_back[-1][0]["text"]


def test_demote_confirm_kb_confirm_and_cancel() -> None:
    rows = _rows(keyboards.demote_confirm_kb(42))
    cbs = [b["cb"] for b in rows[0]]
    assert "demote_confirm:42" in cbs
    assert "demote_cancel:42" in cbs


def test_cancel_proof_kb_single_button() -> None:
    rows = _rows(keyboards.cancel_proof_kb())
    assert rows[0][0]["cb"] == "cancel_proof"


def test_privacy_kb_has_two_rows() -> None:
    rows = _rows(keyboards.privacy_kb())
    assert rows[0][0]["cb"] == "menu_privacy_policy"
    assert rows[1][0]["cb"] == "menu_back_start"
