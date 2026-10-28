# © Copyright 2024 - 2026 Transsion Core
# © Copyright 2024 - 2026 Dizzy
# © Copyright 2026 Ave Labs

"""error_reporter.attach: negative group/channel IDs warn nothing, zero warns."""

from __future__ import annotations

import logging
from typing import Any

from tcbot.utils import error_reporter


def _attach(chat_id: int, caplog: Any) -> None:
    error_reporter.attach(object(), chat_id, None, owner_id=1)  # type: ignore[arg-type]
    assert error_reporter._chat_id == chat_id


def test_negative_chat_id_is_valid(caplog: Any) -> None:
    with caplog.at_level(logging.WARNING, logger="tcbot.utils.error_reporter"):
        _attach(-1001234567890, caplog)

    assert "without a chat_id" not in caplog.text


def test_zero_chat_id_warns(caplog: Any) -> None:
    with caplog.at_level(logging.WARNING, logger="tcbot.utils.error_reporter"):
        _attach(0, caplog)

    assert "without a chat_id" in caplog.text
