# © Copyright 2024 - 2026 Transsion Core
# © Copyright 2024 - 2026 Dizzy
# © Copyright 2026 Ave Labs

"""Group connect enforcement replay: happy path, blind outage, truncation."""

from __future__ import annotations

import asyncio
from typing import Any

import pytest

from tcbot import database as db
from tcbot.modules.helper.pipelines.connected_flow import _REPLAY_CAP, BuildConnection


class _FakeBot:
    def __init__(self) -> None:
        self.banned: list[int] = []
        self.restricted: list[int] = []
        self.sent: list[tuple[int, str]] = []

    async def get_chat(self, chat_id: int) -> Any:
        return type("C", (), {"username": None})()

    async def get_chat_administrators(self, chat_id: int) -> list[Any]:
        return []

    async def ban_chat_member(self, chat_id: int, user_id: int) -> None:
        self.banned.append(user_id)

    async def restrict_chat_member(self, *args: Any, **kwargs: Any) -> None:
        self.restricted.append(int(args[1]))

    async def send_message(self, chat_id: int, text: str, **kwargs: Any) -> None:
        self.sent.append((chat_id, text))


def _install_world(
    monkeypatch: pytest.MonkeyPatch,
    *,
    ban_uids: list[int] | None = None,
    mute_docs: list[Any] | None = None,
) -> None:
    async def _ban_uids() -> list[int]:
        return list(ban_uids) if ban_uids is not None else []

    async def _mute_docs() -> list[Any]:
        return list(mute_docs) if mute_docs is not None else []

    async def _add_group(*args: Any, **kwargs: Any) -> None:
        return None

    async def _remove_pending(chat_id: int) -> None:
        return None

    monkeypatch.setattr(db.bans_db, "active_ban_user_ids", _ban_uids)
    monkeypatch.setattr(db.mutes_db, "active_mute_docs", _mute_docs)
    monkeypatch.setattr(db.groups_db, "add_group", _add_group)
    monkeypatch.setattr(db.groups_db, "remove_pending", _remove_pending)


def _join() -> BuildConnection:
    return BuildConnection(community_name="TCF")


def test_complete_join_happy_path_is_not_blind(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _install_world(monkeypatch, ban_uids=[11, 22])
    bot = _FakeBot()
    blind = asyncio.run(_join().complete_join(-100, "Group", 1, "Owner", bot))  # type: ignore[arg-type]
    assert blind is False
    assert sorted(bot.banned) == [11, 22]
    assert bot.sent != []


def test_complete_join_ban_outage_is_blind(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    async def _ban_boom() -> list[int]:
        raise RuntimeError("ban store down")

    _install_world(monkeypatch, ban_uids=[11])
    monkeypatch.setattr(db.bans_db, "active_ban_user_ids", _ban_boom)
    bot = _FakeBot()
    blind = asyncio.run(_join().complete_join(-100, "Group", 1, "Owner", bot))  # type: ignore[arg-type]
    assert blind is True
    assert bot.banned == []


def test_complete_join_truncates_replay_and_is_blind(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    uids = list(range(_REPLAY_CAP + 1))
    _install_world(monkeypatch, ban_uids=uids)
    bot = _FakeBot()
    blind = asyncio.run(_join().complete_join(-100, "Group", 1, "Owner", bot))  # type: ignore[arg-type]
    assert blind is True
    assert len(bot.banned) == _REPLAY_CAP
