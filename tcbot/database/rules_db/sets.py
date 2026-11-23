# © Copyright 2024 - 2026 Transsion Core
# © Copyright 2024 - 2026 Dizzy
# © Copyright 2026 Ave Labs

"""Community rule set lookup and creation."""

from __future__ import annotations

from typing import Any

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from tcbot.database.base import rule_categories, rule_sets
from tcbot.database.engine import db_call, fetch_all, fetch_one, run_transaction
from tcbot.utils.time_and_date import utc_now

COMMUNITY_KEY = "community"
WORKING_LOCALE = "en-US"

# * A new community starts with a small, editable catalogue. Staff can rename,
# * reorder, retire, and add categories; the defaults are content, not policy.
DEFAULT_CATEGORIES: tuple[tuple[str, str], ...] = (
    ("mandatory", "Mandatory"),
    ("optional", "Optional"),
)


async def _seed_default_categories(sess: AsyncSession, set_id: int, now: Any) -> None:
    """Insert the default catalogue for a set that has no categories yet."""
    await sess.execute(
        rule_categories.insert().values(
            [
                {
                    "rule_set_id": set_id,
                    "category_key": key,
                    "title": title,
                    "sort_order": index * 10,
                    "is_active": True,
                    "created_at": now,
                    "updated_at": now,
                }
                for index, (key, title) in enumerate(DEFAULT_CATEGORIES, start=1)
            ]
        )
    )


async def get_or_create_community_set() -> dict[str, Any]:
    """Return the single active community set, creating it when missing.

    A set left behind by an older, non-atomic creation path can exist without
    its catalogue. Backfill it here so the read surfaces never receive items
    that no category can group.
    """
    row = await db_call(
        lambda: fetch_one(
            select(rule_sets).where(rule_sets.c.scope_type == COMMUNITY_KEY)
        )
    )
    if row is not None:
        rule_set = dict(row)
        set_id = int(rule_set["id"])
        existing = await db_call(
            lambda: fetch_all(
                select(rule_categories.c.id).where(
                    rule_categories.c.rule_set_id == set_id
                )
            )
        )
        if not existing:
            now = utc_now()
            await run_transaction(
                lambda sess: _seed_default_categories(sess, set_id, now)
            )
        return rule_set
    now = utc_now()

    async def _create(sess: AsyncSession) -> dict[str, Any]:
        created = (
            (
                await sess.execute(
                    rule_sets.insert()
                    .values(
                        scope_type=COMMUNITY_KEY,
                        rule_set_key="community",
                        name="Community Rules",
                        is_active=True,
                        requires_acknowledgement=False,
                        created_at=now,
                        updated_at=now,
                    )
                    .returning(rule_sets)
                )
            )
            .mappings()
            .first()
        )
        if created is None:
            raise RuntimeError("Community rule set insert returned no row.")
        rule_set = dict(created)
        set_id = int(rule_set["id"])
        # * The set and its default catalogue must land together.
        await _seed_default_categories(sess, set_id, now)
        return rule_set

    return await run_transaction(_create)
