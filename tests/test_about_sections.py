# © Copyright 2024 - 2026 Transsion Core
# © Copyright 2024 - 2026 Dizzy
# © Copyright 2026 Ave Labs

"""About panels render as an index and three rich section pages."""

from __future__ import annotations

from tcbot.modules.helper.buttons import about_sections_btn, back_to_about_btn
from tcbot.modules.helper.messages import (
    about_msg,
    about_section_labels,
    about_section_msg,
)


def test_index_carries_one_button_per_section() -> None:
    labels = about_section_labels("en-US")
    assert len(labels) == 3
    markup = about_sections_btn(labels, "en-US")
    callbacks = [
        button.callback_data for row in markup.inline_keyboard for button in row
    ]
    assert callbacks[:3] == ["about_section_0", "about_section_1", "about_section_2"]
    assert "back_to_start" in callbacks


def test_index_uses_rich_blocks() -> None:
    text = about_msg("en-US")
    assert "<h2>" in text
    assert "<p>" in text
    assert "<hr/>" in text


def test_each_section_renders_its_items() -> None:
    expected = (
        ("The Federation", 4),
        ("Membership", 4),
        ("Clarification", 3),
    )
    for idx, (label, count) in enumerate(expected):
        text = about_section_msg(idx, "en-US")
        assert f"<h3>{label}</h3>" in text
        assert text.count("<li>") == count
        assert "<ul>" in text


def test_section_back_button_returns_to_index() -> None:
    markup = back_to_about_btn("en-US")
    assert markup.inline_keyboard[0][0].callback_data == "about_menu"
