# © Copyright 2024 - 2026 Transsion Core
# © Copyright 2024 - 2026 Dizzy
# © Copyright 2026 Ave Labs

"""Appeal tag matching and log-message reference checks."""

from __future__ import annotations

from tcbot.modules.helper.workflows.appeal_flow import (
    starts_with_appeal_tag,
    text_references_log_message,
)


def test_appeal_tag_case_insensitive_and_padded() -> None:
    assert starts_with_appeal_tag("#appeal text") is True
    assert starts_with_appeal_tag("#APPEAL text") is True
    assert starts_with_appeal_tag("#Appeal text") is True
    assert starts_with_appeal_tag("   #appeal text  ") is True


def test_appeal_tag_rejects_other_text() -> None:
    assert starts_with_appeal_tag("appeal text") is False
    assert starts_with_appeal_tag("") is False


def test_appeal_tag_is_prefix_not_token() -> None:
    # * The check is a plain prefix match, so "#appeals" also opens the flow.
    assert starts_with_appeal_tag("#appeals text") is True


def test_log_reference_matches_standalone_id() -> None:
    assert text_references_log_message("https://t.me/c/123/67?thread=1", 67) is True
    assert text_references_log_message("log 67 here", 67) is True


def test_log_reference_rejects_partial_numbers() -> None:
    assert text_references_log_message("670", 67) is False
    assert text_references_log_message("6", 67) is False
    assert text_references_log_message("no numbers", 67) is False
