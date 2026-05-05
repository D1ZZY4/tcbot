# © Copyright 2024 - 2026 Transsion Core
# © Copyright 2024 - 2026 Dizzy
# © Copyright 2026 Aveum Apps
## Datetime formatting helpers – all timestamps use UTC and DD-MM-YYYY | HH:MM format
from __future__ import annotations

from datetime import datetime, timezone


def utc_now() -> datetime:
    return datetime.now(timezone.utc)


def fmt_dt(dt: datetime) -> str:
    """Format a datetime as DD-MM-YYYY | HH:MM (UTC)."""
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    return dt.strftime("%d-%m-%Y | %H:%M")


def utc_now_str() -> str:
    return fmt_dt(datetime.now(timezone.utc))
