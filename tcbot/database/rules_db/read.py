# © Copyright 2024 - 2026 Transsion Core
# © Copyright 2024 - 2026 Dizzy
# © Copyright 2026 Ave Labs

"""Read surfaces for published rules and acknowledgements."""

from __future__ import annotations

from typing import Any

from sqlalchemy import func, select
from sqlalchemy.dialects.postgresql import insert as pg_insert

from tcbot.database.base import (
    rule_acknowledgements,
    rule_categories,
    rule_items,
    rule_set_versions,
    rule_sets,
)
from tcbot.database.engine import db_call, fetch_all, fetch_one
from tcbot.database.rules_db.sets import WORKING_LOCALE
from tcbot.utils.time_and_date import utc_now


async def published_rules(set_id: int | None = None) -> dict[str, Any] | None:
    """Return the active published version with its items and categories."""
    if set_id is None:
        set_row = await db_call(
            lambda: fetch_one(
                select(rule_sets.c.id).where(
                    rule_sets.c.scope_type == "community",
                    rule_sets.c.is_active.is_(True),
                )
            )
        )
        if set_row is None:
            return None
        set_id = int(set_row["id"])
    version = await db_call(
        lambda: fetch_one(
            select(rule_set_versions).where(
                rule_set_versions.c.rule_set_id == set_id,
                rule_set_versions.c.locale == WORKING_LOCALE,
                rule_set_versions.c.status == "published",
            )
        )
    )
    if version is None:
        return None
    items = await db_call(
        lambda: fetch_all(
            select(rule_items).where(rule_items.c.rule_set_version_id == version["id"])
        )
    )
    categories = await db_call(
        lambda: fetch_all(
            select(rule_categories).where(rule_categories.c.rule_set_id == set_id)
        )
    )
    set_doc = await db_call(
        lambda: fetch_one(select(rule_sets).where(rule_sets.c.id == set_id))
    )
    return {
        "set": dict(set_doc) if set_doc else {},
        "version": dict(version),
        "items": [dict(row) for row in items],
        "categories": [dict(row) for row in categories],
    }


async def acknowledgement_count(version_id: int) -> int:
    """Return how many users accepted one published version."""
    row = await db_call(
        lambda: fetch_one(
            select(func.count())
            .select_from(rule_acknowledgements)
            .where(rule_acknowledgements.c.rule_set_version_id == version_id)
        )
    )
    return int(row["count"] if row else 0)


async def has_acknowledged(version_id: int, user_id: int) -> bool:
    """Return whether one user already accepted this exact version."""
    row = await db_call(
        lambda: fetch_one(
            select(rule_acknowledgements.c.id).where(
                rule_acknowledgements.c.rule_set_version_id == version_id,
                rule_acknowledgements.c.user_id == user_id,
            )
        )
    )
    return row is not None


async def record_acknowledgement(
    version_id: int,
    user_id: int,
    context_chat_id: int | None,
    message_id: int | None,
) -> bool:
    """Insert one acknowledgement; duplicate taps are safe."""
    result = await db_call(
        lambda: fetch_all(
            pg_insert(rule_acknowledgements)
            .values(
                rule_set_version_id=version_id,
                user_id=user_id,
                context_chat_id=context_chat_id,
                acknowledgement_method="inline_button",
                telegram_message_id=message_id,
                acknowledged_at=utc_now(),
                metadata={"source": "greeting"},
            )
            .on_conflict_do_nothing(index_elements=["rule_set_version_id", "user_id"])
            .returning(rule_acknowledgements.c.id)
        )
    )
    return bool(result)
