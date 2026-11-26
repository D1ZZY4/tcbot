# © Copyright 2024 - 2026 Transsion Core
# © Copyright 2024 - 2026 Dizzy
# © Copyright 2026 Ave Labs

"""Error classification, operator hints, and delivery-routing predicates."""

from __future__ import annotations

import asyncio
import re
from typing import TYPE_CHECKING

from tcbot.database import engine as db_engine
from tcbot.modules.helper.pipelines.errors.exceptions import (
    PollingConflictError,
    is_bad_request,
    is_forbidden,
    is_invalid_button_user,
    is_mtproto_auth_error,
    is_owner_only,
    is_rate_limit,
    is_rpc_error,
    is_telegram_timeout,
    is_unauthorized,
)
from tcbot.utils.circuit_breaker import CircuitOpenError
from tcbot.utils.logger import get_logger

if TYPE_CHECKING:
    import logging

log = get_logger("tcbot.error_reporter")

# * Log-noise patterns come from log_execution wrapping every handler.
_BENIGN_PATTERNS: tuple[str, ...] = (
    "message is not modified",
    "message to edit not found",
    "message to delete not found",
    "query is too old",
    "message is too old",
    "message can't be edited",
)
# * The tracer logs "… raised after Nms" only for an exception it is about to
# * re-raise. Match its whole shape so an unrelated error that merely mentions
# * elapsed time is still reported.
_LOG_NOISE_RE = re.compile(r"\[[^]]+\] uid=\S+ raised after [\d.]+ms")


def _benign(exc: BaseException | None) -> bool:
    """Check recoverable no-op (cancel, circuit, outage, known Telegram no-ops)."""
    if exc is None:
        return False
    if isinstance(exc, asyncio.CancelledError):
        return True
    if db_engine.is_connection_error(exc) or isinstance(exc, CircuitOpenError):
        return True
    # * A saturated pool is a load condition, not a defect. The circuit
    # * breaker reacts to it, and the handler logs it as a warning, so
    # * shipping a report per timeout would only bury the incidents that
    # * need an operator.
    if db_engine.is_pool_timeout(exc):
        return True
    msg = str(exc).lower()
    return any(p in msg for p in _BENIGN_PATTERNS)


def _is_benign(exc: BaseException | None) -> bool:
    """Return True when the exception is a recoverable no-op.

    The reporter exists precisely for unexpected failures, so a predicate
    that itself fails must never discard the report: the unknown state is
    reported instead of swallowed.
    """
    if exc is None:
        return False
    try:
        return _benign(exc)
    except Exception as check_exc:
        log.warning("Benign check failed, treating as reportable: %s", check_exc)
        return False


def _log_noise(record: logging.LogRecord | None) -> bool:
    """Check whether this is the tracer's duplicate of an already-reported error."""
    return bool(record) and bool(_LOG_NOISE_RE.search(record.getMessage()))


def _owner_only(exc: BaseException | None) -> bool:
    """Check owner-only routing to the owner DM only."""
    return exc is not None and is_owner_only(exc)


_ACTION_HINTS: tuple[tuple[str, str], ...] = (
    (
        "PostgreSQL Circuit Open",
        "PostgreSQL is unreachable; the circuit is open and calls fail fast "
        "until recovery. Check the database reachability and credentials, then retry.",
    ),
    ("[DB]", "Check PostgreSQL reachability and credentials, then retry the action."),
    ("Rate Limit", "Telegram asked to slow down; no action needed unless it persists."),
    ("Timed Out", "Transient Telegram hiccup; retry the action."),
    ("Polling Conflict", "Two bot instances are polling; stop the duplicate."),
    ("Invalid Token", "Token revoked or wrong; set BOT_TOKEN and restart."),
    ("Forbidden", "Client lacks admin rights in the target chat; re-promote it."),
    (
        "User Profile Button",
        "A mention in the card points to an id Telegram cannot address. "
        "Re-render that card without the mention or clear its keyboard.",
    ),
    ("Bad Request", "Check the reported call arguments for a bad ID or text."),
    ("Network", "Transient connectivity issue; retry the action."),
    ("Timeout", "Operation exceeded its deadline; retry the action."),
    ("Code Bug", "Needs a code fix; see the traceback below."),
    ("[?] Unknown", "No exception attached; check the message and location above."),
    ("Circuit Open", "Telegram circuit is open; retry after the cooldown."),
    (
        "MTProto Auth",
        "MTProto auth key is dead; stop every instance, delete the session "
        "rows from mtproto_state, then boot one.",
    ),
)


def _action_hint(label: str) -> str:
    """Return the operator action line for a classify label."""
    for marker, hint in _ACTION_HINTS:
        if marker in label:
            return hint
    return "Check the message and location above."


def _is_telegram_timeout(exc: BaseException) -> bool:
    """Match Kurigram's RPC timeout without claiming builtin timeouts.

    Python 3.11 made ``asyncio.TimeoutError`` an alias of the builtin, so an
    ``isinstance(exc, TimeoutError)`` branch would label database and worker
    deadlines as Telegram failures and make the generic timeout branches below
    unreachable. Match the client's RPC timeout classes directly: the old
    name-based check looked for ``TimedOut``, which the client never defines,
    so real RPC deadlines were reported as generic API errors.
    """
    return is_telegram_timeout(exc)


def _classify(exc: BaseException | None) -> str:
    """Return a human-readable label tag for the exception."""
    if exc is None:
        return "[?] Unknown"
    # * AuthKeyDuplicated subclasses RPCError in Kurigram; match dead keys
    # * before the generic branch so they keep the operator hint.
    if is_mtproto_auth_error(exc):
        return "[~] MTProto Auth Key Invalidated"
    if is_rate_limit(exc):
        return "[~] Rate Limit: Flood Wait"
    if _is_telegram_timeout(exc):
        return "[~] Telegram Timed Out"
    if isinstance(exc, PollingConflictError):
        return "[~] Polling Conflict"
    if is_invalid_button_user(exc):
        return "[!] Telegram User Profile Button Invalid"
    if is_bad_request(exc):
        return "[!] Telegram Bad Request"
    if is_forbidden(exc):
        return "[!] Telegram Forbidden"
    if is_unauthorized(exc):
        return "[!] Telegram Invalid Token"
    # * TimeoutError derives from OSError, so the generic timeout check must
    # * precede the network branch or every deadline becomes a Telegram error.
    if isinstance(exc, asyncio.TimeoutError):
        return "[~] Async Timeout"
    if isinstance(exc, OSError):
        return "[~] Telegram Network Error"
    if is_rpc_error(exc):
        return "[!] Telegram API Error"
    mod = type(exc).__module__ or ""
    if db_engine.is_database_error(exc):
        return "[DB] Database Error"
    if isinstance(exc, CircuitOpenError):
        return (
            "[~] PostgreSQL Circuit Open"
            if "postgres" in str(exc).lower()
            else "[~] Circuit Open"
        )
    if "circuit_breaker" in mod:
        return "[~] Circuit Open"
    if isinstance(exc, asyncio.CancelledError):
        return "[-] Task Cancelled"
    if isinstance(exc, (ConnectionError, TimeoutError, OSError)) or any(
        x in mod for x in ("httpx", "aiohttp", "urllib3", "ssl")
    ):
        return "[~] Network / Server Error"
    return "[!] Code Bug"


__all__ = [
    "_ACTION_HINTS",
    "_action_hint",
    "_benign",
    "_classify",
    "_is_benign",
    "_is_telegram_timeout",
    "_log_noise",
    "_owner_only",
]
