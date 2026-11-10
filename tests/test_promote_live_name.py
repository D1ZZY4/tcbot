# © Copyright 2024 - 2026 Transsion Core
# © Copyright 2024 - 2026 Dizzy
# © Copyright 2026 Ave Labs

"""Promote picker falls back to live identity when the cache has no name."""

from __future__ import annotations

import asyncio
from typing import Any

import pytest

from tcbot.modules.admins import on_promote_role_btn
from tcbot.modules.helper.identity import Identity


class _FakeQuery:
    def __init__(self, data: str) -> None:
        self.data = data
        self.answers: list[tuple[str, bool]] = []
        self.edits: list[str] = []

    async def answer(
        self, text: str = "", *, show_alert: bool = False, **kwargs: Any
    ) -> None:
        self.answers.append((text, show_alert))

    async def edit_message_text(self, text: str, **kwargs: Any) -> None:
        self.edits.append(text)


def _update(query: _FakeQuery, user_id: int) -> Any:
    return type(
        "Upd",
        (),
        {
            "callback_query": query,
            "effective_user": type("U", (), {"id": user_id, "first_name": "Op"})(),
            "effective_chat": type("C", (), {"id": -1001})(),
        },
    )()


def test_picker_resolves_live_name_on_cache_miss(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    captured: dict[str, Any] = {}

    async def _locale(update: Any) -> str:
        return "en-US"

    async def _staff(admin_id: int, q: Any, update: Any) -> str:
        _ = (admin_id, q, update)
        return "founder"

    async def _not_bot(update: Any, target_id: int, bot: Any) -> bool:
        _ = (update, target_id, bot)
        return False

    async def _first_name(user_id: int, fallback: str = "") -> str:
        return fallback

    async def _role(user_id: int, *, fresh: bool = False) -> str | None:
        _ = (user_id, fresh)
        return None

    async def _live(bot: Any, target_id: int) -> tuple[str, str | None, str | None]:
        _ = (bot, target_id)
        return ("Real Name", "realname", None)

    async def _execute(
        bot: Any,
        admin_id: int,
        admin_fname: str,
        executor_role: str,
        target_id: int,
        target_fname: str,
        current_role: str | None,
        role: str,
        locale: str | None = None,
    ) -> tuple[bool, str]:
        captured["target_fname"] = target_fname
        captured["role"] = role
        return True, "Done."

    async def _owner() -> int | None:
        return 999_999_001

    async def _classify(
        bot: Any,
        executor_id: int,
        target_id: int,
        target_fname: str | None = None,
        **kwargs: Any,
    ) -> Any:
        _ = (bot, executor_id, target_id, target_fname, kwargs)
        return Identity("user", target_id, target_fname or str(target_id))

    monkeypatch.setattr("tcbot.modules.admins.locale_for_update", _locale)
    monkeypatch.setattr("tcbot.modules.admins.check_callback_staff", _staff)
    monkeypatch.setattr("tcbot.modules.admins.identity.is_proven_bot", _not_bot)
    monkeypatch.setattr("tcbot.modules.admins.identity.classify", _classify)
    monkeypatch.setattr("tcbot.database.users_cache.get_first_name", _first_name)
    monkeypatch.setattr("tcbot.database.users_roles.get_effective_role", _role)
    monkeypatch.setattr("tcbot.database.users_roles.get_owner_id", _owner)
    monkeypatch.setattr("tcbot.modules.helper.extraction.sync_user_identity", _live)
    monkeypatch.setattr("tcbot.modules.admins.Promote.execute", _execute)

    query = _FakeQuery("promo_role:developer:424242:515151")
    # * User 515151 is the opener (last segment); use a fresh ID so the
    # * per-handler rate bucket starts empty.
    ctx = type("Ctx", (), {"bot": object()})()
    asyncio.run(on_promote_role_btn(_update(query, 515151), ctx))  # type: ignore[arg-type]

    assert captured["target_fname"] == "Real Name"
    assert captured["role"] == "developer"
    assert query.edits
