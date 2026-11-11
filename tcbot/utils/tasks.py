# © Copyright 2024 - 2026 Transsion Core
# © Copyright 2024 - 2026 Dizzy
# © Copyright 2026 Ave Labs

"""Lifecycle owner for fire-and-forget background tasks."""

from __future__ import annotations

import asyncio
from typing import TYPE_CHECKING

from tcbot.utils.logger import get_logger

if TYPE_CHECKING:
    from collections.abc import Coroutine
    from typing import Any

log = get_logger(__name__)

# * Default drain budget. Long enough for a slow Telegram call to finish,
# * short enough to keep the shutdown bounded.
DEFAULT_DRAIN_TIMEOUT_S: float = 5.0


class TaskTracker:
    """Owns a set of fire-and-forget tasks and drains them at shutdown.

    Single owner for the "schedule background work and collect it at
    shutdown" pattern. A tracker keeps a strong reference to every task it
    schedules so the garbage collector cannot drop a running coroutine, and
    it releases them in one place instead of every owner exposing its own
    drain helper.
    """

    __slots__ = ("_label", "_tasks")

    def __init__(self, label: str) -> None:
        """Create a tracker whose drain is reported under *label*."""
        self._label = label
        self._tasks: set[asyncio.Task[None]] = set()

    @property
    def label(self) -> str:
        """The label used in the drain log lines."""
        return self._label

    @property
    def pending(self) -> int:
        """How many tracked tasks have not finished yet."""
        return sum(1 for task in self._tasks if not task.done())

    def spawn(self, coro: Coroutine[Any, Any, None]) -> bool:
        """Schedule *coro* and track it until it finishes.

        Returns ``False`` when no event loop is running. The coroutine is
        closed in that case so it never leaks as a never-awaited object.
        """
        try:
            loop = asyncio.get_running_loop()
        except RuntimeError:
            coro.close()
            log.debug("%s task skipped: no running event loop.", self._label)
            return False
        task = loop.create_task(coro)
        self._tasks.add(task)
        task.add_done_callback(self._tasks.discard)
        task.add_done_callback(self._log_failure)
        return True

    def _log_failure(self, task: asyncio.Task[None]) -> None:
        """Retrieve a failed task's exception so asyncio stays quiet.

        An unretrieved task exception is reported by asyncio as "Task
        exception was never retrieved" through the root logger, which would
        re-enter the reporting loop that produced it.
        """
        if task.cancelled():
            return
        exc = task.exception()
        if exc is None:
            return
        log.warning("%s task failed: %s", self._label, exc)

    async def drain(self, *, timeout: float = DEFAULT_DRAIN_TIMEOUT_S) -> None:
        """Await the tracked tasks, then cancel the leftovers; never raises.

        Waits up to *timeout* seconds for the in-flight work, cancels
        anything still running, and awaits the cancellations so no task
        outlives the loop teardown.
        """
        live = [task for task in list(self._tasks) if not task.done()]
        if not live:
            return
        try:
            await asyncio.wait_for(
                asyncio.gather(*live, return_exceptions=True), timeout=timeout
            )
            return
        except TimeoutError:
            log.debug(
                "%s: %d task(s) still running after %.0fs; cancelling.",
                self._label,
                len(live),
                timeout,
            )
        for task in live:
            if not task.done():
                task.cancel()
        try:
            await asyncio.wait_for(
                asyncio.gather(
                    *[task for task in live if not task.done()], return_exceptions=True
                ),
                timeout=timeout,
            )
        except TimeoutError:
            log.debug("%s: tasks survived cancellation; leaving them.", self._label)
