# © Copyright 2024 - 2026 Transsion Core
# © Copyright 2024 - 2026 Dizzy
# © Copyright 2026 Ave Labs

"""The appeal instruction prompt uses rich blocks for its required sections."""

from __future__ import annotations

from tcbot.modules.helper.pipelines.appeal_submit_flow import instruction_text


def test_instruction_text_uses_heading_and_checklist() -> None:
    text = instruction_text(community_name="TCF", log_channel="@logs", locale="en-US")
    assert text.startswith("<h2>TCF Ban Appeal</h2>")
    assert "<ul>" in text and "<li><input" in text
    assert "Log link" in text and "Clarification" in text and "Agreement" in text
    assert text.count("- *Log link:*") == 0
    assert "<blockquote" not in text
