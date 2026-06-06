# © Copyright 2024 - 2026 Transsion Core
# © Copyright 2024 - 2026 Dizzy
# © Copyright 2026 Ave Studio

"""Tests for tcbot.modules.helper.decorators - tracer and authorization guards."""

from __future__ import annotations

import logging
from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest
from telegram.ext import ApplicationHandlerStop

import tcbot.modules.helper.decorators as _dec_mod
from tcbot.database import users_roles
from tcbot.modules.helper.decorators import (
    _ERR_BASIC_MOD_ONLY,
    _ERR_MOD_ONLY,
    _ERR_OWNER_ONLY,
    _ERR_RANK_INSUFFICIENT,
    _ERR_STAFF_ONLY,
    basic_mod_only,
    global_rate_limit_handler,
    log_execution,
    mod_only,
    owner_only,
    resolve_and_check,
    staff_only,
)

# ───────────────────────────── Helpers ──────────────────────────── #


def _update(uid: int | None = 1) -> SimpleNamespace:
    user = SimpleNamespace(id=uid) if uid is not None else None
    return SimpleNamespace(effective_user=user)


def _ctx() -> SimpleNamespace:
    return SimpleNamespace()


# ──────────────────────── Basic invocation ──────────────────────── #


async def test_log_execution_calls_wrapped_function() -> None:
    called: list[int] = []

    @log_execution
    async def handler(update, ctx) -> None:
        called.append(1)

    await handler(_update(), _ctx())
    assert called == [1]


async def test_log_execution_returns_handler_result() -> None:
    @log_execution
    async def handler(update, ctx):
        return "ok"

    result = await handler(_update(), _ctx())
    assert result == "ok"


# ────────────────────── Metadata preservation ───────────────────── #


async def test_log_execution_preserves_function_name() -> None:
    @log_execution
    async def my_handler(update, ctx) -> None:
        pass

    assert my_handler.__name__ == "my_handler"


async def test_log_execution_preserves_docstring() -> None:
    @log_execution
    async def documented(update, ctx) -> None:
        """Handler docstring."""

    assert documented.__doc__ == "Handler docstring."


# ─────────────────────── Exception handling ─────────────────────── #


async def test_log_execution_reraises_exception() -> None:
    @log_execution
    async def bad_handler(update, ctx) -> None:
        raise ValueError("boom")

    with pytest.raises(ValueError, match="boom"):
        await bad_handler(_update(), _ctx())


async def test_log_execution_logs_exception_at_error_level(caplog) -> None:
    @log_execution
    async def failing(update, ctx) -> None:
        raise RuntimeError("kaboom")

    with caplog.at_level(logging.ERROR, logger="tcbot.modules.helper.decorators"):
        with pytest.raises(RuntimeError):
            await failing(_update(uid=7), _ctx())

    assert any("failing" in rec.message for rec in caplog.records)
    assert any(rec.levelno == logging.ERROR for rec in caplog.records)


# ───────────────────────── Logging traces ───────────────────────── #


async def test_log_execution_logs_entry_at_debug(caplog) -> None:
    @log_execution
    async def traced(update, ctx) -> None:
        pass

    with caplog.at_level(logging.DEBUG, logger="tcbot.modules.helper.decorators"):
        await traced(_update(uid=42), _ctx())

    messages = [rec.message for rec in caplog.records]
    assert any("traced" in m and "42" in m for m in messages)


async def test_log_execution_logs_ok_at_debug(caplog) -> None:
    @log_execution
    async def success(update, ctx) -> None:
        pass

    with caplog.at_level(logging.DEBUG, logger="tcbot.modules.helper.decorators"):
        await success(_update(), _ctx())

    assert any("ok" in rec.message for rec in caplog.records)


# ─────────────────────────── Edge cases ─────────────────────────── #


async def test_log_execution_works_when_effective_user_is_none() -> None:
    """Decorator must not crash when there is no user on the update."""
    called: list[int] = []

    @log_execution
    async def handler(update, ctx) -> None:
        called.append(1)

    await handler(_update(uid=None), _ctx())
    assert called == [1]


async def test_log_execution_uid_question_mark_logged_for_missing_user(caplog) -> None:
    @log_execution
    async def anon(update, ctx) -> None:
        pass

    with caplog.at_level(logging.DEBUG, logger="tcbot.modules.helper.decorators"):
        await anon(_update(uid=None), _ctx())

    assert any("?" in rec.message for rec in caplog.records)


# ──────────────────── Authorization guard helpers ───────────────── #


def _auth_update(uid: int | None = 1) -> tuple[SimpleNamespace, list[str]]:
    """Build a fake Update whose effective_message records reply text."""
    replies: list[str] = []

    async def reply_text(text: str, *args, **kwargs) -> None:
        replies.append(text)

    user = SimpleNamespace(id=uid) if uid is not None else None
    msg = SimpleNamespace(reply_text=reply_text)
    update = SimpleNamespace(effective_user=user, effective_message=msg)
    return update, replies


