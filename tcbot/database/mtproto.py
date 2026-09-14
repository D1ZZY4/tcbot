# © Copyright 2024 - 2026 Transsion Core
# © Copyright 2024 - 2026 Dizzy
# © Copyright 2026 Ave Labs

"""MTProto base: lazy optional Kurigram client for lookups beyond Bot API limits.

The Bot API only knows users the bot has seen; a user-session MTProto client
can additionally resolve silent users by ID. Everything here degrades to
None/False when API_ID/API_HASH are unset (or the session is unusable), so
the bot runs exactly as before and moderation never blocks on MTProto.

Not started in serverless paths: resolve_user() simply returns None there.
"""

from __future__ import annotations

import asyncio
import logging
from typing import TYPE_CHECKING

from tcbot import cfg
from tcbot.utils.time_and_date import TELEGRAM_LOOKUP_TIMEOUT

if TYPE_CHECKING:
    from pyrogram import Client

log = logging.getLogger(__name__)

_client: Client | None = None


def is_configured() -> bool:
    """Return True when API_ID + API_HASH are set."""
    return cfg.mtproto_enabled


def client() -> Client | None:
    """Return the shared unstarted MTProto client, or None when unconfigured."""
    global _client
    if _client is not None:
        return _client
    if not cfg.mtproto_enabled:
        return None
    from pyrogram import (  # noqa: PLC0415 (optional extra; import only when configured)
        Client,
    )

    _client = Client(cfg.mtproto_session, api_id=cfg.api_id, api_hash=cfg.api_hash)
    return _client


async def start() -> bool:
    """Connect the shared client; return False (never raise) when unusable.

    The authorization check reads the local session file only: a fresh
    session must never reach start(), because Kurigram answers it with an
    interactive stdin prompt that wedges headless boot forever.
    """
    c = client()
    if c is None:
        log.info("MTProto not configured; identity lookups use Bot API only.")
        return False
    if c.is_connected:
        return True
    try:
        await c.storage.open()
        authorized = bool(await c.storage.user_id())
        await c.storage.close()
    except asyncio.CancelledError:
        raise
    except Exception as exc:
        log.warning("MTProto session unreadable; continuing without it: %s", exc)
        return False
    if not authorized:
        log.warning(
            "MTProto session not authorized; run python -m tcbot.database.mtproto_auth"
            " once and redeploy the .session file. Continuing without MTProto."
        )
        return False
    try:
        await c.start()
    except asyncio.CancelledError:
        raise
    except Exception as exc:
        log.warning("MTProto start failed; continuing without it: %s", exc)
        return False
    log.info("MTProto connected.")
    return True


async def stop() -> None:
    """Disconnect the shared client; best-effort, never raises."""
    global _client
    c, _client = _client, None
    if c is None:
        return
    try:
        await c.stop()
    except asyncio.CancelledError:
        raise
    except Exception as exc:
        log.debug("MTProto stop failed (non-fatal): %s", exc)


async def resolve_user(target_id: int) -> tuple[str, str | None, str | None] | None:
    """Resolve (first_name, username, last_name) for a user ID via MTProto.

    Returns None when unconfigured, disconnected, unknown to the session,
    rate-limited, or nameless: every case just means "fall through to the
    next resolution source". Cancellation always propagates.
    """
    c = client()
    if c is None or not c.is_connected:
        return None
    try:
        async with asyncio.timeout(TELEGRAM_LOOKUP_TIMEOUT):
            user = await c.get_users(target_id)
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
    fname: str = getattr(user, "first_name", "") or ""
    if not fname:
        return None
    return fname, getattr(user, "username", None), getattr(user, "last_name", None)
