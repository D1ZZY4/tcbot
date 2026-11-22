# © Copyright 2024 - 2026 Transsion Core
# © Copyright 2024 - 2026 Dizzy
# © Copyright 2026 Ave Labs

"""Rich messages carry their own markup; the style pass is a no-op."""

from __future__ import annotations

from tcbot.modules.helper.messages.rich_text import style


def test_style_returns_rich_text_verbatim() -> None:
    text = "<b>Ban issued</b>\n<code>abc</code>"
    assert style(text) == text


def test_style_returns_plain_notice_verbatim() -> None:
    text = "Halo semua\nNama: example"
    assert style(text) == text


def test_style_handles_empty_text() -> None:
    assert style("") == ""
