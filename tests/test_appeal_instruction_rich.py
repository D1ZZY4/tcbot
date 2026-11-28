# © Copyright 2024 - 2026 Transsion Core
# © Copyright 2024 - 2026 Dizzy
# © Copyright 2026 Ave Labs

"""The appeal instruction prompt uses rich blocks for its required sections."""

from __future__ import annotations

import pytest

from tcbot.modules.helper.pipelines.appeal_submit import instruction_text
from tcbot.utils.i18n import Safe, link, t


def test_instruction_text_uses_heading_and_checklist() -> None:
    text = instruction_text(community_name="TCF", log_channel="@logs", locale="en-US")
    assert text.startswith("<h2>TCF Ban Appeal</h2>")
    assert "<ul>" in text and "<li><input" in text
    assert "Log link" in text and "Clarification" in text and "Agreement" in text
    assert text.count("- *Log link:*") == 0
    assert "<blockquote" not in text
    assert "https://t.me/logs/1" in text


def test_instruction_example_link_is_not_nested() -> None:
    """A resolved channel URL must not be pasted into another t.me URL."""
    text = instruction_text(
        community_name="TCF",
        log_channel="https://t.me/FedLogs",
        locale="en-US",
    )
    assert "https://t.me/https://" not in text
    assert "https://t.me/FedLogs/1" in text


def test_instruction_example_link_handles_a_numeric_chat() -> None:
    """A supergroup id produces a t.me/c/ example link."""
    text = instruction_text(
        community_name="TCF",
        log_channel="-1001234567890",
        locale="en-US",
    )
    assert "https://t.me/c/1234567890/1" in text


def test_instruction_quotes_the_bans_real_log_message() -> None:
    """The example must be the link the submit step will actually accept."""
    text = instruction_text(
        community_name="TCF",
        log_channel="https://t.me/FedLogs",
        locale="en-US",
        log_message_id=743,
    )
    assert "https://t.me/FedLogs/743" in text
    assert "https://t.me/FedLogs/1" not in text


def test_numeric_log_channel_uses_the_real_message_id() -> None:
    text = instruction_text(
        community_name="TCF",
        log_channel="-1001234567890",
        locale="en-US",
        log_message_id=743,
    )
    assert "https://t.me/c/1234567890/743" in text


@pytest.mark.parametrize("locale", ["en-US", "id-ID"])
def test_invalid_log_reply_names_the_expected_link(locale: str) -> None:
    """A rejected appeal tells the member which message id was expected."""
    text = t(
        "appeals.submit.invalid_log",
        locale,
        log_link=Safe(link("Log message", "https://t.me/c/1234567890/743")),
        plain=True,
    )
    assert "https://t.me/c/1234567890/743" in text


@pytest.mark.parametrize(
    ("locale", "expected"),
    [("en-US", "Log message"), ("id-ID", "Pesan log")],
)
def test_invalid_log_notice_label_is_localized(locale: str, expected: str) -> None:
    assert t("appeals.submit.log_link_label", locale, plain=True) == expected


def test_invite_link_falls_back_to_the_chat_id() -> None:
    """An invite link cannot address a message, so the numeric form is shown."""
    text = instruction_text(
        community_name="TCF",
        log_channel="https://t.me/+invite-code",
        locale="en-US",
        log_message_id=743,
        log_chat_id=-1001234567890,
    )
    assert "https://t.me/c/1234567890/743" in text