def _run_marker() -> tuple[object, list[int]]:
    """Return a handler plus the list it appends to when actually invoked."""
    called: list[int] = []

    async def handler(update, ctx) -> str:
        called.append(1)
        return "ran"

    return handler, called


def _roles_from(mapping: dict[int, str | None]):
    async def fake_get_effective_role(uid: int) -> str | None:
        return mapping.get(uid)

    return fake_get_effective_role


# ──────────────────────────── owner_only ────────────────────────── #


async def test_owner_only_allows_owner(monkeypatch) -> None:
    monkeypatch.setattr(users_roles, "is_owner", lambda uid: _truthy(True))
    handler, called = _run_marker()
    update, replies = _auth_update(uid=1)

    result = await owner_only(handler)(update, _ctx())

    assert called == [1]
    assert result == "ran"
    assert replies == []


async def test_owner_only_blocks_non_owner(monkeypatch) -> None:
    monkeypatch.setattr(users_roles, "is_owner", lambda uid: _truthy(False))
    handler, called = _run_marker()
    update, replies = _auth_update(uid=2)

    await owner_only(handler)(update, _ctx())

    assert called == []
    assert len(replies) == 1


async def test_owner_only_error_text(monkeypatch) -> None:
    """Refusal text must match the module constant so voice edits are centralised."""
    monkeypatch.setattr(users_roles, "is_owner", lambda uid: _truthy(False))
    handler, _ = _run_marker()
    update, replies = _auth_update(uid=99)

    await owner_only(handler)(update, _ctx())

    assert replies == [_ERR_OWNER_ONLY]


# ──────────────────────────── staff_only ────────────────────────── #


async def test_staff_only_allows_staff(monkeypatch) -> None:
    monkeypatch.setattr(users_roles, "is_staff", lambda uid: _truthy(True))
    handler, called = _run_marker()
    update, _replies = _auth_update(uid=1)

    await staff_only(handler)(update, _ctx())

    assert called == [1]


async def test_staff_only_blocks_non_staff(monkeypatch) -> None:
    monkeypatch.setattr(users_roles, "is_staff", lambda uid: _truthy(False))
    handler, called = _run_marker()
    update, replies = _auth_update(uid=2)

    await staff_only(handler)(update, _ctx())

    assert called == []
    assert len(replies) == 1


async def test_staff_only_error_text(monkeypatch) -> None:
    """Refusal text must match the module constant so voice edits are centralised."""
    monkeypatch.setattr(users_roles, "is_staff", lambda uid: _truthy(False))
    handler, _ = _run_marker()
    update, replies = _auth_update(uid=99)

    await staff_only(handler)(update, _ctx())

    assert replies == [_ERR_STAFF_ONLY]


# ───────────────────── mod_only / basic_mod_only ────────────────── #


async def test_mod_only_allows_developer_and_blocks_tester(monkeypatch) -> None:
    monkeypatch.setattr(
        users_roles,
        "get_effective_role",
        _roles_from({1: "developer", 2: "tester"}),
    )

    allowed_handler, allowed_called = _run_marker()
    await mod_only(allowed_handler)(_auth_update(uid=1)[0], _ctx())
    assert allowed_called == [1]

    blocked_handler, blocked_called = _run_marker()
    await mod_only(blocked_handler)(_auth_update(uid=2)[0], _ctx())
    assert blocked_called == []


async def test_mod_only_error_text(monkeypatch) -> None:
    """Refusal text must match the module constant so voice edits are centralised."""
    monkeypatch.setattr(
        users_roles,
        "get_effective_role",
        _roles_from({99: "tester"}),
    )
    handler, _ = _run_marker()
    update, replies = _auth_update(uid=99)

    await mod_only(handler)(update, _ctx())

    assert replies == [_ERR_MOD_ONLY]


async def test_basic_mod_only_allows_tester_and_blocks_unranked(monkeypatch) -> None:
    monkeypatch.setattr(
        users_roles,
        "get_effective_role",
        _roles_from({1: "tester", 2: None}),
    )

    allowed_handler, allowed_called = _run_marker()
    await basic_mod_only(allowed_handler)(_auth_update(uid=1)[0], _ctx())
    assert allowed_called == [1]

    blocked_handler, blocked_called = _run_marker()
    await basic_mod_only(blocked_handler)(_auth_update(uid=2)[0], _ctx())
    assert blocked_called == []


async def test_basic_mod_only_error_text(monkeypatch) -> None:
    """Refusal text must match the module constant so voice edits are centralised."""
    monkeypatch.setattr(
        users_roles,
        "get_effective_role",
        _roles_from({99: None}),
    )
    handler, _ = _run_marker()
    update, replies = _auth_update(uid=99)

    await basic_mod_only(handler)(update, _ctx())

    assert replies == [_ERR_BASIC_MOD_ONLY]


# ─────────────────────────── resolve_and_check ──────────────────── #


