# © Copyright 2024 - 2026 Transsion Core
# © Copyright 2024 - 2026 Dizzy
# © Copyright 2026 Ave Labs

"""Storage and shutdown owner for in-flight moderation proof collections."""

from __future__ import annotations

import asyncio
from dataclasses import dataclass, field
from typing import TYPE_CHECKING, Any

from tcbot.utils.logger import get_logger

if TYPE_CHECKING:
    from collections.abc import Iterator

    from telegram import Message

log = get_logger(__name__)

# * Upper bound for the shutdown drain of the pending proof flushes.
_PROOF_DRAIN_TIMEOUT_S: float = 30.0


@dataclass
class ProofSession:
    """One in-progress proof collection keyed by ``(chat_id, user_id)``."""

    msgs: list[Message] = field(default_factory=list)
    meta: dict[str, Any] = field(default_factory=dict)
    scope: dict[str, Any] = field(default_factory=dict)
    deadline: float = 0.0
    last_arrival: float = 0.0
    flushing: bool = False
    cancelled: bool = False
    flush_task: asyncio.Task[None] | None = None


class ProofSessionRegistry:
    """Owns the live proof sessions and their shutdown contract.

    The registry is independent of the ban executor: the flow creates a
    session, attaches its flush task, and consumes the same object. Keeping
    the lifecycle here makes it testable without importing the executor.
    """

    __slots__ = ("_sessions",)

    def __init__(self) -> None:
        """Create an empty registry."""
        self._sessions: dict[tuple[int, int], ProofSession] = {}

    def get(self, key: tuple[int, int]) -> ProofSession | None:
        """Return the session of one conversation, when present."""
        return self._sessions.get(key)

    def add(self, key: tuple[int, int], session: ProofSession) -> None:
        """Register a new session for one conversation."""
        self._sessions[key] = session

    def pop(
        self, key: tuple[int, int], session: ProofSession | None = None
    ) -> ProofSession | None:
        """Remove one session, optionally only when it is still the same."""
        current = self._sessions.get(key)
        if current is None or (session is not None and current is not session):
            return None
        return self._sessions.pop(key)

    def items(self) -> Iterator[tuple[tuple[int, int], ProofSession]]:
        """Return a snapshot of the live sessions for cancellation paths."""
        return iter(list(self._sessions.items()))

    def values(self) -> list[ProofSession]:
        """Return the live sessions in insertion order."""
        return list(self._sessions.values())

    def __getitem__(self, key: tuple[int, int]) -> ProofSession:
        """Return the session of one conversation."""
        return self._sessions[key]

    def __setitem__(self, key: tuple[int, int], session: ProofSession) -> None:
        """Register a session through the mapping shape."""
        self._sessions[key] = session

    def __delitem__(self, key: tuple[int, int]) -> None:
        """Remove a session through the mapping shape."""
        del self._sessions[key]

    def __contains__(self, key: object) -> bool:
        """Return whether one conversation still has a session."""
        return key in self._sessions

    def __len__(self) -> int:
        """Return the number of live sessions."""
        return len(self._sessions)

    async def drain(self) -> None:
        """Let pending flushes finish, then cancel sessions still waiting.

        A running flush already owns its ban record and fan-out, so the drain
        waits for it and cancels only the sessions still in their silence
        window.
        """
        pending = [
            session.flush_task
            for session in self._sessions.values()
            if session.flush_task is not None
        ]
        live = [task for task in pending if not task.done()]
        if not live:
            return
        try:
            await asyncio.wait_for(
                asyncio.gather(*live, return_exceptions=True),
                timeout=_PROOF_DRAIN_TIMEOUT_S,
            )
            return
        except TimeoutError:
            log.warning(
                "Proof flush still running after %.0fs; cancelling.",
                _PROOF_DRAIN_TIMEOUT_S,
            )
        for task in live:
            if not task.done():
                task.cancel()
        await asyncio.gather(
            *[task for task in live if not task.done()], return_exceptions=True
        )


proof_sessions = ProofSessionRegistry()
