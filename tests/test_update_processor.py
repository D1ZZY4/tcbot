# © Copyright 2024 - 2026 Transsion Core
# © Copyright 2024 - 2026 Dizzy
# © Copyright 2026 Ave Labs

"""The keyed update processor keeps one conversation ordered.

python-telegram-bot documents that ``ConversationHandler`` "heavily relies on
incoming updates being processed one by one", yet the stock
``concurrent_updates=True`` starts every update immediately with no ordering
guarantee. Two taps on the same button could therefore interleave inside a
conversation and lose a state transition.

``KeyedUpdateProcessor`` serialises the updates of one (chat, user) pair and
leaves the rest of the federation concurrent, which is exactly the
granularity the registered conversations use.
"""

from __future__ import annotations

import asyncio
from typing import Any

import pytest
from telegram import Update

from tcbot.utils.update_processor import KeyedUpdateProcessor, conversation_key


class _FakeChat:
    def __init__(self, chat_id: int) -> None:
        self.id = chat_id


class _FakeUser:
    def __init__(self, user_id: int) -> None:
        self.id = user_id


class _FakeUpdate(Update):
    """Minimal Update double carrying only an effective chat and user."""

    def __init__(self, chat_id: int, user_id: int) -> None:
        super().__init__(update_id=0)
        self._chat = _FakeChat(chat_id)
        self._user = _FakeUser(user_id)

    @property
    def effective_chat(self) -> Any:
        return self._chat

    @property
    def effective_user(self) -> Any:
        return self._user


def test_the_conversation_key_is_the_chat_and_user_pair() -> None:
    """The key must match the per_chat + per_user conversations."""
    assert conversation_key(_FakeUpdate(100, 42)) == (100, 42)  # type: ignore[arg-type]


def test_updates_of_one_key_run_in_order() -> None:
    """Two updates of the same conversation must not overlap."""
    order: list[str] = []
    started = asyncio.Event()
    release = asyncio.Event()

    async def _first() -> None:
        order.append("first-start")
        started.set()
        await release.wait()
        order.append("first-end")

    async def _second() -> None:
        order.append("second-start")
        order.append("second-end")

    async def _scenario() -> None:
        processor = KeyedUpdateProcessor()
        update = _FakeUpdate(100, 42)
        first = asyncio.create_task(processor.process_update(update, _first()))
        await started.wait()
        second = asyncio.create_task(processor.process_update(update, _second()))
        await asyncio.sleep(0)
        # * The second update is queued behind the first one.
        assert order == ["first-start"]
        release.set()
        await asyncio.gather(first, second)

    asyncio.run(_scenario())
    assert order == ["first-start", "first-end", "second-start", "second-end"]


def test_updates_of_different_keys_run_concurrently() -> None:
    """Two conversations must still run in parallel."""
    both_started = asyncio.Event()
    started = 0

    async def _handler() -> None:
        nonlocal started
        started += 1
        if started == 2:
            both_started.set()
        await asyncio.wait_for(both_started.wait(), timeout=1)

    async def _scenario() -> None:
        processor = KeyedUpdateProcessor()
        await asyncio.gather(
            processor.process_update(_FakeUpdate(100, 42), _handler()),
            processor.process_update(_FakeUpdate(200, 42), _handler()),
        )

    asyncio.run(_scenario())


def test_the_lock_map_does_not_grow() -> None:
    """Finished conversations must release their lock."""
    processor = KeyedUpdateProcessor()

    async def _noop() -> None:
        return None

    async def _scenario() -> None:
        await processor.process_update(_FakeUpdate(100, 42), _noop())
        await processor.process_update(_FakeUpdate(200, 42), _noop())

    asyncio.run(_scenario())
    assert processor.tracked_keys == 0


def test_an_update_without_a_chat_is_processed_directly() -> None:
    """An update outside a conversation must not be blocked or dropped."""
    processor = KeyedUpdateProcessor()
    ran = False

    async def _handler() -> None:
        nonlocal ran
        ran = True

    async def _scenario() -> None:
        await processor.process_update(object(), _handler())

    asyncio.run(_scenario())
    assert ran


def test_a_failing_update_releases_its_lock() -> None:
    """A raising handler must not strand the conversation lock."""
    processor = KeyedUpdateProcessor()

    async def _boom() -> None:
        raise RuntimeError("handler failed")

    async def _scenario() -> None:
        with pytest.raises(RuntimeError):
            await processor.process_update(_FakeUpdate(100, 42), _boom())

    asyncio.run(_scenario())
    assert processor.tracked_keys == 0
