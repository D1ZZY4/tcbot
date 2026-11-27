# © Copyright 2024 - 2026 Transsion Core
# © Copyright 2024 - 2026 Dizzy
# © Copyright 2026 Ave Labs

"""Regression coverage for fail-closed guards and revocation gates."""

from __future__ import annotations

import asyncio
from types import SimpleNamespace
from typing import Any

import pytest
from pyrogram.types import ChatAdministratorRights, ChatMember

from tcbot import database as db
from tcbot.database import users_cache
from tcbot.database.cache import user_mention_cache
from tcbot.modules.helper import guards
from tcbot.modules.helper.pipelines import mute_executor, warn_executor
from tcbot.modules.helper.pipelines.connect_added import connection
from tcbot.modules.helper.pipelines.errors import report as error_reporter


async def _locale(*args: Any, **kwargs: Any) -> str:
    return "en-US"


def _ctx() -> SimpleNamespace:
    """Return the minimal context a single-tap revocation executor reads."""
    return SimpleNamespace(
        bot=SimpleNamespace(),
        effective_message=SimpleNamespace(
            text="/tcrevoke", chat=SimpleNamespace(id=-100, type="group")
        ),
        effective_chat=SimpleNamespace(id=-100, title="Group", type="group"),
        effective_user=SimpleNamespace(id=1, first_name="Mod"),
    )


def test_forwarded_role_lookup_failure_yields_a_refusal(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """A target-role outage on the shared gate must not raise into the dispatcher."""
    replies: list[str] = []

    async def _fail(*args: Any, **kwargs: Any) -> str:
        raise RuntimeError("roles down")

    async def _reply(_msg: Any, text: str, **_kwargs: Any) -> None:
        replies.append(text)

    monkeypatch.setattr(db.users_roles, "get_effective_role", _fail)
    monkeypatch.setattr(guards, "reply_rich", _reply)
    monkeypatch.setattr(guards, "effective_locale", _locale)

    result = asyncio.run(
        guards.resolve_and_check(
            _ctx().effective_message,
            1,
            2,
            min_role="moderator",
            executor_role="moderator",
        )
    )
    assert result == (None, None)
    assert len(replies) == 1


def test_refresh_display_name_respects_concurrent_invalidation(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """An erasure landing during the write must not be undone by a re-warm."""
    put_calls: list[tuple[int, object]] = []

    async def _peek(_self: object, uid: int) -> list[str | None]:
        return ["Old", "olduser", None]

    async def _upsert(uid: int, username: object, first_name: str) -> bool:
        user_mention_cache.invalidate(uid)  # the partial write's own invalidation
        user_mention_cache.invalidate(uid)  # the erasure sweep's invalidation
        return True

    def _put(_self: object, key: int, value: object) -> None:
        put_calls.append((key, value))

    monkeypatch.setattr(type(user_mention_cache), "peek", _peek)
    monkeypatch.setattr(type(user_mention_cache), "put", _put)
    monkeypatch.setattr(users_cache, "upsert_user", _upsert)

    asyncio.run(users_cache.refresh_display_name(7, "Fresh"))
    assert put_calls == []


def test_display_name_refresh_does_not_rewarm_stale_identity(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """A partial name write must cache the stored identity, not a stale peek."""
    put_calls: list[tuple[int, list[str | None]]] = []

    async def _peek(_self: object, _uid: int) -> list[str | None]:
        return ["Old", "olduser", "OldLast"]

    async def _upsert(uid: int, username: object, first_name: str) -> bool:
        user_mention_cache.invalidate(uid)
        return True

    async def _stored(uid: int) -> list[str | None]:
        return ["Fresh", "currentuser", "CurrentLast"]

    def _put(_self: object, key: int, value: list[str | None]) -> None:
        put_calls.append((key, value))

    monkeypatch.setattr(type(user_mention_cache), "peek", _peek)
    monkeypatch.setattr(type(user_mention_cache), "put", _put)
    monkeypatch.setattr(users_cache, "upsert_user", _upsert)
    monkeypatch.setattr(users_cache, "_fetch_mention_triple", _stored)

    assert asyncio.run(users_cache.refresh_display_name(7, "Fresh")) is True
    assert put_calls == [(7, ["Fresh", "currentuser", "CurrentLast"])]


def test_unmute_refusal_skips_the_revoke(monkeypatch: pytest.MonkeyPatch) -> None:
    """A refused execution-time gate must not revoke the stored mute."""
    called: list[str] = []

    async def _refuse(*args: Any, **kwargs: Any) -> str:
        return "REFUSED"

    async def _reply(*args: Any, **kwargs: Any) -> None:
        called.append("reply")

    async def _active(*args: Any, **kwargs: Any) -> dict[str, Any]:
        called.append("lookup")
        return {"user_id": 33}

    monkeypatch.setattr(mute_executor.guards, "enforcement_refusal", _refuse)
    monkeypatch.setattr(mute_executor, "reply_rich", _reply)
    monkeypatch.setattr(mute_executor, "locale_for_update", _locale)
    monkeypatch.setattr(db.mutes_db, "get_active_mute", _active)

    asyncio.run(mute_executor.execute_unmute(_ctx(), 33, "Target"))
    assert called == ["reply"]


def test_unwarn_refusal_skips_the_count(monkeypatch: pytest.MonkeyPatch) -> None:
    """A refused execution-time gate must not touch the warning store."""
    called: list[str] = []

    async def _refuse(*args: Any, **kwargs: Any) -> str:
        return "REFUSED"

    async def _reply(*args: Any, **kwargs: Any) -> None:
        called.append("reply")

    async def _count(*args: Any, **kwargs: Any) -> int:
        called.append("count")
        return 1

    monkeypatch.setattr(warn_executor.guards, "enforcement_refusal", _refuse)
    monkeypatch.setattr(warn_executor, "reply_rich", _reply)
    monkeypatch.setattr(warn_executor, "locale_for_update", _locale)
    monkeypatch.setattr(db.warns_db, "warn_count", _count)

    asyncio.run(warn_executor.execute_unwarn(_ctx(), 42, "Target"))
    assert called == ["reply"]


def test_connect_permission_gate_reads_admin_privileges() -> None:
    """Kurigram stores admin rights on ChatMember.privileges, not on the member."""
    rights = ChatAdministratorRights(
        can_delete_messages=True,
        can_restrict_members=True,
        can_invite_users=True,
    )
    assert connection.check_perms(ChatMember(status="administrator", privileges=rights))
    assert not connection.check_perms(
        ChatMember(status="administrator", privileges=None)
    )


def test_error_report_keeps_an_unraised_exception_message() -> None:
    """A failure built from stored delivery details still names the real error."""
    payload = error_reporter.build_error_report_payload(
        exc=RuntimeError("CHAT_ADMIN_REQUIRED")
    )
    assert "CHAT_ADMIN_REQUIRED" in payload["html"]
    assert "[?] Unknown" not in payload["html"]
