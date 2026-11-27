# © Copyright 2024 - 2026 Transsion Core
# © Copyright 2024 - 2026 Dizzy
# © Copyright 2026 Ave Labs

"""Per-conversation update serialization helpers for the Kurigram runtime."""

from __future__ import annotations

import asyncio
import inspect
from dataclasses import dataclass, field
from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
    from collections.abc import Awaitable

# * Multi-step flows keep their state per (chat, user). Kurigram dispatches
# * with a worker pool and no ordering guarantee, so a keyed processor keeps
# * one conversation ordered while the rest of the federation stays concurrent.
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
    processed without a lock. The read is duck-typed so the flow scope can
    reuse the same rule without constructing a Kurigram update object.
    """
    chat = getattr(update, "effective_chat", None) or getattr(update, "chat", None)
    user = getattr(update, "effective_user", None) or getattr(update, "from_user", None)
    if chat is None or user is None:
        return None
    chat_id = getattr(chat, "id", None)
    user_id = getattr(user, "id", None)
    if not isinstance(chat_id, int) or not isinstance(user_id, int):
        return None
    return (chat_id, user_id)


class KeyedUpdateProcessor:
    """Process updates one by one per conversation key, concurrently across keys.

    An unkeyed dispatcher starts every update immediately, so two taps on the
    same button can interleave and lose a flow state transition. This
    processor keeps a lock per (chat, user) key, which is the granularity the
    application conversations use, so different moderators still act in
    parallel while one conversation stays ordered.
    """

    def __init__(self, max_concurrent_updates: int = _MAX_CONCURRENT_UPDATES) -> None:
        """Create the processor with its per-key lock map."""
        self._locks: dict[tuple[int, int], _KeyLock] = {}
        # * The global cap bounds the handlers that actually run.
        self._global = asyncio.Semaphore(max_concurrent_updates)

    async def shutdown(self) -> None:
        """Release the per-key locks; nothing to clean up."""
        self._locks.clear()

    async def process_update(  # pyright: ignore[reportIncompatibleMethodOverride]
        self, update: object, coroutine: Awaitable[Any]
    ) -> None:
        """Dispatch the update, taking the conversation lock before the cap.

        A global slot taken before the per-key lock would let a burst on one
        conversation fill every slot with waiting updates and starve other
        chats. Taking the per-key lock first keeps the global cap as a bound
        on handlers that run rather than handlers that wait.
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
        locked = False
        try:
            async with entry.lock:
                locked = True
                await self._guarded(coroutine)
        except asyncio.CancelledError:
            # * A queued update that never reached the handler owns a
            # * coroutine object. Closing it prevents the "never awaited"
            # * warning and releases whatever the handler captured.
            if not locked and inspect.iscoroutine(coroutine):
                coroutine.close()
            raise
        finally:
            # * No await between the decrement and the removal, so the map
            # * never drops a lock another update is about to take.
            entry.waiters -= 1
            if entry.waiters == 0:
                self._locks.pop(key, None)

    async def _guarded(self, coroutine: Awaitable[Any]) -> None:
        """Run one handler under the global concurrency cap."""
        entered = False
        try:
            async with self._global:
                entered = True
                await coroutine
        except asyncio.CancelledError:
            # * Cancellation while waiting for a global slot means the
            # * coroutine was never started.
            if not entered and inspect.iscoroutine(coroutine):
                coroutine.close()
            raise

    @property
    def tracked_keys(self) -> int:
        """Return how many conversation keys currently hold a lock."""
        return len(self._locks)
