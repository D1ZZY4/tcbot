# © Copyright 2024 - 2026 Transsion Core
# © Copyright 2024 - 2026 Dizzy
# © Copyright 2026 Ave Labs

"""Catch-all handlers and error context survive Kurigram's dispatch rules."""

from __future__ import annotations

import asyncio
from types import SimpleNamespace
from typing import Any

import pytest
from pyrogram import ContinuePropagation
from pyrogram.handlers import MessageHandler as PyrogramMessageHandler

from tcbot import __main__ as main_mod
from tcbot.modules.helper import handlers as handlers_mod


def test_cache_handler_runs_before_module_handlers(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Kurigram stops at the first consuming handler, so caching must be first."""
    registered: list[int] = []

    class FakeClient:
        def add_handler(self, handler: Any, group: int = 0) -> None:
            registered.append(group)

    def _handlers() -> list[Any]:
        return [PyrogramMessageHandler(lambda _client, _update: None)]

    monkeypatch.setattr(main_mod, "get_handlers", _handlers)
    main_mod.register_handlers(FakeClient())  # type: ignore[arg-type]

    assert registered.index(main_mod._HANDLER_GROUP_CACHE) < registered.index(0)
    assert registered.index(0) < registered.index(main_mod._HANDLER_GROUP_UNOWNED)


def test_the_cache_handler_passes_the_update_to_the_flows() -> None:
    """Caching an identity must not consume the command or callback."""
    with pytest.raises(ContinuePropagation):
        asyncio.run(main_mod._on_any_update(None, object()))  # type: ignore[arg-type]


def test_a_handler_failure_carries_its_update_context(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """The dispatcher reports errors after the ContextVar is reset."""
    ctx = SimpleNamespace(
        effective_user=SimpleNamespace(first_name="Ayu", id=42),
        effective_chat=SimpleNamespace(
            type=SimpleNamespace(value="private"), title=None, id=None
        ),
        effective_message=SimpleNamespace(text="hello"),
        callback_query=None,
    )

    async def _build(*_args: Any, **_kwargs: Any) -> SimpleNamespace:
        return ctx

    async def _process(_ctx: Any, coro: Any) -> None:
        await coro

    async def _failing(_ctx: Any) -> None:
        raise RuntimeError("handler failed")

    monkeypatch.setattr(handlers_mod, "build_ctx", _build)
    monkeypatch.setattr(handlers_mod._updates, "do_process_update", _process)

    with pytest.raises(RuntimeError) as caught:
        asyncio.run(handlers_mod._wrap(_failing)(None, object()))

    snapshot = handlers_mod.error_context(caught.value)
    assert snapshot is not None
    assert snapshot["user_name"] == "Ayu"
    assert snapshot["text"] == "hello"
    assert handlers_mod.current_ctx() is None


def test_the_error_report_uses_the_snapshot_on_the_exception(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """An unhandled error still names the user even after the wrapper unwound."""
    captured: list[str | None] = []

    async def _report(_exc: BaseException, *, context: str | None = None) -> None:
        captured.append(context)

    monkeypatch.setattr(main_mod.report, "report_exc", _report)
    exc = RuntimeError("handler failed")
    handlers_mod.remember_error_context(
        exc,
        SimpleNamespace(
            effective_user=SimpleNamespace(first_name="Ayu", id=42),
            effective_chat=SimpleNamespace(
                type=SimpleNamespace(value="group"), title="Group", id=-100
            ),
            effective_message=SimpleNamespace(text="hello"),
            callback_query=None,
        ),
    )

    asyncio.run(
        main_mod._error_handler(None, exc, None, None, None, None)  # type: ignore[arg-type]
    )

    assert captured == ["User: Ayu (42) | Chat: Group (-100) | Text: hello"]
