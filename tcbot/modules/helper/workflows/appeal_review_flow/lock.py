# © Copyright 2024 - 2026 Transsion Core
# © Copyright 2024 - 2026 Dizzy
# © Copyright 2026 Ave Labs

"""Review lock window for appeal decisions."""

from __future__ import annotations

from datetime import datetime, timedelta

from tcbot.utils.time_and_date import to_utc, utc_now

LOCK_HOURS: int = 12
_LOCK_WINDOW = timedelta(hours=LOCK_HOURS)

# * Appeal review prose lives in appeals.toml [review]/[decision];
# * only the lock-window tunable stays in code.


def reviewer_locked_out(
    review_timestamp: datetime | None,
    ban_admin_id: int | None,
    reviewer_id: int,
) -> bool:
    """Check whether reviewer_id is blocked from reviewing within the lock window."""
    # * A missing or zero ban_admin_id means the ban owner is unknown
    # * (legacy record): fail open with no lock, matching the documented
    # * contract. Failing closed here would lock out every reviewer for
    # * 12 hours with nobody able to act.
    if review_timestamp is None or not ban_admin_id:
        return False
    if reviewer_id == ban_admin_id:
        return False
    elapsed = utc_now() - to_utc(review_timestamp)
    return elapsed < _LOCK_WINDOW
