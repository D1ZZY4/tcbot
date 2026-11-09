# © Copyright 2024 - 2026 Transsion Core
# © Copyright 2024 - 2026 Dizzy
# © Copyright 2026 Ave Labs

"""Per-group render-locale preferences stored on the group row."""

from __future__ import annotations

import cachetools as _cachetools

from tcbot.database.mongos import db_call

from .collections import _groups

# * Stored on the federated_groups row itself: locale rides alongside
# * the group with no extra collection, and reads filter on the already
# * indexed chat_id. No upsert here: only connected groups hold settings.
# * L1 for locale reads: resolution runs on every group command, so hits
# * must cost no I/O. Writes invalidate; TTL bounds staleness when
# * another process changes the row. Unset (None) caches too.
_GROUP_LOCALE_L1: _cachetools.TTLCache = _cachetools.TTLCache(maxsize=1024, ttl=300)


async def get_group_locale(chat_id: int) -> str | None:
    """Return the stored locale code for a group, or None when unset."""
    try:
        return _GROUP_LOCALE_L1[chat_id]
    except KeyError:
        pass
    doc = await db_call(
        _groups().find_one({"chat_id": chat_id}, {"_id": 0, "locale": 1})
    )
    if not doc:
        _GROUP_LOCALE_L1[chat_id] = None
        return None
    locale = doc.get("locale")
    value = locale if isinstance(locale, str) and locale else None
    _GROUP_LOCALE_L1[chat_id] = value
    return value


async def set_group_locale(chat_id: int, locale: str | None) -> bool:
    """Store a group locale, or clear it when ``locale`` is None.

    Returns True when a group row was matched. Locale codes are stored
    verbatim; validity is enforced by the caller and at resolution time.
    """
    if locale is None:
        result = await db_call(
            _groups().update_one({"chat_id": chat_id}, {"$unset": {"locale": ""}})
        )
    else:
        result = await db_call(
            _groups().update_one({"chat_id": chat_id}, {"$set": {"locale": locale}})
        )
    _GROUP_LOCALE_L1.pop(chat_id, None)
    return result.matched_count > 0
