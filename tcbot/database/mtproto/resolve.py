# © Copyright 2024 - 2026 Transsion Core
# © Copyright 2024 - 2026 Dizzy
# © Copyright 2026 Ave Labs

"""MTProto identity resolution: user, username, and bot-flag lookups."""

from __future__ import annotations

import asyncio
from typing import TYPE_CHECKING

from tcbot.database import mtproto as _mtproto_pkg
from tcbot.utils.logger import get_logger
from tcbot.utils.time_and_date import TELEGRAM_LOOKUP_TIMEOUT

if TYPE_CHECKING:
    from pyrogram import Client
    from pyrogram.types import User

# * Logger keeps the pre-split name so log output is unchanged.
log = get_logger("tcbot.database.mtproto")


async def _fetch_user(target_id: int) -> User | None:
    """Single peer lookup shared by resolve_user and is_bot_user.

    Returns the raw peer, or None when the client is down, the lookup
    times out, or the peer is unknown/rate-limited. Cancellation propagates.
    """
    c: Client | None = _mtproto_pkg._client
    if _mtproto_pkg._auth_dead or c is None or not c.is_connected:
        return None
    try:
        async with asyncio.timeout(TELEGRAM_LOOKUP_TIMEOUT):
            return await c.get_users(target_id)
    except asyncio.CancelledError:
        raise
    except Exception as exc:
        # * FloodWait carries the wait in .value; either way the answer is
        # * "not now": never sleep the moderation loop for it.
        wait = getattr(exc, "value", None)
        if wait is not None:
            log.warning("MTProto FloodWait for %d: retry in %ss.", target_id, wait)
        else:
            log.debug("MTProto resolve failed for %d: %s", target_id, exc)
        return None


async def resolve_user(target_id: int) -> tuple[str, str | None, str | None] | None:
    """Resolve (first_name, username, last_name) for a user ID via MTProto.

    Returns None when the client is not running (serverless paths), when it
    drops mid-run, or when the peer is unknown, rate-limited, or nameless:
    every case just means "fall through to the next resolution source".
    Cancellation always propagates.
    """
    user = await _fetch_user(target_id)
    if user is None:
        return None
    fname: str = getattr(user, "first_name", "") or ""
    if not fname:
        return None
    return fname, getattr(user, "username", None), getattr(user, "last_name", None)


async def resolve_username(username: str) -> tuple[int, str, str | None] | None:
    """Resolve an @username to (user_id, first_name, username) via MTProto.

    Catches what Bot API username lookups miss (proven live: a username
    ``get_chat`` rejected resolved here). Exact match only, so moderation
    paths can trust it like any verified @username. Returns None when the
    client is down or the username is unknown/taken-down. Resolved peers
    stay in shared storage for later direct ID lookups.
    """
    c: Client | None = _mtproto_pkg._client
    if _mtproto_pkg._auth_dead or c is None or not c.is_connected:
        return None
    try:
        from pyrogram import raw  # noqa: PLC0415 (heavy extra; import only on use)

        async with asyncio.timeout(TELEGRAM_LOOKUP_TIMEOUT):
            resolved = await c.invoke(
                raw.functions.contacts.ResolveUsername(username=username.lstrip("@"))  # type: ignore[attr-defined]
            )
    except asyncio.CancelledError:
        raise
    except Exception as exc:
        log.debug("MTProto username resolve failed for %s: %s", username, exc)
        return None
    for user in resolved.users:
        fname: str = getattr(user, "first_name", "") or ""
        if fname:
            return user.id, fname, getattr(user, "username", None)
    return None


async def is_bot_user(target_id: int) -> bool | None:
    """Return is_bot for a user ID via MTProto, or None when unknowable.

    Uses the same peer lookup as resolve_user but surfaces the bot flag
    instead of the name triple. Promotion and transfer guards use it to
    refuse bot targets; client down, unknown peer, flood, and nameless
    all map to None (unknown, never False-as-fact).
    """
    user = await _fetch_user(target_id)
    if user is None:
        return None
    return bool(getattr(user, "is_bot", False))
