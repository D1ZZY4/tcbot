# © Copyright 2024 - 2026 Transsion Core
# © Copyright 2024 - 2026 Dizzy
# © Copyright 2026 Ave Labs

"""Per-user and community settings helpers (locale preferences)."""

from __future__ import annotations

from typing import TYPE_CHECKING

from sqlalchemy import select
from sqlalchemy.dialects.postgresql import insert as pg_insert

from tcbot.database.base import community_settings, telegram_users, user_settings
from tcbot.database.cache.singletons import (
    _COMMUNITY_LOCALE_KEY,
    community_locale_cache,
    user_locale_cache,
)
from tcbot.database.engine import db_call, fetch_one, run_transaction
from tcbot.utils.logger import get_logger
from tcbot.utils.time_and_date import utc_now

if TYPE_CHECKING:
    from sqlalchemy.ext.asyncio import AsyncSession

log = get_logger(__name__)

# * The two-level cache keeps a language change visible across processes:
# * a write invalidates the Redis entry with a generation guard, so a read
# * that started before the write cannot publish the old value into L1.
# * Unset (None) is cached too, so a repeated miss costs no I/O.

# ─────────────────────── User Locale Preferences ───────────────────── #
# * Stored apart from the user profile on purpose: locale rows must never
# * inflate the user counts or appear in user listings, so a bare
# * {user_id, locale} row here is harmless while the same row in the
# * profile table would corrupt stats and search results.


async def get_user_locale(user_id: int) -> str | None:
    """Return the stored locale code for a user, or None when unset."""

    async def _fetch() -> str | None:
        row = await db_call(
            lambda: fetch_one(
                select(user_settings.c.locale).where(user_settings.c.user_id == user_id)
            )
        )
        if row is None:
            return None
        locale = row.get("locale")
        if locale == "":
            # * An empty stored code resolves to no locale while the row
            # * lingers: surface it so the mismatch is visible.
            log.warning("Stored locale for user %d is empty", user_id)
        return locale if isinstance(locale, str) and locale else None

    return await user_locale_cache.get_or_fetch(user_id, _fetch)


async def get_community_locale() -> str | None:
    """Return the community default locale, or None when unset.

    The community row is a singleton, so the cache holds one key. This is
    the last locale tier before the application default: the render path
    reads it only when neither the user nor the group has a usable
    preference.
    """

    async def _fetch() -> str | None:
        row = await db_call(
            lambda: fetch_one(
                select(community_settings.c.default_locale).where(
                    community_settings.c.singleton_key == "global"
                )
            )
        )
        locale = row.get("default_locale") if row is not None else None
        return locale if isinstance(locale, str) and locale else None

    return await community_locale_cache.get_or_fetch(_COMMUNITY_LOCALE_KEY, _fetch)


async def set_user_locale(user_id: int, locale: str | None) -> None:
    """Store a user locale, or clear it when ``locale`` is None.

    Clearing empties the locale and keeps the row, so the other
    preferences of the user survive. Locale codes are stored verbatim;
    validity against the translation catalog is enforced by the caller
    (command layer) and defensively at resolution time.
    """

    async def _work(sess: AsyncSession) -> None:
        # * The settings row refers to the user profile, so the profile
        # * has to exist before the preference can be stored.
        await sess.execute(
            pg_insert(telegram_users)
            .values(user_id=user_id, created_at=utc_now(), updated_at=utc_now())
            .on_conflict_do_nothing(index_elements=["user_id"])
        )
        await sess.execute(
            pg_insert(user_settings)
            .values(user_id=user_id, locale=locale, updated_at=utc_now())
            .on_conflict_do_update(
                index_elements=["user_id"],
                set_={"locale": locale, "updated_at": utc_now()},
            )
        )

    await run_transaction(_work)
    user_locale_cache.invalidate(user_id)
