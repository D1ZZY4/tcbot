# © Copyright 2024 - 2026 Transsion Core
# © Copyright 2024 - 2026 Dizzy
# © Copyright 2026 Ave Labs

"""Executor checks fail closed and origin guards enforce federation scope."""

from __future__ import annotations

import asyncio
from types import SimpleNamespace
from typing import Any

import pytest

from tcbot import database as db
from tcbot.modules.helper.decorators import (
    auth,
    checks,
    require_federation_origin,
    resolve_and_check,
)


def _msg(chat_type: str = "group", chat_id: int = -1001) -> Any:
    return SimpleNamespace(chat=SimpleNamespace(type=chat_type, id=chat_id))


class _ReplyLog:
    def __init__(self) -> None:
        self.texts: list[str] = []

    async def reply(self, msg: Any, text: str, **kwargs: Any) -> None:
        self.texts.append(text)


def _install(monkeypatch: pytest.MonkeyPatch, log: _ReplyLog) -> None:
    async def _locale(*args: Any) -> str:
        return "en-US"

    async def _safe_reply(msg: Any, text: str, **kwargs: Any) -> None:
        await log.reply(msg, text, **kwargs)

    monkeypatch.setattr(checks, "effective_locale", _locale)
    monkeypatch.setattr(checks, "safe_reply", _safe_reply)


def test_resolve_and_check_success(monkeypatch: pytest.MonkeyPatch) -> None:
    roles = {11: "developer", 22: None}
    log = _ReplyLog()
    _install(monkeypatch, log)

    async def _role(user_id: int, *, fresh: bool = False) -> str | None:
        return roles.get(user_id)

    monkeypatch.setattr(db.users_roles, "get_effective_role", _role)
    executor, target = asyncio.run(
        resolve_and_check(_msg(), 11, 22, min_role="developer")
    )
    assert (executor, target) == ("developer", None)
    assert log.texts == []


