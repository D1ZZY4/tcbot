# © Copyright 2024 - 2026 Transsion Core
# © Copyright 2024 - 2026 Dizzy
# © Copyright 2026 Ave Labs

"""Draft rule item CRUD."""

from __future__ import annotations

import re
from typing import Any

from sqlalchemy import func, select

from tcbot.database.base import (
    rule_categories,
    rule_items,
    rule_set_versions,
)
from tcbot.database.engine import db_call, fetch_all, fetch_one, run, run_returning
from tcbot.utils.time_and_date import utc_now


async def list_items(
    version_id: int, category_key: str | None = None
) -> list[dict[str, Any]]:
    """Return items in display order, optionally limited to one category."""
    stmt = select(rule_items).where(rule_items.c.rule_set_version_id == version_id)
    if category_key is not None:
        stmt = stmt.where(rule_items.c.category_key == category_key)
    stmt = stmt.order_by(
        rule_items.c.category_sort_order,
        rule_items.c.category_key,
        rule_items.c.sort_order,
        rule_items.c.id,
    )
    rows = await db_call(lambda: fetch_all(stmt))
    return [dict(row) for row in rows]


async def _set_id(version_id: int) -> int:
    """Return the rule set a version belongs to."""
    row = await db_call(
        lambda: fetch_one(
            select(rule_set_versions.c.rule_set_id).where(
                rule_set_versions.c.id == version_id
            )
        )
    )
    if row is None:
        raise ValueError(f"Unknown rule version {version_id}")
    return int(row["rule_set_id"])


async def _snapshot(version_id: int, category_key: str) -> tuple[str, int]:
    """Return the category title and order to snapshot into a new item."""
    set_id = await _set_id(version_id)
    row = await db_call(
        lambda: fetch_one(
            select(rule_categories.c.title, rule_categories.c.sort_order).where(
                rule_categories.c.rule_set_id == set_id,
                rule_categories.c.category_key == category_key,
            )
        )
    )
    if row is None:
        return category_key, 100
    return str(row["title"]), int(row["sort_order"])


def _rule_key(title: str) -> str:
    return re.sub(r"[^a-z0-9]+", "-", title.lower()).strip("-")[:50] or "rule"


async def add_item(
    version_id: int,
    category_key: str,
    title: str,
    body: str,
    reference_url: str | None = None,
) -> dict[str, Any]:
    """Append an item to the draft with the current category snapshot."""
    category_title, category_order = await _snapshot(version_id, category_key)
    count_row = await db_call(
        lambda: fetch_one(
            select(func.count().label("count"))
            .select_from(rule_items)
            .where(rule_items.c.rule_set_version_id == version_id)
        )
    )
    order = int(count_row["count"] if count_row else 0) + 1
    base_key = _rule_key(title)
    key = base_key
    suffix = 2
    while (
        await db_call(
            lambda candidate=key: fetch_one(
                select(rule_items.c.id).where(
                    rule_items.c.rule_set_version_id == version_id,
                    rule_items.c.rule_key == candidate,
                )
            )
        )
        is not None
    ):
        key = f"{base_key}-{suffix}"
        suffix += 1
    created = await db_call(
        lambda: run_returning(
            rule_items.insert()
            .values(
                rule_set_version_id=version_id,
                rule_key=key,
                category_key=category_key,
                category_title=category_title,
                category_sort_order=category_order,
                title=title,
                body=body,
                content_format="plain_text",
                sort_order=order,
                is_mandatory=True,
                reference_url=reference_url,
                created_at=utc_now(),
            )
            .returning(rule_items)
        )
    )
    return dict(created[0])


async def delete_item(version_id: int, item_id: int) -> bool:
    """Delete one draft item; published items are refused by the schema."""
    affected = await db_call(
        lambda: run(
            rule_items.delete().where(
                rule_items.c.id == item_id,
                rule_items.c.rule_set_version_id == version_id,
            )
        )
    )
    return affected > 0
