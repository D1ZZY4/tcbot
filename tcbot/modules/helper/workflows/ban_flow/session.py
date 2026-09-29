# © Copyright 2024 - 2026 Transsion Core
# © Copyright 2024 - 2026 Dizzy
# © Copyright 2026 Ave Labs

"""Proof-collection session registry and silence-window flush task."""

from __future__ import annotations

import asyncio
from dataclasses import dataclass, field
from typing import TYPE_CHECKING, Any

from telegram import Message

from tcbot import cfg

# * Registry and executor resolve through the package namespace, keeping one
# * live binding for every submodule and caller.
from tcbot.modules.helper.workflows import ban_flow as _flow
from tcbot.modules.helper.workflows.ban_flow.shared import BAN_USER_DATA_KEYS
from tcbot.utils.logger import get_logger
from tcbot.utils.time_and_date import monotonic

if TYPE_CHECKING:
    from telegram import Bot

log = get_logger(__name__)


@dataclass
class _ProofSession:
    """One in-progress proof collection, keyed by (chat_id, user_id).

    Gathers every proof message (album parts and sequential sends alike)
    until the Done button or a silence window flushes it. ``flushing`` is
    claimed with a synchronous check-and-set so a Done tap and the flush
    task can never execute the same session twice. The session stays
    visible (with ``flushing`` set) through execution so late arrivals
    are dropped exactly like the old executing-flag guard.
    """

    msgs: list[Message] = field(default_factory=list)
    meta: dict[str, Any] = field(default_factory=dict)
    user_data: dict[str, Any] | None = None
    deadline: float = 0.0
    last_arrival: float = 0.0
    flushing: bool = False
    cancelled: bool = False
    flush_task: asyncio.Task[None] | None = None


# * Live proof sessions keyed by (chat_id, user_id). user_data is per
# * (chat, user) under per_chat/per_user routing, so one key maps to one
# * conversation exactly.
_proof_sessions: dict[tuple[int, int], _ProofSession] = {}


def _clear_ban_state(user_data: dict[str, Any] | None) -> None:
    """Remove all ban-related keys from ``user_data``.

    Safe to call when ``user_data`` is ``None`` (no-op).
    """
    if user_data is None:
        return
    for key in BAN_USER_DATA_KEYS:
        user_data.pop(key, None)


def _cancel_proof_session(user_data: dict[str, Any] | None) -> None:
    """Cancel any in-flight proof flush tasks and clear all ban state.

    Clears ban keys from ``user_data`` and cancels every flush task whose
    session references the given dict. Called from ``on_cancel_proof`` and
    ``on_proof_timeout`` so the cleanup path is defined exactly once.
    (``on_done_proof`` cleans its own claimed session inline instead.)
    """
    _clear_ban_state(user_data)
    if user_data is None:
        return
    sessions = _flow._proof_sessions
    for key in [k for k, s in sessions.items() if s.user_data is user_data]:
        session = sessions.pop(key)
        session.cancelled = True
        if session.flush_task is not None:
            session.flush_task.cancel()


async def _flush_session(key: tuple[int, int], bot: Bot) -> None:
    """Flush one proof session after a silence window or the hard cap."""
    session: _ProofSession | None = None
    try:
        while True:
            await asyncio.sleep(cfg.album_debounce)
            session = _flow._proof_sessions.get(key)
            if session is None or session.cancelled or session.flushing:
                return
            if (
                monotonic() - session.last_arrival >= cfg.album_debounce
                or monotonic() >= session.deadline
            ):
                break
        # * Synchronous claim, mirroring on_done_proof: exactly one of the
        # * two paths proceeds, and the session stays visible with flushing
        # * set so late arrivals drop instead of double-executing.
        session = _flow._proof_sessions.get(key)
        if session is None or session.flushing or session.cancelled:
            return
        session.flushing = True
        if (
            not session.msgs
            or not session.meta.get("ban_target_id")
            or not session.meta.get("ban_admin_id")
        ):
            if session.msgs:
                log.warning("Session flush aborted: meta missing target or admin")
            return
        log.info(
            "Flushing proof session %s with %d media items", key, len(session.msgs)
        )
        try:
            await _flow._execute_ban(bot, session.msgs, session.meta)
        except Exception:
            log.exception("_execute_ban raised in _flush_session for %s", key)
    except asyncio.CancelledError:
        # * Done tap or cancel/timeout path took over; propagate so the
        # * task ends, with shared cleanup below.
        raise
    finally:
        # * Never pop a successor session that may have taken the key while
        # * this task unwound: only this task's own claimed session object
        # * may be cleared.
        if session is not None and _flow._proof_sessions.get(key) is session:
            _flow._proof_sessions.pop(key, None)
            _clear_ban_state(session.user_data)
