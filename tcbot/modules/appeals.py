# © Copyright 2024 - 2026 Transsion Core
# © Copyright 2024 - 2026 Dizzy
# © Copyright 2026 Aveum Apps
"""Pure functions for appeal logic – no Telegram I/O, fully unit-testable."""
from __future__ import annotations

import re
from datetime import datetime, timedelta

from tcbot.modules.helper.parse_link import utcnow

_LOCK_WINDOW = timedelta(hours=12)


def starts_with_appeal_tag(text: str) -> bool:
    """Return True when text (stripped) starts with #appeal (case-insensitive)."""
    return text.strip().lower().startswith("#appeal")


def text_references_log_message(text: str, msg_id: int) -> bool:
    """Return True when text contains msg_id as a standalone integer token."""
    return bool(re.search(rf"\b{msg_id}\b", text))


def reviewer_locked_out(
    review_timestamp: datetime | None,
    ban_admin_id: int | None,
    reviewer_id: int,
) -> bool:
    """Check whether reviewer_id is blocked from reviewing within the lock window.

    Returns False immediately when metadata is absent or reviewer is the
    original banning admin (they may always review their own bans).
    Returns True only if elapsed < LOCK_WINDOW and reviewer is a different admin.
    """
    if review_timestamp is None or ban_admin_id is None:
        return False
    if reviewer_id == ban_admin_id:
        return False
    ts = review_timestamp
    if hasattr(ts, "tzinfo") and ts.tzinfo is not None:
        ts = ts.replace(tzinfo=None)
    elapsed = utcnow() - ts
    return elapsed < _LOCK_WINDOW


def now() -> "datetime":
    """Return the current UTC datetime (alias for utcnow, patchable in tests)."""
    return utcnow()

