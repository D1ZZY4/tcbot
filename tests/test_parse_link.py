# © Copyright 2024 - 2026 Transsion Core
# © Copyright 2024 - 2026 Dizzy
# © Copyright 2026 Ave Labs

"""Telegram deep-link builders."""

from __future__ import annotations

from tcbot.modules.helper.parse_link import (
    appeal_deep_link,
    chat_id_to_link_id,
    message_link,
)


def test_supergroup_prefix_stripped() -> None:
    assert chat_id_to_link_id(-100123) == "123"


def test_plain_negative_id_stripped() -> None:
    assert chat_id_to_link_id(-5) == "5"


def test_message_link_shapes() -> None:
    assert message_link(-100123, 7) == "https://t.me/c/123/7"
    assert message_link(-100123, 7, 10) == "https://t.me/c/123/7?thread=10"


def test_appeal_deep_link_shape() -> None:
    assert (
        appeal_deep_link("bot", "x" * 10) == "https://t.me/bot?start=appeal_xxxxxxxxxx"
    )
