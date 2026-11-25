# © Copyright 2024 - 2026 Transsion Core
# © Copyright 2024 - 2026 Dizzy
# © Copyright 2026 Ave Labs

"""Per-conversation update serialization helpers for the Kurigram runtime."""

from __future__ import annotations

import asyncio
import contextlib
import inspect
from collections import deque
from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
    from collections.abc import Awaitable

# * Multi-step flows keep their state per (chat, user). Kurigram dispatches
# * with a worker pool and no ordering guarantee, so a keyed processor keeps
# * one conversation ordered while the rest of the federation stays concurrent.
_MAX_CONCURRENT_UPDATES: int = 64


def conversation_key(update: object) -> tuple[int, int] | None:
    """Return the conversation key of ``update``, or ``None`` when it has none.

    The key matches the ``per_chat=True, per_user=True`` conversations the
    project registers: one conversation per (chat, user) pair. An update
    without a chat or a user cannot belong to a conversation, so it is
    processed without a lock. The read is duck-typed so the flow scope can
    reuse the same rule without constructing a Kurigram update object.
    """
    chat = getattr(update, "effective_chat", None)
    if chat is None:
        chat = getattr(update, "chat", None)
    user = getattr(update, "effective_user", None)
    if user is None:
        user = getattr(update, "from_user", None)
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
    processor keeps a FIFO waiter queue per (chat, user) key, which is the
    granularity the application conversations use, so different moderators
    still act in parallel while one conversation stays ordered. Uncontended
    keys pay zero lock or queue allocation.
    """

    def __init__(self, max_concurrent_updates: int = _MAX_CONCURRENT_UPDATES) -> None:
        """Create the processor with its per-key waiter map."""
        self._queues: dict[tuple[int, int], deque[asyncio.Future[None]] | None] = {}
        # * The global cap bounds the handlers that actually run.
        self._global = asyncio.Semaphore(max_concurrent_updates)

    async def initialize(self) -> None:
        """Prepare the processor; nothing to allocate up front."""

    async def shutdown(self) -> None:
        """Release the per-key waiter map; nothing to clean up."""
        self._queues.clear()

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

    def _release_key(self, key: tuple[int, int]) -> None:
        """Wake the next waiter for ``key`` or drop the entry if idle."""
        q = self._queues.get(key)
        if not q:
            self._queues.pop(key, None)
            return
        next_fut = q.popleft()
        if not next_fut.done():
            next_fut.set_result(None)

    async def do_process_update(
        self, update: object, coroutine: Awaitable[Any]
    ) -> None:
        """Run the update under the FIFO serialization of its conversation key."""
        key = conversation_key(update)
        if key is None:
            await self._guarded(coroutine)
            return
        if key not in self._queues:
            # * Fast path: uncontended key allocates neither a lock nor a deque.
            self._queues[key] = None
            try:
                await self._guarded(coroutine)
            finally:
                self._release_key(key)
            return

        q = self._queues[key]
        if q is None:
            q = self._queues[key] = deque()
        fut = asyncio.get_running_loop().create_future()
        q.append(fut)
        acquired = False
        try:
            await fut
            acquired = True
            await self._guarded(coroutine)
        except asyncio.CancelledError:
            if not acquired:
                # * A queued update that never reached the handler owns a
                # * coroutine object. Closing it prevents the "never awaited"
                # * warning and releases whatever the handler captured.
                if inspect.iscoroutine(coroutine):
                    coroutine.close()
                with contextlib.suppress(ValueError):
                    q.remove(fut)
            raise
        finally:
            if acquired or (fut.done() and not fut.cancelled()):
                self._release_key(key)

    async def _guarded(self, coroutine: Awaitable[Any]) -> None:
        """Run one handler under the global concurrency cap."""
        entered = False
        try:
            await self._global.acquire()
            entered = True
            await coroutine
        except asyncio.CancelledError:
            # * Cancellation while waiting for a global slot means the
            # * coroutine was never started.
            if not entered and inspect.iscoroutine(coroutine):
                coroutine.close()
            raise
        finally:
            if entered:
                self._global.release()

    @property
    def tracked_keys(self) -> int:
        """Return how many conversation keys currently hold a lock."""
        return len(self._queues)
