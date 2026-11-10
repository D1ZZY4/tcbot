# © Copyright 2024 - 2026 Transsion Core
# © Copyright 2024 - 2026 Dizzy
# © Copyright 2026 Ave Labs

"""Central time and date helpers: UTC storage, display, and measurement."""

from __future__ import annotations

import re
import time
from datetime import UTC, datetime, timedelta

from tcbot.utils.formatter import esc
from tcbot.utils.i18n import t

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


# ────────────────────── Duration Helpers ──────────────────────────── #

_DURATION_RE = re.compile(r"^(\d+)(ye|mo|[smhdw])$", re.IGNORECASE)
_SECS_PER_HOUR: int = 3_600
_SECS_PER_DAY: int = 86_400
_DAYS_PER_YEAR: int = 365
_MAX_DURATION_DAYS: int = 36500


def parse_duration(raw: str) -> timedelta | None:
    """Parse a duration token like '3d', '1mo', '2ye'. None if invalid."""
    m = _DURATION_RE.match(raw.strip())
    if not m:
        return None
    value = int(m.group(1))
    if value <= 0:
        # * timedelta(0) is falsy; a "0s" token must be invalid, never
        # * permanent (None would disable expiry on mute expiry paths).
        return None
    unit = m.group(2).lower()
    try:
        result = {
            "s": timedelta(seconds=value),
            "m": timedelta(minutes=value),
            "h": timedelta(hours=value),
            "d": timedelta(days=value),
            "w": timedelta(weeks=value),
            "mo": timedelta(days=value * 30),
            "ye": timedelta(days=value * _DAYS_PER_YEAR),
        }.get(unit)
    except OverflowError:
        return None
    if result is None or result.days > _MAX_DURATION_DAYS:
        return None
    return result


def fmt_duration(td: timedelta | None, locale: str | None = None) -> str:
    """Human-readable duration string for replies."""
    if td is None:
        return t("muting.duration.permanent", locale, plain=True)
    total = int(td.total_seconds())
    if total < 60:
        return f"{total}s"
    if total < _SECS_PER_HOUR:
        return f"{total // 60}m"
    if total < _SECS_PER_DAY:
        return f"{total // _SECS_PER_HOUR}h"
    days = total // _SECS_PER_DAY
    if days < 7:
        return f"{days}d"
    if days < 30:
        return f"{days // 7}w"
    if days < _DAYS_PER_YEAR:
        return f"{days // 30}mo"
    return f"{days // _DAYS_PER_YEAR}ye"


def date_or_unknown(value: datetime | None, locale: str | None = None) -> str:
    """Format a datetime field or a localized Unknown fallback if missing."""
    return (
        fmt_dt(value) if value else t("common.action.unknown_date", locale, plain=True)
    )
