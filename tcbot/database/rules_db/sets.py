# © Copyright 2024 - 2026 Transsion Core
# © Copyright 2024 - 2026 Dizzy
# © Copyright 2026 Ave Labs

"""Community rule set lookup and creation."""

from __future__ import annotations

from typing import Any

from sqlalchemy import select

from tcbot.database.base import rule_categories, rule_sets
from tcbot.database.engine import db_call, fetch_all, fetch_one, run, run_returning
from tcbot.utils.time_and_date import utc_now

COMMUNITY_KEY = "community"
WORKING_LOCALE = "en-US"

# * A new community starts with a small, editable catalogue. Staff can rename,
# * reorder, retire, and add categories; the defaults are content, not policy.
DEFAULT_CATEGORIES: tuple[tuple[str, str], ...] = (
    ("conduct", "Conduct"),
    ("spam", "Spam and Advertising"),
    ("content", "Content"),
    ("safety", "Safety"),
    ("other", "Other"),
)


async def get_or_create_community_set() -> dict[str, Any]:
    """Return the single active community set, creating it when missing."""
    row = await db_call(
        lambda: fetch_one(
            select(rule_sets).where(rule_sets.c.scope_type == COMMUNITY_KEY)
        )
    )
    if row is not None:
        return dict(row)
    created = await db_call(
        lambda: run_returning(
            rule_sets.insert()
            .values(
                scope_type=COMMUNITY_KEY,
                rule_set_key="community",
                name="Community Rules",
                is_active=True,
                requires_acknowledgement=False,
                created_at=utc_now(),
                updated_at=utc_now(),
            )
            .returning(rule_sets)
        )
    )
    rule_set = dict(created[0])
    set_id = int(rule_set["id"])
    await db_call(
        lambda: fetch_all(
            rule_categories.insert()
            .values(
                [
                    {
                        "rule_set_id": set_id,
                        "category_key": key,
                        "title": title,
                        "sort_order": index * 10,
                        "is_active": True,
                        "created_at": utc_now(),
                        "updated_at": utc_now(),
                    }
                    for index, (key, title) in enumerate(DEFAULT_CATEGORIES, start=1)
                ]
            )
            .returning(rule_categories.c.id)
        )
    )
    return rule_set


async def get_community_set() -> dict[str, Any] | None:
    """Return the community set without creating one."""
    row = await db_call(
        lambda: fetch_one(
            select(rule_sets).where(rule_sets.c.scope_type == COMMUNITY_KEY)
        )
    )
    return dict(row) if row is not None else None


async def set_acknowledgement(set_id: int, *, enabled: bool) -> None:
    """Toggle whether a public version requires an acknowledgement."""
    await db_call(
        lambda: run(
            rule_sets.update()
            .where(rule_sets.c.id == set_id)
            .values(requires_acknowledgement=enabled, updated_at=utc_now())
        )
    )
