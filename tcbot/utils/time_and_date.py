# © Copyright 2024 - 2026 Transsion Core
# © Copyright 2024 - 2026 Dizzy
# © Copyright 2026 Ave Labs

"""Central time and date helpers: UTC storage, display, and measurement."""

from __future__ import annotations

import re
import time
from datetime import UTC, datetime, timedelta

from tcbot.utils.i18n import esc, t

# ──────────────────────── Datetime Helpers ──────────────────────── #


def utc_now() -> datetime:
    """Return the current UTC datetime (tz-aware)."""
    return datetime.now(UTC)


def to_utc(dt: datetime) -> datetime:
    """Normalise dt to UTC; naive datetimes are assumed UTC."""
    if dt.tzinfo is None:
        return dt.replace(tzinfo=UTC)
    return dt.astimezone(UTC)


def fmt_date(dt: datetime) -> str:
    """Format the calendar date of dt as DD-MM-YYYY in UTC."""
    u = to_utc(dt)
    return f"{u.day:02d}-{u.month:02d}-{u.year:04d}"


def fmt_time(dt: datetime) -> str:
    """Format the clock time of dt as HH:MM in UTC."""
    u = to_utc(dt)
    return f"{u.hour:02d}:{u.minute:02d}"


def fmt_dt_raw(dt: datetime) -> str:
    """Format dt as DD-MM-YYYY | HH:MM in UTC (legacy combined form).

    Kept for the rules publication content hash, where the two values appear
    as one string in a version footer. Display surfaces use fmt_date and
    fmt_time separately.
    """
    u = to_utc(dt)
    return f"{u.day:02d}-{u.month:02d}-{u.year:04d} | {u.hour:02d}:{u.minute:02d}"


def fmt_dt(dt: datetime) -> str:
    """Format dt as an escaped combined date and time for upgrade compat."""
    return esc(fmt_dt_raw(dt))


# ──────────────────────── Measurement Helpers ──────────────────────── #


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
_DAYS_PER_MONTH: int = 30
# * Telegram treats any restriction longer than 366 days as indefinite. A
# * finite stored expiry beyond that point would disagree with the actual
# * Telegram state, so the parser rejects the token instead of accepting a
# * mute the expiry sweep could never end. Omit the duration for a permanent
# * mute.
_MAX_DURATION_DAYS: int = 366
# * Telegram treats a restriction shorter than 30 seconds as permanent. A
# * 60-second floor keeps the stored expiry and the actual Telegram state in
# * agreement even after API-call latency.
_MIN_TELEGRAM_RESTRICTION_SECONDS: int = 60

# * Seconds in one unit of each accepted suffix. A dict lookup keeps the
# * conversion to the requested unit only: building every unit eagerly
# * overflowed ``timedelta`` for the year form and rejected a second-based
# * token that was still inside the documented cap.
_DURATION_UNIT_SECONDS: dict[str, int] = {
    "s": 1,
    "m": 60,
    "h": _SECS_PER_HOUR,
    "d": _SECS_PER_DAY,
    "w": 7 * _SECS_PER_DAY,
    "mo": _DAYS_PER_MONTH * _SECS_PER_DAY,
    "ye": _DAYS_PER_YEAR * _SECS_PER_DAY,
}


_MIN_RESTRICTION_TD = timedelta(seconds=_MIN_TELEGRAM_RESTRICTION_SECONDS)
_MAX_DURATION_SECONDS_EXCL = (_MAX_DURATION_DAYS + 1) * _SECS_PER_DAY


def parse_duration(raw: str) -> timedelta | None:
    """Parse a duration token like '3d', '1mo', '2ye'. None if invalid."""
    m = _DURATION_RE.match(raw.strip())
    if not m:
        return None
    try:
        value = int(m.group(1))
    except ValueError:
        # * Python caps int(str) at 4300 digits; a longer token is simply an
        # * invalid duration, not a reason to abort the whole command.
        return None
    if value <= 0:
        # * timedelta(0) is falsy; a "0s" token must be invalid, never
        # * permanent (None would disable expiry on mute expiry paths).
        return None
    unit_seconds = _DURATION_UNIT_SECONDS.get(m.group(2).lower())
    if unit_seconds is None:
        return None
    total_seconds = value * unit_seconds
    if total_seconds >= _MAX_DURATION_SECONDS_EXCL:
        return None
    if total_seconds < _MIN_TELEGRAM_RESTRICTION_SECONDS:
        return _MIN_RESTRICTION_TD
    try:
        return timedelta(seconds=total_seconds)
    except OverflowError:
        return None


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
    """Format the calendar date or a localized Unknown fallback if missing."""
    return (
        fmt_date(value)
        if value
        else t("common.action.unknown_date", locale, plain=True)
    )


def time_or_unknown(value: datetime | None, locale: str | None = None) -> str:
    """Format the clock time or a localized Unknown fallback if missing."""
    return (
        fmt_time(value)
        if value
        else t("common.action.unknown_date", locale, plain=True)
    )
