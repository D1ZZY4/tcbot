# © Copyright 2024 - 2026 Transsion Core
# © Copyright 2024 - 2026 Dizzy
# © Copyright 2026 Ave Labs

"""Category catalogue of a rule set."""

from __future__ import annotations

import re
from typing import Any

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from tcbot.database.base import rule_categories, rule_items, rule_set_versions
from tcbot.database.engine import (
    db_call,
    fetch_all,
    fetch_one,
    run,
    run_returning,
    run_transaction,
    session,
)
from tcbot.utils.time_and_date import utc_now


async def list_categories(
    set_id: int, *, active_only: bool = False
) -> list[dict[str, Any]]:
    """Return the categories of a set in display order."""
    stmt = select(rule_categories).where(rule_categories.c.rule_set_id == set_id)
    if active_only:
        stmt = stmt.where(rule_categories.c.is_active.is_(True))
    stmt = stmt.order_by(rule_categories.c.sort_order, rule_categories.c.id)
    rows = await db_call(lambda: fetch_all(stmt))
    return [dict(row) for row in rows]


# * The key is embedded in "rules_cat_rename:<key>" callback data, which
# * Telegram caps at 64 bytes. Leave room for the prefix and a numeric
# * collision suffix so a long title cannot break the editor keyboard.
_KEY_MAX = 40


def _available_key(title: str, existing: set[str]) -> str:
    """Return a slug that does not collide with an existing category."""
    base = re.sub(r"[^a-z0-9]+", "-", title.strip().lower()).strip("-")[:_KEY_MAX]
    # * A title with no ASCII alphanumerics collapses to an empty base. Build
    # * collision suffixes from the fallback stem so the key still satisfies
    # * the DB check constraint instead of producing an invalid "-2".
    stem = base or "category"
    key = stem
    suffix = 2
    while key in existing:
        key = f"{stem}-{suffix}"
        suffix += 1
    return key


async def add_category(set_id: int, key: str, title: str) -> dict[str, Any]:
    """Add a category, resolving a slug collision with a numeric suffix."""
    rows = await list_categories(set_id)
    used = {str(row["category_key"]) for row in rows}
    final_key = key if key not in used else _available_key(title, used)
    next_order = max((int(row["sort_order"]) for row in rows), default=0) + 10
    created = await db_call(
        lambda: run_returning(
            rule_categories.insert()
            .values(
                rule_set_id=set_id,
                category_key=final_key,
                title=title,
                sort_order=next_order,
                is_active=True,
                created_at=utc_now(),
                updated_at=utc_now(),
            )
            .returning(rule_categories)
        )
    )
    return dict(created[0])


async def set_category_description(
    set_id: int, category_key: str, description: str
) -> None:
    """Store the introductory text of one category for its editor panel."""
    await db_call(
        lambda: run(
            rule_categories.update()
            .where(
                rule_categories.c.rule_set_id == set_id,
                rule_categories.c.category_key == category_key,
            )
            .values(description=description)
        )
    )


async def rename_category(set_id: int, category_key: str, title: str) -> None:
    """Rename a category and refresh the snapshot of its draft items."""

    async def _work(sess: AsyncSession) -> None:
        await sess.execute(
            rule_categories.update()
            .where(
                rule_categories.c.rule_set_id == set_id,
                rule_categories.c.category_key == category_key,
            )
            .values(title=title, updated_at=utc_now())
        )
        await sess.execute(
            rule_items.update()
            .where(
                rule_items.c.category_key == category_key,
                rule_items.c.rule_set_version_id.in_(
                    select(rule_set_versions.c.id).where(
                        rule_set_versions.c.rule_set_id == set_id,
                        rule_set_versions.c.status == "draft",
                    )
                ),
            )
            .values(category_title=title)
        )

    await run_transaction(_work)


async def delete_category(set_id: int, category_key: str) -> bool:
    """Remove an empty category; a category with draft items is kept."""
    count = await db_call(
        lambda: fetch_one(
            select(func.count().label("count"))
            .select_from(rule_items)
            .where(
                rule_items.c.category_key == category_key,
                rule_items.c.rule_set_version_id.in_(
                    select(rule_set_versions.c.id).where(
                        rule_set_versions.c.rule_set_id == set_id,
                        rule_set_versions.c.status == "draft",
                    )
                ),
            )
        )
    )
    if int(count["count"] if count else 0) > 0:
        return False
    affected = await db_call(
        lambda: run(
            rule_categories.delete().where(
                rule_categories.c.rule_set_id == set_id,
                rule_categories.c.category_key == category_key,
            )
        )
    )
    return affected > 0


async def move_category(set_id: int, category_key: str, delta: int) -> None:
    """Move a category one position up or down in the display order."""
    rows = await list_categories(set_id)
    index = next(
        (i for i, row in enumerate(rows) if row["category_key"] == category_key), -1
    )
    other = index + (-1 if delta < 0 else 1)
    if index < 0 or other < 0 or other >= len(rows):
        return
    current, neighbour = rows[index], rows[other]

    async with session() as sess:
        await sess.execute(
            rule_categories.update()
            .where(rule_categories.c.id == current["id"])
            .values(sort_order=neighbour["sort_order"], updated_at=utc_now())
        )
        await sess.execute(
            rule_categories.update()
            .where(rule_categories.c.id == neighbour["id"])
            .values(sort_order=current["sort_order"], updated_at=utc_now())
        )
