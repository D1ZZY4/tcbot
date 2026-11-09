# © Copyright 2024 - 2026 Transsion Core
# © Copyright 2024 - 2026 Dizzy
# © Copyright 2026 Ave Labs

"""Ban-log keyboard keeps the proof row layout with or without a previous proof."""

from __future__ import annotations

from tcbot.modules.helper import keyboards as kb


def test_ban_log_kb_new_has_two_rows() -> None:
    markup = kb.ban_log_kb(7, "https://t.me/c/1/2", "https://t.me/p?start=ban_x")
    rows = markup.inline_keyboard
    assert len(rows) == 2
    assert rows[0][0].url == "https://t.me/c/1/2"
    assert rows[1][0].url == "https://t.me/p?start=ban_x"


def test_ban_log_kb_update_adds_previous_proof_row() -> None:
    markup = kb.ban_log_kb(
        7,
        "https://t.me/c/1/3",
        "https://t.me/p?start=ban_x",
        previous_proof_link="https://t.me/c/1/2",
    )
    rows = markup.inline_keyboard
    assert len(rows) == 3
    assert rows[0][0].url == "https://t.me/c/1/3"
    assert rows[1][0].url == "https://t.me/c/1/2"
    assert rows[2][0].url == "https://t.me/p?start=ban_x"
