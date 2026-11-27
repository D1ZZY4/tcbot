# © Copyright 2024 - 2026 Transsion Core
# © Copyright 2024 - 2026 Dizzy
# © Copyright 2026 Ave Labs

"""Ban proof-session registry, flush, and cancel-path helpers."""

from __future__ import annotations

import asyncio
from typing import Any

from pyrogram import Client

from tcbot import cfg
from tcbot.modules.helper.pipelines.ban_executor import execute_ban
from tcbot.modules.helper.pipelines.proof_session import (
    ProofSession,
    proof_sessions,
    replace_live_session,
)
from tcbot.modules.helper.pipelines.proof_steps import BuildProof
from tcbot.utils.logger import get_logger
from tcbot.utils.time_and_date import monotonic

log = get_logger(__name__)

# ────────────────────────── Proof session ───────────────────────── #


BAN_USER_DATA_KEYS = (
    "ban_target_id",
    "ban_target_fname",
    "ban_reason",
    "ban_admin_id",
    "ban_admin_fname",
    "ban_prompt_msg_id",
    "ban_prompt_chat_id",
    "ban_locale",
)
WAITING_PROOF = 0
WAITING_UPDATE_CONFIRM = 1
proof = BuildProof("ban", skip_allowed=False)
_PROOF_COLLECT_MAX_S: float = 60.0


def _clear_ban_state(scope: dict[str, Any] | None) -> None:
    """Remove all ban-related keys from the conversation scope."""
    if scope is None:
        return
    for key in BAN_USER_DATA_KEYS:
        scope.pop(key, None)


async def _cancel_proof_session(scope: dict[str, Any] | None) -> None:
    """Cancel flushes and await them before clearing state.

    An unawaited flush cleanup could delete a newer ban's scope keys.
    """
    _clear_ban_state(scope)
    if scope is None:
        return
    cancelled: list[asyncio.Task[None]] = []
    for key, session in proof_sessions.items():
        if session.scope is not scope:
            continue
        proof_sessions.pop(key, session)
        session.cancelled = True
        if session.flush_task is not None:
            session.flush_task.cancel()
            cancelled.append(session.flush_task)
    if cancelled:
        await asyncio.gather(*cancelled, return_exceptions=True)


async def replace_live_proof_session(
    scope: dict[str, Any], chat_id: int, user_id: int
) -> bool:
    """Retire an unfinished session before a re-entry replaces its scope."""
    return await replace_live_session(
        proof_sessions, scope, chat_id, user_id, _clear_ban_state
    )


async def drain_proof_sessions() -> None:
    """Let pending proof flushes finish so no ban is left half-applied."""
    await proof_sessions.drain()


# ─────────────────────── Proof session flush ────────────────────── #


async def _flush_session(key: tuple[int, int], bot: Client) -> None:
    """Flush one proof session after a silence window or the hard cap."""
    # * Own the session from the first await, so a cancellation during the
    # * silence window still releases the registry entry in the finally block.
    session: ProofSession | None = proof_sessions.get(key)
    if session is None:
        return
    try:
        while True:
            # * Sleep no longer than the collection deadline: a deployment
            # * with a very large debounce value must not defeat the hard
            # * 60-second cap and leave a ban unflushed indefinitely.
            remaining = session.deadline - monotonic()
            if remaining <= 0:
                break
            await asyncio.sleep(min(cfg.album_debounce, remaining))
            if (
                proof_sessions.get(key) is not session
                or session.cancelled
                or session.flushing
            ):
                return
            if (
                monotonic() - session.last_arrival >= cfg.album_debounce
                or monotonic() >= session.deadline
            ):
                break
        # * Claim is synchronous: Done and this timer can never double-execute.
        session.flushing = True
        if (
            not session.msgs
            or not session.meta.get("ban_target_id")
            or not session.meta.get("ban_admin_id")
        ):
            if session.msgs:
                log.warning("Session flush aborted: meta missing target or admin")
            return
        # * execute_ban runs the shared enforcement gate before any record,
        # * proof, or fan-out, and it edits the prompt when the executor no
        # * longer holds the rank. A second rank read here could only abort
        # * the flush silently after the moderator already sent the proof.
        log.info(
            "Flushing proof session %s with %d media items", key, len(session.msgs)
        )
        try:
            await execute_ban(bot, session.msgs, session.meta)
        except Exception:
            log.exception("execute_ban raised in _flush_session for %s", key)
    except asyncio.CancelledError:
        raise
    finally:
        if session is not None and proof_sessions.get(key) is session:
            proof_sessions.pop(key, None)
            _clear_ban_state(session.scope)


__all__ = [
    "BAN_USER_DATA_KEYS",
    "WAITING_PROOF",
    "WAITING_UPDATE_CONFIRM",
    "drain_proof_sessions",
    "proof",
    "proof_sessions",
    "replace_live_proof_session",
]
