# © Copyright 2024 - 2026 Transsion Core
# © Copyright 2024 - 2026 Dizzy
# © Copyright 2026 Ave Labs

"""Per-conversation update serialization for the PTB update processor."""

from __future__ import annotations

import asyncio
from dataclasses import dataclass, field
from typing import TYPE_CHECKING, Any

from telegram import Update
from telegram.ext import BaseUpdateProcessor

if TYPE_CHECKING:
    from collections.abc import Awaitable

# * PTB's ConversationHandler is documented to require one-by-one update
# * processing. The stock `concurrent_updates=True` runs up to 256 updates
# * at once with no ordering guarantee at all, and `concurrent_updates=False`
# * serialises the whole bot. A keyed processor keeps the federation
# * concurrent while making the updates of a single conversation ordered.
_MAX_CONCURRENT_UPDATES: int = 64


@dataclass
class _KeyLock:
    """A lock for one conversation key plus the number of queued waiters."""

    lock: asyncio.Lock = field(default_factory=asyncio.Lock)
    waiters: int = 0


def conversation_key(update: object) -> tuple[int, int] | None:
    """Return the conversation key of ``update``, or ``None`` when it has none.

    The key matches the ``per_chat=True, per_user=True`` conversations the
    project registers: one conversation per (chat, user) pair. An update
    without a chat or a user cannot belong to a conversation, so it is
    processed without a lock.
    """
    if not isinstance(update, Update):
        return None
    chat = update.effective_chat
    user = update.effective_user
    if chat is None or user is None:
        return None
    return (chat.id, user.id)


class KeyedUpdateProcessor(BaseUpdateProcessor):
    """Process updates one by one per conversation key, concurrently across keys.

    ``SimpleUpdateProcessor`` (what ``concurrent_updates=True`` builds) starts
    every update immediately, so two taps on the same button can interleave
    inside a ``ConversationHandler`` and lose a state transition. This
    processor keeps a lock per (chat, user) key, which is exactly the
    granularity the registered conversations use, so different moderators
    still act in parallel while one conversation stays ordered.
    """

    def __init__(self, max_concurrent_updates: int = _MAX_CONCURRENT_UPDATES) -> None:
        """Create the processor with its per-key lock map."""
        super().__init__(max_concurrent_updates)
        self._locks: dict[tuple[int, int], _KeyLock] = {}
        # * The global cap bounds the handlers that actually run. PTB's own
        # * semaphore is left unused: see ``process_update`` below.
        self._global = asyncio.Semaphore(max_concurrent_updates)
        self._running = 0

    async def initialize(self) -> None:
        """Prepare the processor; nothing to allocate up front."""

    async def shutdown(self) -> None:
        """Release the per-key locks; nothing to clean up."""
        self._locks.clear()

    async def process_update(  # pyright: ignore[reportIncompatibleMethodOverride]
        self, update: object, coroutine: Awaitable[Any]
    ) -> None:
        """Dispatch the update, taking the conversation lock before the cap.

        PTB's ``BaseUpdateProcessor.process_update`` takes a global
        concurrency slot *before* the per-key lock. An update queued behind
        a long-running handler of the same conversation would therefore
        hold a global slot while it waits, so a burst on one conversation
        could occupy every slot and starve every other chat in the
        federation. This override keeps the per-key lock first, so the
        global cap bounds the handlers that run rather than the ones that
        wait.

        ``BaseUpdateProcessor.process_update`` is marked ``@final``, which
        is a typing aid rather than a runtime guarantee. The override is
        deliberate and covered by the processor's own tests.
        """
        await self.do_process_update(update, coroutine)

    async def do_process_update(
        self, update: object, coroutine: Awaitable[Any]
    ) -> None:
        """Run the update under the lock of its conversation key."""
        key = conversation_key(update)
        if key is None:
            await self._guarded(coroutine)
            return
        entry = self._locks.get(key)
        if entry is None:
            entry = self._locks[key] = _KeyLock()
        entry.waiters += 1
        try:
            async with entry.lock:
                await self._guarded(coroutine)
        finally:
            # * No await between the decrement and the removal, so the map
            # * never drops a lock another update is about to take.
            entry.waiters -= 1
            if entry.waiters == 0:
                self._locks.pop(key, None)

    async def _guarded(self, coroutine: Awaitable[Any]) -> None:
        """Run one handler under the global concurrency cap."""
        async with self._global:
            self._running += 1
            try:
                await coroutine
            finally:
                self._running -= 1

    @property
    def tracked_keys(self) -> int:
        """Return how many conversation keys currently hold a lock."""
        return len(self._locks)