async def test_resolve_and_check_rejects_low_rank_executor(monkeypatch) -> None:
    monkeypatch.setattr(
        users_roles,
        "get_effective_role",
        _roles_from({1: "tester", 2: None}),
    )
    update, replies = _auth_update()

    executor_role, target_role = await resolve_and_check(
        update.effective_message, 1, 2, min_role="developer"
    )

    assert executor_role is None
    assert target_role is None
    assert len(replies) == 1


async def test_resolve_and_check_rejects_when_target_outranks(monkeypatch) -> None:
    monkeypatch.setattr(
        users_roles,
        "get_effective_role",
        _roles_from({1: "developer", 2: "admin"}),
    )
    update, replies = _auth_update()

    executor_role, target_role = await resolve_and_check(
        update.effective_message, 1, 2, min_role="developer"
    )

    assert executor_role is None
    assert target_role is None
    assert len(replies) == 1


async def test_resolve_and_check_allows_valid_action(monkeypatch) -> None:
    monkeypatch.setattr(
        users_roles,
        "get_effective_role",
        _roles_from({1: "admin", 2: "tester"}),
    )
    update, replies = _auth_update()

    executor_role, target_role = await resolve_and_check(
        update.effective_message, 1, 2, min_role="developer"
    )

    assert executor_role == "admin"
    assert target_role == "tester"
    assert replies == []


async def _truthy(value: bool) -> bool:
    """Await helper so a patched coroutine function can return a plain bool."""
    return value


# ────────────── Error-text pinning for _ERR_RANK_INSUFFICIENT ────── #


def test_err_rank_insufficient_is_non_empty_string() -> None:
    assert isinstance(_ERR_RANK_INSUFFICIENT, str)
    assert len(_ERR_RANK_INSUFFICIENT) > 0


def test_err_rank_insufficient_text_value() -> None:
    assert _ERR_RANK_INSUFFICIENT == "You don't have the rank for this one."


# ───────────────── global_rate_limit_handler ────────────────────── #


def _rate_update(
    uid: int | None = 1,
    *,
    has_cbq: bool = False,
    text: str = "/start",
) -> SimpleNamespace:
    """Build a minimal Update-like namespace for rate-limit tests."""
    user = SimpleNamespace(id=uid) if uid is not None else None
    cbq = SimpleNamespace(answer=AsyncMock()) if has_cbq else None
    msg = SimpleNamespace(text=text, reply_text=AsyncMock())
    return SimpleNamespace(
        effective_user=user,
        callback_query=cbq,
        effective_message=msg,
    )


async def test_global_rate_limit_no_user_returns_none() -> None:
    """Handler returns immediately when effective_user is None."""
    update = _rate_update(uid=None)
    result = await global_rate_limit_handler(update, SimpleNamespace())
    assert result is None


async def test_global_rate_limit_cbq_under_limit_returns_none(monkeypatch) -> None:
    """Callback query under the rate limit - handler returns without raising."""
    monkeypatch.setattr(
        _dec_mod, "_cbq_limiter", SimpleNamespace(check=lambda uid: 0.0)
    )
    update = _rate_update(has_cbq=True)
    result = await global_rate_limit_handler(update, SimpleNamespace())
    assert result is None
    update.callback_query.answer.assert_not_called()


async def test_global_rate_limit_cbq_over_limit_raises(monkeypatch) -> None:
    """Callback query over the rate limit raises ApplicationHandlerStop."""
    monkeypatch.setattr(
        _dec_mod, "_cbq_limiter", SimpleNamespace(check=lambda uid: 5.0)
    )
    update = _rate_update(has_cbq=True)
    with pytest.raises(ApplicationHandlerStop):
        await global_rate_limit_handler(update, SimpleNamespace())
    update.callback_query.answer.assert_awaited_once()


async def test_global_rate_limit_command_under_limit_returns_none(monkeypatch) -> None:
    """Command message under the rate limit - handler returns without raising."""
    monkeypatch.setattr(
        _dec_mod, "_cmd_limiter", SimpleNamespace(check=lambda uid: 0.0)
    )
    update = _rate_update(text="/ban")
    result = await global_rate_limit_handler(update, SimpleNamespace())
    assert result is None


async def test_global_rate_limit_command_over_limit_raises(monkeypatch) -> None:
    """Command message over the rate limit raises ApplicationHandlerStop."""
    monkeypatch.setattr(
        _dec_mod, "_cmd_limiter", SimpleNamespace(check=lambda uid: 3.0)
    )
    update = _rate_update(text="/warn")
    with pytest.raises(ApplicationHandlerStop):
        await global_rate_limit_handler(update, SimpleNamespace())


async def test_global_rate_limit_plain_message_never_rate_checked(monkeypatch) -> None:
    """Plain chat messages (not starting with a prefix) bypass the rate limiter entirely."""
    check_called: list[int] = []

    def _record_check(uid: int) -> float:
        check_called.append(uid)
        return 999.0

    monkeypatch.setattr(_dec_mod, "_cmd_limiter", SimpleNamespace(check=_record_check))
    update = _rate_update(text="Hello world")
    result = await global_rate_limit_handler(update, SimpleNamespace())
    assert result is None
    assert check_called == []
