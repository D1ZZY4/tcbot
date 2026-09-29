# © Copyright 2024 - 2026 Transsion Core
# © Copyright 2024 - 2026 Dizzy
# © Copyright 2026 Ave Labs

"""Mute duration parsing and formatting."""

from __future__ import annotations

import re
from datetime import timedelta

from tcbot.utils.i18n import t

_DURATION_RE = re.compile(r"^(\d+)(ye|mo|[smhdw])$", re.IGNORECASE)

_SECS_PER_HOUR: int = 3_600
_SECS_PER_DAY: int = 86_400
_DAYS_PER_YEAR: int = 365
# * Upper bound for an accepted duration (100 years in days). Larger inputs
# * would overflow timedelta construction or the utc_now() + duration date
# * math, crashing the command on malicious input such as 9999999999ye.
# * Rejected values return None so the token falls back to reason text.
# * All documented examples (up to 2ye) are far below this cap.
_MAX_DURATION_DAYS: int = 36500


def parse_duration(raw: str) -> timedelta | None:
    """Parse a single duration token like '3d', '1mo', '2ye'. Returns None if invalid."""
    m = _DURATION_RE.match(raw.strip())
    if not m:
        return None
    value = int(m.group(1))
    unit = m.group(2).lower()
    try:
        mapping = {
            "s": timedelta(seconds=value),
            "m": timedelta(minutes=value),
            "h": timedelta(hours=value),
            "d": timedelta(days=value),
            "w": timedelta(weeks=value),
            "mo": timedelta(days=value * 30),
            "ye": timedelta(days=value * _DAYS_PER_YEAR),
        }
        result = mapping.get(unit)
    except OverflowError:
        return None
    if result is None or result.days > _MAX_DURATION_DAYS:
        return None
    return result


def fmt_duration(td: timedelta | None, locale: str | None = None) -> str:
    """Human-readable duration string for use in replies."""
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
