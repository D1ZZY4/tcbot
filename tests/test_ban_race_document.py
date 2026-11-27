# © Copyright 2024 - 2026 Transsion Core
# © Copyright 2024 - 2026 Dizzy
# © Copyright 2026 Ave Labs

"""A lost one-active-ban race returns the winning document, not a KeyError."""

from __future__ import annotations

from types import SimpleNamespace
from typing import Any

import pytest
from sqlalchemy.exc import IntegrityError

from tcbot.database.bans_db import _writes


@pytest.mark.asyncio
async def test_a_lost_active_ban_race_returns_the_existing_ban(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """The race loser must reuse the composed BanDoc from the winner."""
    error = IntegrityError("INSERT", {}, Exception("duplicate"))
    error.orig = SimpleNamespace(  # type: ignore[assignment]
        diag=SimpleNamespace(constraint_name="uq_moderation_actions_active_ban")
    )

    async def _raise(_op: Any) -> Any:
        raise error

    async def _active(_target_id: int) -> dict[str, Any]:
        return {"id": 7, "ban_id": "b1", "target_user_id": 42}

    monkeypatch.setattr(_writes, "run_transaction", _raise)
    monkeypatch.setattr(_writes, "get_active_ban", _active)

    document = await _writes.create_ban(42, "spam", 1, 0, 0, ban_id="b2")

    assert document["ban_id"] == "b1"
