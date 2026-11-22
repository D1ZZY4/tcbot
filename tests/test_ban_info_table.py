# © Copyright 2024 - 2026 Transsion Core
# © Copyright 2024 - 2026 Dizzy
# © Copyright 2026 Ave Labs

"""Ban detail cards use real rich structure instead of bullet runs."""

from __future__ import annotations

import asyncio
from datetime import UTC, datetime
from typing import Any, cast

from tcbot import database as db
from tcbot.database.documents import BanDoc
from tcbot.modules.helper.ban_info import build_ban_detail


def test_ban_detail_renders_a_headed_table(monkeypatch: Any) -> None:
    async def _mention(_uid: int) -> tuple[str, None]:
        return "Admin", None

    monkeypatch.setattr(db.users_cache, "get_user_mention_data", _mention)

    ban = {
        "target_user_id": 42,
        "actor_user_id": 7,
        "reason": "spam",
        "ban_id": "abc123",
        "timestamp": datetime(2026, 11, 22, tzinfo=UTC),
    }
    text, _link = asyncio.run(build_ban_detail(cast("BanDoc", ban), "Target", "en-US"))

    assert text.startswith("<h3>Ban Information</h3>")
    assert "<hr/>" in text
    assert "<table" in text and "<th>Field</th><th>Value</th>" in text
    assert "<th>User</th>" not in text  # labels are cells, not headers
    assert "<td>Reason</td>" in text and "<td>Ban ID</td>" in text
    assert "<code>abc123</code>" in text
    assert "<li>" not in text
