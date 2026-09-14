# © Copyright 2024 - 2026 Transsion Core
# © Copyright 2024 - 2026 Dizzy
# © Copyright 2026 Ave Labs

"""MTProto base: lazy optional Kurigram client for lookups beyond Bot API limits.

Not wired into extraction yet. When API_ID/API_HASH are unset every helper
below degrades to None/False so the bot runs exactly as before.
"""

from __future__ import annotations

import logging
from typing import TYPE_CHECKING

from tcbot import cfg

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
