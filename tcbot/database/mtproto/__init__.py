# © Copyright 2024 - 2026 Transsion Core
# © Copyright 2024 - 2026 Dizzy
# © Copyright 2026 Ave Labs

"""MTProto client: bot-token session for lookups beyond Bot API enumeration."""

from __future__ import annotations

from typing import TYPE_CHECKING

from tcbot import cfg as cfg
from tcbot.utils.time_and_date import monotonic as monotonic

from .harvest import harvest_group_members
from .lifecycle import (
    _heartbeat_lease,
    _instance_id,
    _release_lease_quietly,
    client,
    handle_auth_failure,
    is_auth_dead,
    is_auth_key_duplicated,
    is_configured,
    start,
    stop,
)
from .resolve import _fetch_user, is_bot_user, resolve_user, resolve_username

if TYPE_CHECKING:
    import asyncio

    from pyrogram import Client

# ─────────── Shared mutable state (single owner: this package) ────── #
# * Tests patch these attributes on the package (monkeypatch.setattr on
# * tcbot.database.mtproto), so they live here and every submodule reads
# * them via the package namespace at call time, exactly like
# * tcbot.database.cache.twolevel resolves its patchable names.

_client: Client | None = None
_lease_owner: str | None = None
_heartbeat_task: asyncio.Task[None] | None = None
_auth_dead: bool = False

# * Ceiling for the initial session connect at boot. A network partition
# * must fail the boot loudly instead of hanging it forever.
_START_TIMEOUT_S: float = 60.0

# * Single-owner lease bounds: only the instance holding the lease keeps a
# * live MTProto connection, because Telegram kills the shared auth key
# * when two clients connect with it at once (406 AUTH_KEY_DUPLICATED).
# * The heartbeat refreshes well inside the TTL; a crashed holder fails
# * over to the next claimant after at most one TTL.
_LEASE_TTL_S: float = 90.0
_HEARTBEAT_S: float = 30.0

# * Wall-clock cap for one harvest_group_members scan: the loop is up to
# * ``limit`` sequential DB writes on the event loop, so an unbounded scan
# * of a mega-group would stall moderation traffic behind a backfill.
_HARVEST_BUDGET_S: float = 25.0

__all__ = [
    "_HARVEST_BUDGET_S",
    "_HEARTBEAT_S",
    "_LEASE_TTL_S",
    "_START_TIMEOUT_S",
    "_auth_dead",
    "_client",
    "_fetch_user",
    "_heartbeat_lease",
    "_heartbeat_task",
    "_instance_id",
    "_lease_owner",
    "_release_lease_quietly",
    "cfg",
    "client",
    "handle_auth_failure",
    "harvest_group_members",
    "is_auth_dead",
    "is_auth_key_duplicated",
    "is_bot_user",
    "is_configured",
    "monotonic",
    "resolve_user",
    "resolve_username",
    "start",
    "stop",
]
