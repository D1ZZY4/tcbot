# © Copyright 2024 - 2026 Transsion Core
# © Copyright 2024 - 2026 Dizzy
# © Copyright 2026 Ave Labs

"""Per-user settings table helpers (locale preferences)."""

from __future__ import annotations

import cachetools as _cachetools
from sqlalchemy import select
from sqlalchemy.dialects.postgresql import insert as pg_insert

from tcbot.database.base import user_settings
from tcbot.database.documents import UserSettingsDoc
from tcbot.database.engine import db_call, fetch_one, run
from tcbot.database.types import UserId
from tcbot.utils.logger import get_logger

log = get_logger(__name__)

# * L1 for locale reads: resolution runs on every command and callback,
# * so hits must cost no I/O. Writes invalidate; TTL bounds staleness
# * when another process changes the row. Unset (None) caches too.
_LOCALE_L1: _cachetools.TTLCache = _cachetools.TTLCache(maxsize=4096, ttl=300)

# ─────────────────────── User Locale Preferences ───────────────────── #
# * Stored apart from member_cache on purpose: locale rows must never
# * inflate the cached-user counts or appear in user listings, so a
# * bare {user_id, locale} row here is harmless while the same row
# * in member_cache would corrupt stats and search results.


async def get_user_locale(user_id: int) -> str | None:
    """Return the stored locale code for a user, or None when unset."""
    try:
        return _LOCALE_L1[user_id]
    except KeyError:
        pass
    row = await db_call(
        lambda: fetch_one(
            select(user_settings.c.locale).where(user_settings.c.user_id == user_id)
        )
    )
    if row is None:
        _LOCALE_L1[user_id] = None
        return None
    locale = row.get("locale")
    value = locale if isinstance(locale, str) and locale else None
    if locale == "":
        # * An empty stored code resolves to no locale while the row
        # * lingers: surface it so the mismatch is visible.
        log.warning("Stored locale for user %d is empty", user_id)
    _LOCALE_L1[user_id] = value
    return value


async def set_user_locale(user_id: int, locale: str | None) -> None:
    """Store a user locale, or clear it when ``locale`` is None.

    Clearing deletes the row so the table holds only users with an
    explicit preference. Locale codes are stored verbatim; validity
    against the translation catalog is enforced by the caller (command
    layer) and defensively at resolution time.
    """
    if locale is None:
        await db_call(
            lambda: run(
                user_settings.delete().where(user_settings.c.user_id == user_id)
            )
        )
        _LOCALE_L1.pop(user_id, None)
        return
    row: UserSettingsDoc = {"user_id": UserId(user_id), "locale": locale}
    await db_call(
        lambda: run(
            pg_insert(user_settings)
            .values(user_id=row["user_id"], locale=row["locale"])
            .on_conflict_do_update(
                index_elements=["user_id"],
                set_={"locale": row["locale"]},
            )
        )
    )
    _LOCALE_L1.pop(user_id, None)