def test_resolve_and_check_fails_closed_on_lookup_failure(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    log = _ReplyLog()
    _install(monkeypatch, log)

    async def _boom(user_id: int, *, fresh: bool = False) -> str | None:
        raise RuntimeError("db down")

    monkeypatch.setattr(db.users_roles, "get_effective_role", _boom)
    executor, target = asyncio.run(resolve_and_check(_msg(), 11, 22, min_role="tester"))
    assert (executor, target) == (None, None)
    # * One fail-closed retry notice, not a silent pass.
    assert len(log.texts) == 1


def test_resolve_and_check_propagates_cancellation(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    log = _ReplyLog()
    _install(monkeypatch, log)

    async def _cancelled(user_id: int, *, fresh: bool = False) -> str | None:
        raise asyncio.CancelledError

    monkeypatch.setattr(db.users_roles, "get_effective_role", _cancelled)
    with pytest.raises(asyncio.CancelledError):
        asyncio.run(resolve_and_check(_msg(), 11, 22, min_role="tester"))


def test_resolve_and_check_rejects_outrank_and_low_rank(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    log = _ReplyLog()
    _install(monkeypatch, log)

    async def _role(user_id: int, *, fresh: bool = False) -> str | None:
        return "tester" if user_id == 11 else "admin"

    monkeypatch.setattr(db.users_roles, "get_effective_role", _role)
    # * Tester (rank 1) outranked by admin target (rank 3): refuse.
    executor, target = asyncio.run(resolve_and_check(_msg(), 11, 22, min_role="tester"))
    assert (executor, target) == (None, None)
    assert len(log.texts) == 1


def test_require_origin_allows_private_only_when_permitted(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    log = _ReplyLog()
    _install(monkeypatch, log)
    msg = _msg(chat_type="private", chat_id=42)
    assert (
        asyncio.run(
            require_federation_origin(
                msg, chat_id=42, chat_type="private", locale="en-US", allow_private=True
            )
        )
        is True
    )
    assert (
        asyncio.run(
            require_federation_origin(
                msg,
                chat_id=42,
                chat_type="private",
                locale="en-US",
                allow_private=False,
            )
        )
        is False
    )
    assert len(log.texts) == 1


def test_require_origin_blocks_disconnected_and_fails_closed(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    log = _ReplyLog()
    _install(monkeypatch, log)
    msg = _msg(chat_type="group", chat_id=-1002)

    async def _not_connected(chat_id: int, *, fresh: bool = False) -> bool:
        return False

    monkeypatch.setattr(db.groups_db, "is_connected", _not_connected)
    assert (
        asyncio.run(
            require_federation_origin(
                msg,
                chat_id=-1002,
                chat_type="group",
                locale="en-US",
                allow_private=True,
            )
        )
        is False
    )

    async def _boom(chat_id: int, *, fresh: bool = False) -> bool:
        raise RuntimeError("db down")

    monkeypatch.setattr(db.groups_db, "is_connected", _boom)
    assert (
        asyncio.run(
            require_federation_origin(
                msg,
                chat_id=-1002,
                chat_type="group",
                locale="en-US",
                allow_private=True,
            )
        )
        is False
    )
    assert len(log.texts) == 2


def test_recheck_executor_rank_allows_meeting_rank(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    log = _ReplyLog()
    _install(monkeypatch, log)

    async def _role(user_id: int, *, fresh: bool = False) -> str | None:
        return "developer"

    monkeypatch.setattr(db.users_roles, "get_effective_role", _role)
    assert (
        asyncio.run(checks.recheck_executor_rank(_msg(), 11, min_role="developer"))
        is True
    )
    assert log.texts == []


def test_recheck_executor_rank_refuses_demotion(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    log = _ReplyLog()
    _install(monkeypatch, log)

    async def _role(user_id: int, *, fresh: bool = False) -> str | None:
        return None

    monkeypatch.setattr(db.users_roles, "get_effective_role", _role)
    assert (
        asyncio.run(checks.recheck_executor_rank(_msg(), 11, min_role="tester"))
        is False
    )
    assert len(log.texts) == 1


def test_recheck_executor_rank_fails_closed_on_outage(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    log = _ReplyLog()
    _install(monkeypatch, log)

    async def _boom(user_id: int, *, fresh: bool = False) -> str | None:
        raise RuntimeError("db down")

    monkeypatch.setattr(db.users_roles, "get_effective_role", _boom)
    assert (
        asyncio.run(checks.recheck_executor_rank(_msg(), 11, min_role="tester"))
        is False
    )
    assert len(log.texts) == 1


def test_recheck_executor_rank_propagates_cancellation(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    log = _ReplyLog()
    _install(monkeypatch, log)

    async def _cancelled(user_id: int, *, fresh: bool = False) -> str | None:
        raise asyncio.CancelledError

    monkeypatch.setattr(db.users_roles, "get_effective_role", _cancelled)
    with pytest.raises(asyncio.CancelledError):
        asyncio.run(checks.recheck_executor_rank(_msg(), 11, min_role="tester"))


def _update_ctx() -> tuple[Any, Any]:
    msg = SimpleNamespace(
        chat=SimpleNamespace(type="group", id=-1001),
        text="/tcban 22 spam",
    )
    admin = SimpleNamespace(id=11, first_name="Admin")
    update = SimpleNamespace(effective_message=msg, effective_user=admin)
    ctx = SimpleNamespace(user_data={}, bot=SimpleNamespace(id=99))
    return update, ctx


def test_resolve_mod_target_returns_resolved_target(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    log = _ReplyLog()
    _install(monkeypatch, log)
    update, ctx = _update_ctx()

    async def _locale(upd: Any) -> str:
        return "en-US"

    async def _origin(msg: Any, **kwargs: Any) -> bool:
        return True

    async def _extract(upd: Any, args: Any, bot: Any) -> tuple[Any, Any]:
        return (22, "Target"), True

    async def _classify(
        bot: Any,
        admin_id: int,
        target_id: int,
        target_name: Any,
        msg: Any,
        **kwargs: Any,
    ) -> tuple[Any, Any]:
        return SimpleNamespace(kind="user"), None

    monkeypatch.setattr(checks, "locale_for_update", _locale)
    monkeypatch.setattr(checks, "require_federation_origin", _origin)
    monkeypatch.setattr(checks.extraction, "extract_mod_target", _extract)
    monkeypatch.setattr(checks, "classify_and_check", _classify)
    monkeypatch.setattr(checks.identity, "refuse_message", lambda *a: None)

    resolved = asyncio.run(
        checks.resolve_mod_target(
            update,
            ctx,
            action="ban",
            min_role="developer",
            allow_private=True,
            log_prefix="cmd_ban_start",
        )
    )
    assert resolved is not None
    assert resolved.target_id == 22
    assert resolved.target_name == "Target"
    assert resolved.has_explicit_target is True
    assert resolved.args == ["22", "spam"]
    assert resolved.locale == "en-US"
    assert log.texts == []


def test_resolve_mod_target_replies_no_target(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    log = _ReplyLog()
    _install(monkeypatch, log)
    update, ctx = _update_ctx()

    async def _locale(upd: Any) -> str:
        return "en-US"

    async def _origin(msg: Any, **kwargs: Any) -> bool:
        return True

    async def _extract(upd: Any, args: Any, bot: Any) -> tuple[Any, Any]:
        return (0, ""), False

    monkeypatch.setattr(checks, "locale_for_update", _locale)
    monkeypatch.setattr(checks, "require_federation_origin", _origin)
    monkeypatch.setattr(checks.extraction, "extract_mod_target", _extract)

    resolved = asyncio.run(
        checks.resolve_mod_target(
            update,
            ctx,
            action="kick",
            min_role="tester",
            allow_private=False,
            log_prefix="cmd_kick",
        )
    )
    assert resolved is None
    assert len(log.texts) == 1


def test_resolve_staff_target_returns_resolved_target(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """The single-action commands share one entry sequence."""
    log = _ReplyLog()
    _install(monkeypatch, log)
    update, ctx = _update_ctx()

    async def _locale(upd: Any) -> str:
        return "en-US"

    async def _origin(msg: Any, **kwargs: Any) -> bool:
        return True

    async def _extract(upd: Any, args: Any, bot: Any) -> tuple[Any, Any]:
        return (22, "Target")

    async def _classify(
        bot: Any,
        admin_id: int,
        target_id: int,
        target_name: Any,
        msg: Any,
        **kwargs: Any,
    ) -> tuple[Any, Any]:
        return SimpleNamespace(kind="user"), None

    async def _not_bot(upd: Any, target_id: int, bot: Any) -> bool:
        return False

    monkeypatch.setattr(checks, "locale_for_update", _locale)
    monkeypatch.setattr(checks, "require_federation_origin", _origin)
    monkeypatch.setattr(checks.extraction, "extract_target", _extract)
    monkeypatch.setattr(checks, "classify_and_check", _classify)
    monkeypatch.setattr(checks.identity, "is_proven_bot", _not_bot)
    monkeypatch.setattr(checks.identity, "refuse_message", lambda *a: None)

    resolved = asyncio.run(
        checks.resolve_staff_target(
            update,
            ctx,
            action="unwarn",
            min_role="tester",
            log_prefix="cmd_unwarn",
        )
    )
    assert resolved is not None
    assert resolved.target_id == 22
    assert resolved.target_name == "Target"
    assert resolved.locale == "en-US"
    assert log.texts == []


def test_resolve_staff_target_refuses_a_protected_identity(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """A protected target is refused and the command does not run."""
    log = _ReplyLog()
    _install(monkeypatch, log)
    update, ctx = _update_ctx()

    async def _locale(upd: Any) -> str:
        return "en-US"

    async def _origin(msg: Any, **kwargs: Any) -> bool:
        return True

    async def _extract(upd: Any, args: Any, bot: Any) -> tuple[Any, Any]:
        return (22, "Target")

    async def _classify(
        bot: Any,
        admin_id: int,
        target_id: int,
        target_name: Any,
        msg: Any,
        **kwargs: Any,
    ) -> tuple[Any, Any]:
        return SimpleNamespace(kind="founder"), None

    async def _not_bot(upd: Any, target_id: int, bot: Any) -> bool:
        return False

    monkeypatch.setattr(checks, "locale_for_update", _locale)
    monkeypatch.setattr(checks, "require_federation_origin", _origin)
    monkeypatch.setattr(checks.extraction, "extract_target", _extract)
    monkeypatch.setattr(checks, "classify_and_check", _classify)
    monkeypatch.setattr(checks.identity, "is_proven_bot", _not_bot)
    monkeypatch.setattr(
        checks.identity, "refuse_message", lambda *a: "refused, founder"
    )

    resolved = asyncio.run(
        checks.resolve_staff_target(
            update,
            ctx,
            action="unmute",
            min_role="tester",
            log_prefix="cmd_unmute",
        )
    )
    assert resolved is None
    assert len(log.texts) == 1
    assert "refused" in log.texts[0]


def test_resolve_staff_target_refuses_a_disconnected_origin(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """The origin guard runs before the target is resolved."""
    log = _ReplyLog()
    _install(monkeypatch, log)
    update, ctx = _update_ctx()

    async def _locale(upd: Any) -> str:
        return "en-US"

    async def _origin(msg: Any, **kwargs: Any) -> bool:
        return False

    resolved = asyncio.run(
        checks.resolve_staff_target(
            update,
            ctx,
            action="resetwarns",
            min_role="tester",
            log_prefix="cmd_resetwarns",
        )
    )
    assert resolved is None


def test_the_owner_tier_refreshes_the_effective_role_cache(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """The Founder tier must leave the effective-role cache in step.

    The rank comparison that follows a tier check reads the executor's
    role from the cache. The owner tier resolved its role straight from
    the database, so without refreshing the cache the comparison would
    use the role the previous Founder still had, and an ownership
    transfer would refuse its own target.
    """
    cached: dict[int, str | None] = {}

    async def _owner_id(*, fresh: bool = False) -> int:
        return 1

    def _cache_role(user_id: int, role: str | None) -> None:
        cached[user_id] = role

    async def _handler(update: Any, ctx: Any) -> None:
        return None

    monkeypatch.setattr(db.users_roles, "get_owner_id", _owner_id)
    monkeypatch.setattr(db.users_roles, "cache_effective_role", _cache_role)

    update = SimpleNamespace(
        effective_user=SimpleNamespace(id=1, first_name="Founder", is_bot=False),
        effective_message=None,
    )

    guarded = auth.owner_only(_handler)
    asyncio.run(guarded(update, SimpleNamespace()))

    assert cached == {1: "founder"}
