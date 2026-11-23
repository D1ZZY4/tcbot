# © Copyright 2024 - 2026 Transsion Core
# © Copyright 2024 - 2026 Dizzy
# © Copyright 2026 Ave Labs

"""The additional-links panel renders as rich blocks, not folded plain text."""

from __future__ import annotations

from tcbot.modules import additional


def test_additional_msg_renders_separate_paragraphs() -> None:
    """The heading and the hint must not collapse into one Telegram line."""
    text = additional.additional_msg("en-US")

    assert text.count("<p>") == 2
    assert "<b>Official Links</b>" in text
    assert "Use the buttons below" in text
