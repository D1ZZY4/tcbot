# © Copyright 2024 - 2026 Transsion Core
# © Copyright 2024 - 2026 Dizzy
# © Copyright 2026 Ave Labs

"""Identity refusal copy, staff notices, and recognition notes."""

from __future__ import annotations

import asyncio
import logging
from types import SimpleNamespace
from typing import Any

import pytest
from sqlalchemy.exc import OperationalError

from tcbot import database as db
from tcbot.modules.helper.identity import (
    Identity,
    classify,
    profile_note,
    refuse_message,
    staff_notice,
    verify_not_bot,
)


def _database_outage() -> OperationalError:
    """Return the error a refused PostgreSQL connection produces."""
    return OperationalError("SELECT 1", {}, Exception("connection refused"))


def _ident(kind: str) -> Identity:
    """Build a fixed identity for copy assertions."""
    return Identity(kind, 123, "Dizzy", "dizzy")  # type: ignore[arg-type]


def test_ban_refuses_self_bot_telegram_anon_founder() -> None:
    for kind in ("self", "this_bot", "telegram", "anon_admin", "founder"):
        assert isinstance(refuse_message("ban", _ident(kind)), str)


def test_ban_allows_user_and_staff() -> None:
    for kind in ("user", "admin", "developer", "tester", "other_bot"):
        assert refuse_message("ban", _ident(kind)) is None


def test_unknown_action_allows_everything() -> None:
    assert refuse_message("nope", _ident("self")) is None
    assert refuse_message("nope", _ident("user")) is None


def test_promote_refuses_admin() -> None:
    assert isinstance(refuse_message("promote", _ident("admin")), str)


def test_staff_notice_only_for_staff() -> None:
    for kind in ("admin", "developer", "tester"):
        notice = staff_notice("warn", _ident(kind), "TCF")
        assert notice is not None and "warn" in notice
    for kind in ("user", "founder", "self", "other_bot"):
        assert staff_notice("warn", _ident(kind), "TCF") is None


def test_profile_note_only_for_special_identities() -> None:
    for kind in ("this_bot", "self", "telegram", "anon_admin"):
        assert isinstance(profile_note(_ident(kind)), str)
    for kind in ("user", "admin", "developer", "tester", "founder", "other_bot"):
        assert profile_note(_ident(kind)) is None


def test_role_label_maps_staff_only() -> None:
    assert _ident("admin").role_label == "Admin"
    assert _ident("founder").role_label == "Founder"
    assert _ident("user").role_label is None
    assert _ident("self").role_label is None


class _ProbeFailBot:
    """Fake Bot whose membership probe always faults."""

    async def get_chat_member(self, chat_id: int, user_id: int) -> object:
        raise RuntimeError("probe offline")


def _group_update() -> Any:
    """Update stand-in for a group chat without a reply context."""
    return SimpleNamespace(
        effective_message=None,
        effective_chat=SimpleNamespace(id=-100123, type="supergroup"),
    )


def test_verify_not_bot_falls_through_after_probe_failure(
    monkeypatch: Any, caplog: Any
) -> None:
    """A faulting membership probe defers to MTProto and logs the miss."""
    seen: list[int] = []

    async def _fake_is_bot_user(user_id: int) -> bool:
        seen.append(user_id)
        return False

    monkeypatch.setattr(db.mtproto, "is_bot_user", _fake_is_bot_user)
    with caplog.at_level(logging.DEBUG, logger="tcbot.modules.helper.identity"):
        result = asyncio.run(verify_not_bot(_group_update(), 42, _ProbeFailBot()))  # type: ignore[arg-type]
    assert result is True
    assert seen == [42]
    assert "bot verification member probe failed for 42 in -100123" in caplog.text


def test_verify_not_bot_is_indeterminate_when_both_lookups_miss(
    monkeypatch: Any,
) -> None:
    """Probe failure plus an unknown MTProto verdict stays indeterminate."""

    async def _fake_is_bot_user(user_id: int) -> None:
        return None

    monkeypatch.setattr(db.mtproto, "is_bot_user", _fake_is_bot_user)
    result = asyncio.run(verify_not_bot(_group_update(), 42, _ProbeFailBot()))  # type: ignore[arg-type]
    assert result is None


def test_classify_raises_when_the_role_cannot_be_resolved(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """An unresolved role must not degrade into "no role".

    The refusal table is keyed on the identity kind, so a target that
    resolved to ``"user"`` because of a database outage would silently
    lose the protection that keeps a Founder from being moderated.
    """

    async def _boom(_user_id: int) -> str:
        raise _database_outage()

    async def _name(_user_id: int) -> tuple[str, str | None]:
        return ("Founder", None)

    monkeypatch.setattr(db.users_roles, "get_effective_role", _boom)
    monkeypatch.setattr(db.users_cache, "get_user_mention_data", _name)

    bot = SimpleNamespace(id=999)
    with pytest.raises(OperationalError):
        asyncio.run(classify(bot, 1, 2))  # type: ignore[arg-type]


def test_classify_still_resolves_when_only_the_name_lookup_fails(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """The display name is not an authorization input, so it may degrade."""

    async def _role(_user_id: int) -> str:
        return "founder"

    async def _boom(_user_id: int) -> tuple[str, str | None]:
        raise _database_outage()

    monkeypatch.setattr(db.users_roles, "get_effective_role", _role)
    monkeypatch.setattr(db.users_cache, "get_user_mention_data", _boom)

    bot = SimpleNamespace(id=999)
    ident = asyncio.run(classify(bot, 1, 2))  # type: ignore[arg-type]
    assert ident.kind == "founder"
