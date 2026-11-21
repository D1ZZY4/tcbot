# © Copyright 2024 - 2026 Transsion Core
# © Copyright 2024 - 2026 Dizzy
# © Copyright 2026 Ave Labs

"""Shared message style: heading, divider, and arrow bullets."""

from __future__ import annotations

from tcbot.modules.helper.messages.rich import apply_style
from tcbot.utils.formatter import BULLET, SECTION_RULE


def test_heading_gets_a_divider() -> None:
    styled = apply_style("*Ban issued*\nReason: spam")
    assert styled == f"*Ban issued*\n{SECTION_RULE}\nReason: spam"


def test_plain_message_gains_layout_without_entities() -> None:
    styled = apply_style("Ban issued\nReason: spam")
    assert styled == f"Ban issued\n{SECTION_RULE}\nReason: spam"
    assert "*" not in styled


def test_rich_message_bolds_its_first_line() -> None:
    styled = apply_style("Summary\nUser: `123`")
    assert styled.startswith(f"*Summary*\n{SECTION_RULE}\n")


def test_list_markers_become_arrows_with_bold_labels() -> None:
    styled = apply_style("Summary `1`\n- Owner: 1\n• Moderator: 2\n· Items: 3")
    assert f"{BULLET} *Owner:* 1" in styled
    assert f"{BULLET} *Moderator:* 2" in styled
    assert f"{BULLET} *Items:* 3" in styled


def test_already_styled_text_is_untouched() -> None:
    styled = f"*Heading*\n{SECTION_RULE}\n{BULLET} Item"
    assert apply_style(styled) == styled


def test_single_line_and_empty_text_are_untouched() -> None:
    assert apply_style("") == ""
    assert apply_style("Just one line") == "Just one line"


def test_escaped_markup_is_not_re_escaped() -> None:
    styled = apply_style("Halo\\- semua `1`\n- Nama: `123`")
    assert "Halo\\- semua" in styled
    assert f"{BULLET} *Nama:* `123`" in styled


def test_rich_message_without_a_boldable_heading_still_gets_a_rule() -> None:
    styled = apply_style("User \\*Al\\*\nReason: spam\n- Chat: `123`")
    assert styled.startswith(f"User \\*Al\\*\n{SECTION_RULE}\n")


def test_plain_escaped_message_keeps_zero_entities() -> None:
    styled = apply_style("Halo\\- semua\nNama: example")
    assert styled == f"Halo\\- semua\n{SECTION_RULE}\nNama: example"
