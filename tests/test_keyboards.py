# © Copyright 2024 - 2026 Transsion Core
# © Copyright 2024 - 2026 Dizzy
# © Copyright 2026 Ave Studio

"""Tests for tcbot.modules.helper.keyboards - all keyboard factory functions."""

from __future__ import annotations

from telegram import InlineKeyboardMarkup

from tcbot.modules.helper import keyboards

# ───────────────────────────── Helper ───────────────────────────── #


def _rows(kb: InlineKeyboardMarkup) -> list[list[dict]]:
    return [
        [{"text": b.text, "cb": b.callback_data, "url": b.url} for b in row]
        for row in kb.inline_keyboard
    ]


# ──────────────────────── Start / main menu ─────────────────────── #


def test_main_menu_kb_has_three_rows() -> None:
    rows = _rows(keyboards.main_menu_kb())
    assert len(rows) == 3
    assert [b["text"] for b in rows[0]] == ["About", "Help"]
    assert rows[0][0]["cb"] == "about_menu"
    assert rows[0][1]["cb"] == "help_menu"
    assert rows[1][0]["cb"] == "additional_menu"
    assert rows[2][0]["cb"] == "privacy_menu"


def test_back_to_start_kb_single_back_button() -> None:
    rows = _rows(keyboards.back_to_start_kb())
    assert len(rows) == 1 and len(rows[0]) == 1
    assert rows[0][0]["cb"] == "back_to_start"


# ───────────────────────── Promo decision ───────────────────────── #


def test_promo_decision_kb_uses_colon_separator() -> None:
    rows = _rows(keyboards.promo_decision_kb("req-uuid"))
    assert rows[0][0]["cb"] == "promo_approve:req-uuid"
    assert rows[0][1]["cb"] == "promo_reject:req-uuid"


# ────── Ban log keyboards (positional args, not keyword-only) ───── #


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


# ─────────────────────────── Help menus ─────────────────────────── #


def test_help_modules_optional_back_to_start() -> None:
    sample = [[("A", "help_a"), ("B", "help_b")]]
    rows_no_back = _rows(keyboards.help_modules(sample, with_back_to_start=False))
    assert len(rows_no_back) == 1

    rows_with_back = _rows(keyboards.help_modules(sample, with_back_to_start=True))
    assert rows_with_back[-1][0]["cb"] == "back_to_start"
    assert "Back" in rows_with_back[-1][0]["text"]


def test_demote_confirm_kb_confirm_and_cancel() -> None:
    rows = _rows(keyboards.demote_confirm_kb(42))
    cbs = [b["cb"] for b in rows[0]]
    assert "demote_confirm:42" in cbs
    assert "demote_cancel:42" in cbs


def test_privacy_kb_has_two_rows() -> None:
    rows = _rows(keyboards.privacy_kb())
    assert rows[0][0]["cb"] == "privacy_policy_menu"
    assert rows[1][0]["cb"] == "back_to_start"


def test_main_menu_kb_returns_inline_markup() -> None:
    kb = keyboards.main_menu_kb()
    assert isinstance(kb, InlineKeyboardMarkup)


def test_back_to_start_kb_returns_inline_markup() -> None:
    kb = keyboards.back_to_start_kb()
    assert isinstance(kb, InlineKeyboardMarkup)


def test_ban_log_new_returns_inline_markup() -> None:
    kb = keyboards.ban_log_new(99, "https://t.me/c/1/1", "https://t.me/bot?start=x")
    assert isinstance(kb, InlineKeyboardMarkup)


def test_promo_decision_kb_returns_inline_markup() -> None:
    assert isinstance(keyboards.promo_decision_kb("uuid-x"), InlineKeyboardMarkup)


def test_help_modules_with_multiple_rows() -> None:
    sample = [[("A", "help_a")], [("B", "help_b"), ("C", "help_c")]]
    rows = _rows(keyboards.help_modules(sample, with_back_to_start=False))
    assert len(rows) == 2
    assert len(rows[1]) == 2


# ──────────────────── Privacy / back-to-privacy ─────────────────── #


