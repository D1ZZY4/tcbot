# © Copyright 2024 - 2026 Transsion Core
# © Copyright 2024 - 2026 Dizzy
# © Copyright 2026 Ave Labs

"""Privacy panels use real rich blocks with a divider above the policy hint."""

from __future__ import annotations

import pytest

from tcbot.modules.privacy import (
    _SECTION_KEYS,
    _privacy_msg,
    _privacy_policy_index_msg,
    _section_body,
)

_LOCALES = ("en-US", "id-ID")


@pytest.mark.parametrize("locale", _LOCALES)
def test_summary_separates_visibility_from_the_policy_hint(locale: str) -> None:
    """The lookup notice and the tap hint must not fold into one paragraph."""
    text = _privacy_msg("TC Bot", locale)
    parts = text.split("<hr/>")

    assert len(parts) == 3
    assert "<ul>" in parts[1]
    assert "</code>" in parts[1] or "<code>" in parts[1]
    assert "<p>" in parts[2]
    assert "[privacy." not in text


@pytest.mark.parametrize("locale", _LOCALES)
def test_policy_index_is_built_from_rich_blocks(locale: str) -> None:
    text = _privacy_policy_index_msg("TC Bot", locale)

    assert text.startswith("<h2>")
    assert "<hr/>" in text
    assert text.endswith("</p>")
    assert "[privacy." not in text


@pytest.mark.parametrize("locale", _LOCALES)
@pytest.mark.parametrize("idx", range(len(_SECTION_KEYS)))
def test_every_section_has_a_list_and_a_footer(idx: int, locale: str) -> None:
    label, body = _section_body(idx, "TC Bot", locale)

    assert label and "[" not in label
    assert "<p>" in body
    assert "<ul>" in body
    assert "<hr/>" in body
    assert body.rstrip().endswith("</footer>")
    assert "[privacy." not in body
