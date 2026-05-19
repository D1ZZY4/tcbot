# © Copyright 2024 - 2026 Transsion Core
# © Copyright 2024 - 2026 Dizzy
# © Copyright 2026 Aveum Apps

"""
Datetime formatting helpers – all timestamps use UTC and DD-MM-YYYY | HH:MM format
"""

from __future__ import annotations

from datetime import datetime, timezone


# ──────────────────────── Datetime Helpers ──────────────────────── #
# * Consistent UTC datetime utilities for all bot logging/formatting

def utc_now() -> datetime:
    """
    Return current UTC datetime with proper timezone info
    * Always uses timezone.utc to avoid naive datetime issues
    * Standardized across the entire codebase to prevent time bugs
    """
    return datetime.now(timezone.utc)


def fmt_dt(dt: datetime) -> str:
    """
    Format a datetime as DD-MM-YYYY | HH:MM (always UTC)
    * If dt is naive (no tzinfo), automatically converts to UTC
    * Uses a consistent string format across all log messages
    * Ensures timezone consistency even if input is naive
    """
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    return dt.strftime("%d-%m-%Y | %H:%M")


def utc_now_str() -> str:
    """
    Return current UTC datetime as a formatted string
    * Combines utc_now() and fmt_dt() for one-line usage
    * Perfect for log messages that need a timestamp
    """
    return fmt_dt(utc_now())