def test_back_to_privacy_kb_returns_privacy_menu_callback() -> None:
    rows = _rows(keyboards.back_to_privacy_kb())
    assert len(rows) == 1 and len(rows[0]) == 1
    assert rows[0][0]["cb"] == "privacy_menu"


def test_back_to_privacy_kb_returns_inline_markup() -> None:
    assert isinstance(keyboards.back_to_privacy_kb(), InlineKeyboardMarkup)


# ─────────────────── Additional menu keyboard ───────────────────── #


def test_additional_menu_kb_has_four_rows() -> None:
    rows = _rows(keyboards.additional_menu_kb())
    assert len(rows) == 4


def test_additional_menu_kb_back_row_goes_to_start() -> None:
    rows = _rows(keyboards.additional_menu_kb())
    assert rows[-1][0]["cb"] == "back_to_start"


def test_additional_menu_kb_first_row_has_url_buttons() -> None:
    rows = _rows(keyboards.additional_menu_kb())
    for btn in rows[0]:
        assert btn["url"] and btn["url"].startswith("https://t.me/")


def test_additional_menu_kb_returns_inline_markup() -> None:
    assert isinstance(keyboards.additional_menu_kb(), InlineKeyboardMarkup)


# ─────────────────── Groups toggle keyboards ────────────────────── #


def test_groups_menu_kb_detailed_true_shows_simple_button() -> None:
    rows = _rows(keyboards.groups_menu_kb(True))
    assert rows[0][0]["cb"] == "menu_groups_simple"
    assert "Simple" in rows[0][0]["text"]


def test_groups_menu_kb_detailed_false_shows_details_button() -> None:
    rows = _rows(keyboards.groups_menu_kb(False))
    assert rows[0][0]["cb"] == "menu_groups_details"
    assert "Detail" in rows[0][0]["text"]


def test_groups_menu_kb_always_has_back_row() -> None:
    for detailed in (True, False):
        rows = _rows(keyboards.groups_menu_kb(detailed))
        assert rows[-1][0]["cb"] == "back_to_start"


def test_tcgroups_kb_detailed_shows_simple() -> None:
    rows = _rows(keyboards.tcgroups_kb(True))
    assert rows[0][0]["cb"] == "groups_simple"
    assert "Simple" in rows[0][0]["text"]


def test_tcgroups_kb_simple_shows_details() -> None:
    rows = _rows(keyboards.tcgroups_kb(False))
    assert rows[0][0]["cb"] == "groups_details"
    assert "Detail" in rows[0][0]["text"]


# ─────────────────────── Stats keyboards ────────────────────────── #


def test_stats_main_kb_has_three_rows() -> None:
    rows = _rows(keyboards.stats_main_kb())
    assert len(rows) == 3


def test_stats_main_kb_first_row_is_staff_roster() -> None:
    rows = _rows(keyboards.stats_main_kb())
    assert rows[0][0]["cb"] == "stats_admins"


def test_stats_main_kb_chats_row_starts_at_page_zero() -> None:
    rows = _rows(keyboards.stats_main_kb())
    assert rows[1][0]["cb"] == "stats_chats:0"


def test_stats_main_kb_bans_row_starts_at_page_zero() -> None:
    rows = _rows(keyboards.stats_main_kb())
    assert rows[2][0]["cb"] == "stats_bans:0"


def test_stats_back_kb_returns_to_stats_main() -> None:
    rows = _rows(keyboards.stats_back_kb())
    assert len(rows) == 1 and len(rows[0]) == 1
    assert rows[0][0]["cb"] == "stats_main"


# ──────────────── Group / help navigation keyboards ─────────────── #


def test_group_start_kb_has_pm_url_and_help_callback() -> None:
    rows = _rows(keyboards.group_start_kb("MyBot"))
    assert rows[0][0]["url"] == "https://t.me/MyBot?start=menu"
    assert rows[1][0]["cb"] == "help_menu_group"


def test_back_to_help_kb_goes_to_help_menu() -> None:
    rows = _rows(keyboards.back_to_help_kb())
    assert rows[0][0]["cb"] == "help_menu"


def test_back_to_help_cmd_kb_goes_to_helpc_main() -> None:
    rows = _rows(keyboards.back_to_help_cmd_kb())
    assert rows[0][0]["cb"] == "helpc_main"


