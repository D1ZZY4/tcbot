# © Copyright 2024 - 2026 Transsion Core
# © Copyright 2024 - 2026 Dizzy
# © Copyright 2026 Aveum Apps

"""Tests for tcbot.modules.helper.decorators - @log_execution decorator."""

from __future__ import annotations

import logging
from types import SimpleNamespace

import pytest

from tcbot.modules.helper.decorators import log_execution

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
