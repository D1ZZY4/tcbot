# © Copyright 2024 - 2026 Transsion Core
# © Copyright 2024 - 2026 Dizzy
# © Copyright 2026 Ave Labs

"""Argument notation in rich catalog copy must survive the HTML transport."""

from __future__ import annotations

import pytest

from tcbot.utils.i18n import t

_USAGE_KEYS = (
    "banning.error.reason_required",
    "disconnecting.state.usage",
    "maintenance.repair.usage",
    "maintenance.forget.usage",
)


@pytest.mark.parametrize("key", _USAGE_KEYS)
@pytest.mark.parametrize("locale", ["en-US", "id-ID"])
def test_usage_templates_escape_angle_brackets(key: str, locale: str) -> None:
    """A raw <token> would be parsed as a tag by the rich HTML renderer."""
    rendered = t(key, locale)
    assert "&lt;" in rendered
    assert "&gt;" in rendered
    assert "<target>" not in rendered
    assert "<chat_id>" not in rendered
    assert "<user_id>" not in rendered
    assert "<run_id>" not in rendered
