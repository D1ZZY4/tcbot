# © Copyright 2024 - 2026 Transsion Core
# © Copyright 2024 - 2026 Dizzy
# © Copyright 2026 Ave Labs

"""Central time and date helpers: UTC storage, display, and measurement.

Single source of truth for every clock read in the bot. Wall-clock helpers
(``utc_now``, ``from_timestamp``, ``fmt_dt``) are for stored and displayed
timestamps. Monotonic helpers (``monotonic``, ``elapsed_ms``) are for
measuring durations, timeouts, and rate-limit windows; never mix them with
wall-clock values. The one exception is Redis-backed rate limiting, which
needs wall-clock ``time.time()`` scores shared across processes.
"""

from __future__ import annotations

import time
from datetime import UTC, datetime

from tcbot.utils.formatter import esc

# ──────────────────────── Datetime Helpers ──────────────────────── #


def utc_now() -> datetime:
    """Return the current UTC datetime (tz-aware)."""
    return datetime.now(UTC)


def to_utc(dt: datetime) -> datetime:
    """Normalise dt to UTC; naive datetimes are assumed UTC."""
    if dt.tzinfo is None:
        return dt.replace(tzinfo=UTC)
    return dt.astimezone(UTC)


def fmt_dt(dt: datetime) -> str:
    """Format dt as DD-MM-YYYY | HH:MM in UTC, escaped for MarkdownV2 text.

    Every caller embeds the result in a MarkdownV2 message, so the
    ``-`` and ``|`` separators come back pre-escaped from this single
    source instead of at each call site.
    """
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=UTC)
    return esc(dt.strftime("%d-%m-%Y | %H:%M"))


def utc_now_str() -> str:
    """Return the current UTC time formatted for user-visible display."""
    return fmt_dt(utc_now())


def from_timestamp(ts: float) -> datetime:
    """Convert a POSIX timestamp (e.g. ``LogRecord.created``) to aware UTC."""
    return datetime.fromtimestamp(ts, tz=UTC)


# ──────────────────────── Measurement Helpers ──────────────────────── #


# * Standard budget for a single Telegram lookup (get_chat, get_chat_member).
# * Previously triplicated as ``_TG_TIMEOUT`` across group-flow modules.
TELEGRAM_LOOKUP_TIMEOUT: float = 3.0


def monotonic() -> float:
    """Return the monotonic clock in seconds, for measuring durations."""
    return time.monotonic()


def elapsed_ms(start: float) -> float:
    """Return milliseconds elapsed since a ``monotonic()`` reading."""
    return (time.monotonic() - start) * 1_000
