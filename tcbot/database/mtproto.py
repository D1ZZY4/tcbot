# © Copyright 2024 - 2026 Transsion Core
# © Copyright 2024 - 2026 Dizzy
# © Copyright 2026 Ave Labs

"""MTProto client: required Kurigram identity resolution beyond Bot API limits.

The Bot API only knows users the bot has seen; a user-session MTProto client
can additionally resolve silent users by ID. The session lives in MongoDB
(``mtproto_store``), so every instance shares one authorization. API_ID and
API_HASH are mandatory: the bot refuses to boot without them, and a stored
session without a login is fatal too. Only transient runtime failures
(disconnects, unknown peers, flood waits) degrade to None so moderation
never blocks on MTProto.

Serverless paths never start the client: resolve_user() simply returns None
there (and when unconfigured, which main transports forbid at boot).
"""

from __future__ import annotations

import asyncio
import logging
import sqlite3
from pathlib import Path
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


def client() -> Client:
    """Return the shared unstarted MTProto client.

    Raises RuntimeError when API_ID/API_HASH are not set: MTProto is
    mandatory, so a missing configuration must fail fast, never silently
    degrade into Bot-API-only mode.
    """
    global _client
    if _client is not None:
        return _client
    if not cfg.mtproto_enabled:
        raise RuntimeError(
            "API_ID/API_HASH are required for MTProto identity resolution; refusing to boot degraded."
        )
    from pyrogram import (  # noqa: PLC0415 (optional extra; import only when configured)
        Client,
    )

    from tcbot.database.mtproto_store import (  # noqa: PLC0415 (same; keeps startup lean)
        MongoStorage,
    )

    _client = Client(
        cfg.mtproto_session,
        api_id=cfg.api_id,
        api_hash=cfg.api_hash,
        storage_engine=MongoStorage(cfg.mtproto_session),
    )
    return _client


async def start() -> bool:
    """Connect the shared client; raise RuntimeError when unusable.

    Missing credentials, an unreadable store, or a session without a login
    are all fatal: booting degraded would silently reintroduce the numeric-ID
    displays MTProto exists to eliminate. The authorization check reads the
    stored session only: a fresh session must never reach start(), because
    Kurigram answers it with an interactive stdin prompt that wedges
    headless boot forever.
    """
    c = client()
    if c.is_connected:
        return True
    try:
        store = c.storage
        await store.open()
        authorized = bool(await store.user_id())
        if not authorized:
            authorized = await _import_legacy_file(store)
        await store.close()
    except asyncio.CancelledError:
        raise
    except Exception as exc:
        raise RuntimeError(f"MTProto session unreadable: {exc}") from exc
    if not authorized:
        raise RuntimeError(
            "MTProto session not authorized; run python -m tcbot.database.mtproto_auth"
            " once to log in."
        )
    try:
        await c.start()
    except asyncio.CancelledError:
        raise
    except Exception as exc:
        raise RuntimeError(f"MTProto start failed: {exc}") from exc
    log.info("MTProto connected.")
    return True


async def _import_legacy_file(store) -> bool:  # type: ignore[no-untyped-def]
    """Import an authorized `<session>.session` file into the shared store once.

    Returns True when the file held a login (the store is usable now).
    Missing, junk, or unauthorized files all mean False, never raise.
    """
    path = Path(f"{cfg.mtproto_session}.session")
    if not path.is_file():
        return False
    try:
        db = sqlite3.connect(f"file:{path}?mode=ro", uri=True)
        try:
            row = db.execute(
                "SELECT dc_id, server_address, port, api_id, test_mode,"
                " auth_key, date, user_id, is_bot FROM sessions"
            ).fetchone()
            if not row or not row[7]:
                return False
            for name, value in zip(
                (
                    "dc_id",
                    "server_address",
                    "port",
                    "api_id",
                    "test_mode",
                    "auth_key",
                    "date",
                    "user_id",
                    "is_bot",
                ),
                row,
                strict=True,
            ):
                await store._accessor(name, value)
            await store.update_peers(
                db.execute(
                    "SELECT id, access_hash, type, phone_number FROM peers"
                ).fetchall()
            )
            for peer_id, names in _group_usernames(db).items():
                await store.update_usernames([(peer_id, names)])
            for state in db.execute(
                "SELECT id, pts, qts, date, seq FROM update_state"
            ).fetchall():
                await store.set_update_state(_update_state(*state))
        finally:
            db.close()
    except Exception as exc:
        log.debug("Legacy session import skipped for %s: %s", path, exc)
        return False
    log.info("Imported authorized session from %s into shared storage.", path)
    return True


def _group_usernames(db: sqlite3.Connection) -> dict[int, list[str | None]]:
    """Group username rows by peer ID."""
    grouped: dict[int, list[str | None]] = {}
    for peer_id, username in db.execute(
        "SELECT id, username FROM usernames"
    ).fetchall():
        grouped.setdefault(peer_id, []).append(username)
    return grouped


def _update_state(  # type: ignore[no-untyped-def]
    state_id: int, pts: int | None, qts: int | None, date: int | None, seq: int | None
):
    """Build the storage UpdateState shape without importing Kurigram here."""
    from pyrogram.storage import UpdateState  # noqa: PLC0415 (lazy like the client)

    return UpdateState(state_id, pts, qts, date, seq)


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

    Returns None when the client is not running (serverless paths), when it
    drops mid-run, or when the peer is unknown, rate-limited, or nameless:
    every case just means "fall through to the next resolution source".
    Missing credentials also mean None here; main transports refuse to boot
    that way, so this only fires where MTProto was never required.
    Cancellation always propagates.
    """
    if not cfg.mtproto_enabled:
        return None
    c = client()
    if not c.is_connected:
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


async def harvest_group_members(chat_id: int, *, limit: int = 1000) -> int:
    """Cache every member of *chat_id* the session can see; return harvested count.

    One-shot backfill for silent members no Bot API call ever observed: each
    seen identity lands in member_cache, so later bans and checks resolve by
    name. Stops early on FloodWait (returns the count so far); peer hashes
    persist in shared storage as a side effect for future direct resolves.
    """
    # ponytail: single sequential scan, no parallelism; shard per-group or
    # page with smaller limits if a mega-group harvest ever too slow.
    from tcbot.database import users_cache  # noqa: PLC0415 (avoid import cycle)

    c = client()
    if not c.is_connected:
        raise RuntimeError("MTProto client is not connected.")
    count = 0
    try:
        async for member in c.get_chat_members(chat_id, limit=limit):
            user = getattr(member, "user", None)
            fname = getattr(user, "first_name", None) if user is not None else None
            if user is None or getattr(user, "is_bot", False) or not fname:
                continue
            try:
                await users_cache.harvest_user_identity(
                    user.id,
                    getattr(user, "username", None),
                    fname,
                    getattr(user, "last_name", None),
                )
            except Exception as exc:
                log.debug("Member harvest write failed for %d: %s", user.id, exc)
                continue
            count += 1
    except Exception as exc:
        if getattr(exc, "value", None) is not None:  # FloodWait-likes carry .value
            log.warning("Member harvest stopped early in %d: %s", chat_id, exc)
            return count
        raise
    return count
