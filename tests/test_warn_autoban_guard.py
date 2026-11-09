# © Copyright 2024 - 2026 Transsion Core
# © Copyright 2024 - 2026 Dizzy
# © Copyright 2026 Ave Labs

"""Warn threshold ban fails closed when the target role lookup blows up."""

from __future__ import annotations

import asyncio
from types import SimpleNamespace
from typing import Any

import pytest

from tcbot import database as db
from tcbot.modules.helper.pipelines import warn_flow


class _FakeMsg:
    """Message double recording replies."""

    def __init__(self) -> None:
        self.replies: list[str] = []

    async def reply_text(self, text: str, **kwargs: Any) -> object:
        self.replies.append(text)
        return object()


def _boom(*args: Any, **kwargs: Any) -> Any:
    raise AssertionError("must not run on role-lookup failure")


def test_threshold_ban_aborts_on_role_lookup_failure(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    async def _locale(_update: Any) -> str:
        return "en-US"

    async def _role_lookup(user_id: int, *, fresh: bool = False) -> object:
        raise RuntimeError("db blip")

    msg = _FakeMsg()
    update = SimpleNamespace(
        effective_message=msg,
        effective_chat=SimpleNamespace(id=22, title="Group", type="supergroup"),
        effective_user=SimpleNamespace(id=1, first_name="Admin"),
    )
    ctx = SimpleNamespace(bot=SimpleNamespace(), user_data={})

    async def _add_warn(*args: Any, **kwargs: Any) -> int:
        return 3

    monkeypatch.setattr(warn_flow, "locale_for_update", _locale)
    monkeypatch.setattr(db.warns_db, "add_warn", _add_warn)
    monkeypatch.setattr(db.users_roles, "get_effective_role", _role_lookup)
    monkeypatch.setattr(db.bans_db, "get_active_ban", _boom)
    monkeypatch.setattr(db.groups_db, "active_groups", _boom)

    asyncio.run(
        warn_flow.execute_warn(
            update,  # type: ignore[arg-type]
            ctx,  # type: ignore[arg-type]
            42,
            "Target",
            "spam",
        )
    )

    assert len(msg.replies) == 1


class _FakeBot:
    """Bot double fanning one successful ban plus log and DM posts."""

    def __init__(self) -> None:
        self.sent: list[tuple[Any, ...]] = []

    async def send_message(self, *args: Any, **kwargs: Any) -> Any:
        self.sent.append((args, kwargs))

        class _Sent:
            message_id = 99

        return _Sent()

    async def ban_chat_member(self, *args: Any, **kwargs: Any) -> bool:
        return True


def test_threshold_ban_stores_warn_proof_on_ban_record(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    created: list[dict[str, Any]] = []
    cleared: list[int] = []

    async def _locale(_update: Any) -> str:
        return "en-US"

    async def _add_warn(*args: Any, **kwargs: Any) -> int:
        return 3

    async def _upload(*args: Any, **kwargs: Any) -> int:
        return 77

    async def _role_lookup(user_id: int, *, fresh: bool = False) -> None:
        return None

    async def _groups() -> list[dict[str, Any]]:
        return [{"chat_id": 5, "title": "Group"}]

    async def _no_ban(user_id: int) -> None:
        return None

    async def _create_ban(
        target_id: int,
        reason: str,
        admin_id: int,
        proof_msg_id: int,
        log_msg_id: int,
    ) -> dict[str, Any]:
        created.append({"proof_msg_id": proof_msg_id})
        return {"ban_id": "b1"}

    async def _set_log(ban_id: str, log_msg_id: int) -> None:
        return None

    async def _clear_all(user_id: int) -> int:
        cleared.append(user_id)
        return 1

    monkeypatch.setattr(warn_flow, "locale_for_update", _locale)
    monkeypatch.setattr(warn_flow, "upload_proof", _upload)
    monkeypatch.setattr(db.warns_db, "add_warn", _add_warn)
    monkeypatch.setattr(db.users_roles, "get_effective_role", _role_lookup)
    monkeypatch.setattr(db.groups_db, "active_groups", _groups)
    monkeypatch.setattr(db.bans_db, "get_active_ban", _no_ban)
    monkeypatch.setattr(db.bans_db, "create_ban", _create_ban)
    monkeypatch.setattr(db.bans_db, "set_log_message_id", _set_log)
    monkeypatch.setattr(db.warns_db, "clear_all_warns", _clear_all)

    msg = _FakeMsg()
    update = SimpleNamespace(
        effective_message=msg,
        effective_chat=SimpleNamespace(id=22, title="Group", type="supergroup"),
        effective_user=SimpleNamespace(id=1, first_name="Admin"),
    )
    ctx = SimpleNamespace(bot=_FakeBot(), user_data={})
    asyncio.run(
        warn_flow.execute_warn(
            update,  # type: ignore[arg-type]
            ctx,  # type: ignore[arg-type]
            42,
            "Target",
            "spam",
            proof_msgs=[object()],  # type: ignore[arg-type]
        )
    )

    assert created == [{"proof_msg_id": 77}]
    assert cleared == [42]
    assert len(msg.replies) == 1
