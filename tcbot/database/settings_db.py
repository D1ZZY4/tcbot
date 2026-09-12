# © Copyright 2024 - 2026 Transsion Core
# © Copyright 2024 - 2026 Dizzy
# © Copyright 2026 Ave Labs

"""Per-user settings collection helpers (locale preferences)."""

from __future__ import annotations

from typing import TYPE_CHECKING

from tcbot.database.mongos import col, db_call

if TYPE_CHECKING:
    from motor.motor_asyncio import AsyncIOMotorCollection

# ─────────────────────── Collection Helpers ─────────────────────── #


def _settings() -> AsyncIOMotorCollection:
    return col("user_settings")


# ──────────────────── User Locale Preferences ───────────────────── #
# * Stored apart from member_cache on purpose: locale rows must never
# * inflate the cached-user counts or appear in user listings, so a
# * bare {user_id, locale} document here is harmless while the same row
# * in member_cache would corrupt stats and search results.


async def get_user_locale(user_id: int) -> str | None:
    """Return the stored locale code for a user, or None when unset."""
    doc = await db_call(
        _settings().find_one({"user_id": user_id}, {"_id": 0, "locale": 1})
    )
    if not doc:
        return None
    locale = doc.get("locale")
    return locale if isinstance(locale, str) and locale else None


async def set_user_locale(user_id: int, locale: str | None) -> None:
    """Store a user locale, or clear it when ``locale`` is None.

    Clearing deletes the row so the collection holds only users with an
    explicit preference. Locale codes are stored verbatim; validity
    against the translation catalog is enforced by the caller (command
    layer) and defensively at resolution time.
    """
    if locale is None:
        await db_call(_settings().delete_one({"user_id": user_id}))
        return
    await db_call(
        _settings().update_one(
            {"user_id": user_id},
            {"$set": {"user_id": user_id, "locale": locale}},
            upsert=True,
        )
    )