def test_back_to_module_kb_uses_provided_callback() -> None:
    rows = _rows(keyboards.back_to_module_kb("help_banning"))
    assert rows[0][0]["cb"] == "help_banning"


# ──────────────── help_topics_menu_kb / help_topics_kb ──────────── #


def test_help_topics_menu_kb_appends_back_to_start() -> None:
    topics = [("Banning", "help_banning"), ("Kick", "help_kick")]
    rows = _rows(keyboards.help_topics_menu_kb(topics))
    assert rows[-1][0]["cb"] == "back_to_start"


def test_help_topics_kb_no_back_to_start() -> None:
    topics = [("Banning", "help_banning")]
    rows = _rows(keyboards.help_topics_kb(topics))
    cbs = [b["cb"] for row in rows for b in row]
    assert "back_to_start" not in cbs


def test_help_topics_menu_kb_pairs_topics_into_two_columns() -> None:
    topics = [("A", "cb_a"), ("B", "cb_b"), ("C", "cb_c")]
    rows = _rows(keyboards.help_topics_menu_kb(topics))
    assert len(rows[0]) == 2
    assert len(rows[1]) == 1


# ───────────── module_help_kb pairing behavior ──────────────────── #


def test_module_help_kb_pairs_even_sections() -> None:
    sections = [("A", "a"), ("B", "b"), ("C", "c"), ("D", "d")]
    rows = _rows(keyboards.module_help_kb(sections, "back_cb"))
    assert len(rows[0]) == 2
    assert len(rows[1]) == 2
    assert rows[-1][0]["cb"] == "back_cb"


def test_module_help_kb_odd_section_on_own_row() -> None:
    sections = [("A", "a"), ("B", "b"), ("C", "c")]
    rows = _rows(keyboards.module_help_kb(sections, "back_cb"))
    pair_row = rows[0]
    odd_row = rows[1]
    back_row = rows[2]
    assert len(pair_row) == 2
    assert len(odd_row) == 1
    assert back_row[0]["cb"] == "back_cb"


# ───────────── checkme keyboards ────────────────────────────────── #


def test_checkme_ban_kb_with_proof_has_two_first_row_buttons() -> None:
    rows = _rows(
        keyboards.checkme_ban_kb("Bot", "ban001", proof_link="https://t.me/c/1/5")
    )
    assert len(rows[0]) == 2
    assert rows[0][0]["cb"] == "checkme_detail:ban001"
    assert rows[0][1]["url"] == "https://t.me/c/1/5"
    assert "appeal_ban001" in rows[1][0]["url"]


def test_checkme_ban_kb_without_proof_has_one_first_row_button() -> None:
    rows = _rows(keyboards.checkme_ban_kb("Bot", "ban002"))
    assert len(rows[0]) == 1
    assert rows[0][0]["cb"] == "checkme_detail:ban002"


def test_checkme_detail_back_kb_with_proof_shows_proof_then_back() -> None:
    rows = _rows(
        keyboards.checkme_detail_back_kb("ban003", proof_link="https://t.me/c/2/9")
    )
    assert rows[0][0]["url"] == "https://t.me/c/2/9"
    assert rows[1][0]["cb"] == "checkme_back:ban003"


def test_checkme_detail_back_kb_without_proof_shows_only_back() -> None:
    rows = _rows(keyboards.checkme_detail_back_kb("ban004"))
    assert len(rows) == 1
    assert rows[0][0]["cb"] == "checkme_back:ban004"


# ─────────────── promote_role_kb layout ─────────────────────────── #


def test_promote_role_kb_cancel_always_last_row() -> None:
    rows = _rows(keyboards.promote_role_kb(99, ["admin", "tester"]))
    assert rows[-1][0]["cb"] == "promo_role_cancel:99"


def test_promote_role_kb_filters_unknown_roles() -> None:
    rows = _rows(keyboards.promote_role_kb(77, ["unknown_role"]))
    cbs = [b["cb"] for row in rows for b in row]
    assert all("unknown_role" not in cb for cb in cbs if "cancel" not in cb)
