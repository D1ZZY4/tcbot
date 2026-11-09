# © Copyright 2024 - 2026 Transsion Core
# © Copyright 2024 - 2026 Dizzy
# © Copyright 2026 Ave Labs

"""Transfer and warn-manage delivery gathers propagate cancellation."""

from __future__ import annotations

import asyncio

import pytest

from tcbot.utils.dispatch import throw_if_cancelled


class _CancelledBot:
    async def send_message(self, *args: object, **kwargs: object) -> object:
        raise asyncio.CancelledError

    async def reply_text(self, *args: object, **kwargs: object) -> object:
        raise asyncio.CancelledError


class _FakeChat:
    id = 1
    title = "Group"
    type = "supergroup"


class _FakeMessage:
    def __init__(self) -> None:
        self.chat = _FakeChat()

    async def reply_text(self, *args: object, **kwargs: object) -> object:
        raise asyncio.CancelledError


def test_transfer_delivery_cancellation_propagates(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    async def _scenario() -> None:
        # Directly exercise the delivery gather shape used by cmd_transfer.
        results = await asyncio.gather(
            _CancelledBot().send_message(),
            _FakeMessage().reply_text(),
            return_exceptions=True,
        )
        with pytest.raises(asyncio.CancelledError):
            throw_if_cancelled(results)

    asyncio.run(_scenario())


def test_warn_manage_delivery_cancellation_propagates() -> None:
    async def _scenario() -> None:
        results = await asyncio.gather(
            _CancelledBot().send_message(),
            _FakeMessage().reply_text(),
            return_exceptions=True,
        )
        with pytest.raises(asyncio.CancelledError):
            throw_if_cancelled(results)

    asyncio.run(_scenario())
