# © Copyright 2024 - 2026 Transsion Core
# © Copyright 2024 - 2026 Dizzy
# © Copyright 2026 Ave Labs

"""Validation gates and tunables for appeal submission."""

from __future__ import annotations

import re
from datetime import datetime, timedelta

from tcbot.utils.time_and_date import to_utc, utc_now

WAITING_APPEAL = 0

# * Maximum character length for an appeal message.
_MAX_APPEAL_LEN: int = 2000
_STALE_REVIEW_HOURS: int = 72
_STALE_REVIEW_WINDOW = timedelta(hours=_STALE_REVIEW_HOURS)
_REJECTION_COOLDOWN_HOURS: int = 24
_REJECTION_COOLDOWN = timedelta(hours=_REJECTION_COOLDOWN_HOURS)
_SECONDS_PER_HOUR: int = 3600

_ID_RE = re.compile(r"^/start\s+appeal_([a-z0-9]{10})$")

# * Appeal runtime prose lives in appeals.toml [submit]/[instruction];
# * only numeric tunables stay in code.


# ─────────────────────── Appeal pure helpers ────────────────────── #


def starts_with_appeal_tag(text: str) -> bool:
    """Return True when text (stripped) starts with #appeal (case-insensitive)."""
    return text.strip().lower().startswith("#appeal")


def text_references_log_message(text: str, msg_id: int) -> bool:
    """Return True when text contains msg_id as a standalone integer token."""
    return bool(re.search(rf"\b{msg_id}\b", text))


# * Conversation keys shared by every appeal exit path. One tuple so a
# * future key cannot be cleared in _start and leak in _on_message.
_APPEAL_STATE_KEYS: tuple[str, ...] = (
    "appeal_ban_id",
    "appeal_log_msg_id",
    "appeal_instruction_msg_id",
)


def _clear_appeal_state(user_data: dict[str, object] | None) -> None:
    """Remove appeal conversation keys so retries start clean."""
    if not user_data:
        return
    for key in _APPEAL_STATE_KEYS:
        user_data.pop(key, None)


def _is_stale_review(review_ts: datetime | None) -> bool:
    """Return True when a stored review no longer blocks a new appeal."""
    return review_ts is None or (to_utc(review_ts) < utc_now() - _STALE_REVIEW_WINDOW)


def _cooldown_remaining_h(rejected_at: datetime | None) -> int | None:
    """Return remaining whole hours rounded up inside the rejection cooldown, else None."""
    if rejected_at is None:
        return None
    elapsed = utc_now() - to_utc(rejected_at)
    if elapsed < timedelta(0):
        elapsed = timedelta(0)
    if elapsed >= _REJECTION_COOLDOWN:
        return None
    # * Round up so a fresh rejection shows the full window (24, not 25)
    # * and a nearly-expired one still shows 1 instead of 0.
    total = int((_REJECTION_COOLDOWN - elapsed).total_seconds())
    return (total + _SECONDS_PER_HOUR - 1) // _SECONDS_PER_HOUR
