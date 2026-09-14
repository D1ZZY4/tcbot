# © Copyright 2024 - 2026 Transsion Core
# © Copyright 2024 - 2026 Dizzy
# © Copyright 2026 Ave Labs

"""Warn auto-ban fails closed when the target role lookup blows up."""

from __future__ import annotations

import asyncio
from typing import Any

import pytest

from tcbot import database as db
from tcbot.modules.helper.workflows import warning_flow


class _FakeMsg:
    """Message double recording replies."""

    def __init__(self) -> None:
        self.replies: list[str] = []

    async def reply_text(self, text: str, **kwargs: Any) -> object:
        self.replies.append(text)
        return object()


def _boom(*args: Any, **kwargs: Any) -> Any:
    raise AssertionError("must not run on role-lookup failure")


def test_autoban_aborts_on_role_lookup_failure(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    async def _role_lookup(user_id: int) -> object:
        raise RuntimeError("db blip")

    monkeypatch.setattr(db.users_roles, "get_effective_role", _role_lookup)
    monkeypatch.setattr(db.bans_db, "get_active_ban", _boom)
    monkeypatch.setattr(db.groups_db, "active_groups", _boom)

    msg = _FakeMsg()
    asyncio.run(
        warning_flow._execute_warn_auto_ban(
            None,  # type: ignore[arg-type]
            msg,  # type: ignore[arg-type]
            42,
            "Target",
            1,
            "Admin",
            "spam",
            3,
            3,
            0,
            "per_group",
            None,
            22,
            0,
            None,
            "log",
            "en-US",
        )
    )

    assert len(msg.replies) == 1
