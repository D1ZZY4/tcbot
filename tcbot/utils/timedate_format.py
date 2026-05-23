# © Copyright 2024 - 2026 Transsion Core
# © Copyright 2024 - 2026 Dizzy
# © Copyright 2026 Aveum Apps

"""Datetime helpers – UTC storage and DD-MM-YYYY | HH:MM display."""

from __future__ import annotations

from datetime import datetime, timezone

# ──────────────────────── Datetime Helpers ──────────────────────── #


def utc_now() -> datetime:
    """Return the current UTC datetime (tz-aware)."""
    return datetime.now(timezone.utc)


def to_utc(dt: datetime) -> datetime:
    """Normalise dt to UTC; naive datetimes are assumed UTC."""
    if dt.tzinfo is None:
        return dt.replace(tzinfo=timezone.utc)
    return dt.astimezone(timezone.utc)


def fmt_dt(dt: datetime) -> str:
    """Format dt as DD-MM-YYYY | HH:MM in UTC."""
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    return dt.strftime("%d-%m-%Y | %H:%M")


def utc_now_str() -> str:
    """Return the current UTC time as a formatted string."""
    return fmt_dt(utc_now())
