# © Copyright 2024 - 2026 Transsion Core
# © Copyright 2024 - 2026 Dizzy
# © Copyright 2026 Ave Labs

"""Error classification: benign filters, owner-only routing, and labels."""

from __future__ import annotations

import asyncio
from typing import TYPE_CHECKING

import telegram.error as _te

if TYPE_CHECKING:
    import logging

# * Benign errors are caught/recovered by safe_edit; we never ship them.
# * Log-noise patterns come from log_execution wrapping every handler.
_BENIGN_PATTERNS: tuple[str, ...] = (
    "message is not modified",
    "message to edit not found",
    "message to delete not found",
    "query is too old",
    "message is too old",
    "message can't be edited",
)

# * log_execution emits a per-handler exception summary of the form
# * "<action> raised after <delta>s: <type>". PTB's global error handler
# * then follows up with a richer report. The substring is a stable,
# * documented contract between the two paths (see decorators.py).
_LOG_NOISE_PATTERNS: tuple[str, ...] = (" raised after ",)

# * Owner-only errors: infra-level issues that should reach the owner
# * privately via DM, but must NOT be posted to the shared logs_errors
# * channel. Conflict arises when two bot instances poll simultaneously;
# * InvalidToken means the token was revoked or is wrong -- both are
# * operator concerns, not bugs the on-call moderator needs to see.
_OWNER_ONLY_TYPES: tuple[type[BaseException], ...] = (
    _te.Conflict,
    _te.InvalidToken,
)


def _benign(exc: BaseException | None) -> bool:
    """Return True when the exception is a recoverable, well-known no-op."""
    if exc is None:
        return False
    # * Shutdown cancellation is normal lifecycle, not a reportable error.
    if isinstance(exc, asyncio.CancelledError):
        return True
    msg = str(exc).lower()
    return any(p in msg for p in _BENIGN_PATTERNS)


def _log_noise(record: logging.LogRecord | None) -> bool:
    """Return True when the log record duplicates info already reported elsewhere."""
    if record is None:
        return False
    msg = record.getMessage()
    return any(p in msg for p in _LOG_NOISE_PATTERNS)


def _owner_only(exc: BaseException | None) -> bool:
    """Return True when the error is an infra/operator issue that goes to owner DM only."""
    if exc is None:
        return False
    return isinstance(exc, _OWNER_ONLY_TYPES)


_ACTION_HINTS: tuple[tuple[str, str], ...] = (
    ("[DB]", "Check MongoDB reachability and credentials, then retry the action."),
    ("Rate Limit", "Telegram asked to slow down; no action needed unless it persists."),
    ("Timed Out", "Transient Telegram hiccup; retry the action."),
    ("Polling Conflict", "Two bot instances are polling; stop the duplicate."),
    ("Invalid Token", "Token revoked or wrong; update BOT_TOKEN and restart."),
    ("Forbidden", "Bot lacks admin rights in the target chat; re-promote it."),
    ("Bad Request", "Check the reported call arguments for a bad ID or text."),
    ("Network", "Transient connectivity issue; retry the action."),
    ("Timeout", "Operation exceeded its deadline; retry the action."),
    ("Code Bug", "Needs a code fix; see the traceback below."),
)


def _action_hint(label: str) -> str:
    """Return the operator action line matching a classify label."""
    for marker, hint in _ACTION_HINTS:
        if marker in label:
            return hint
    return "Needs a code fix; see the traceback below."


def _classify(exc: BaseException | None) -> str:
    """Return a human-readable label tag for the exception."""
    if exc is None:
        return "[?] Unknown"

    # * Specific Telegram error subclasses first; BadRequest inherits NetworkError.
    if isinstance(exc, _te.RetryAfter):
        return "[~] Rate Limit: Flood Wait"
    if isinstance(exc, _te.TimedOut):
        return "[~] Telegram Timed Out"
    if isinstance(exc, _te.Conflict):
        return "[~] Polling Conflict"
    if isinstance(exc, _te.BadRequest):
        return "[!] Telegram Bad Request"
    if isinstance(exc, _te.Forbidden):
        return "[!] Telegram Forbidden"
    if isinstance(exc, _te.InvalidToken):
        return "[!] Telegram Invalid Token"
    if isinstance(exc, _te.NetworkError):
        return "[~] Telegram Network Error"
    if isinstance(exc, _te.TelegramError):
        return "[!] Telegram API Error"

    mod = type(exc).__module__ or ""
    if any(x in mod for x in ("motor", "pymongo", "mongo")):
        return "[DB] Database Error"

    if isinstance(exc, asyncio.TimeoutError):
        return "[~] Async Timeout"
    if isinstance(exc, asyncio.CancelledError):
        return "[-] Task Cancelled"

    if isinstance(exc, (ConnectionError, TimeoutError, OSError)) or any(
        x in mod for x in ("httpx", "aiohttp", "urllib3", "ssl")
    ):
        return "[~] Network / Server Error"

    return "[!] Code Bug"
