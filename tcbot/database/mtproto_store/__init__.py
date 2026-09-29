# © Copyright 2024 - 2026 Transsion Core
# © Copyright 2024 - 2026 Dizzy
# © Copyright 2026 Ave Labs

"""MongoDB-backed Kurigram storage engine for the shared MTProto session."""

from __future__ import annotations

from tcbot.database.mongos import col, db_call

from .lease import claim_owner, refresh_owner, release_owner
from .peers import (
    get_peer_by_id,
    get_peer_by_phone_number,
    get_peer_by_username,
    update_peers,
    update_usernames,
)
from .retry import (
    _MAX_WRITE_RETRIES,
    _RETRY_BASE_DELAY,
    _is_transient_write_error,
    _retry_write,
)
from .storage import MongoStorage

__all__ = [
    "_MAX_WRITE_RETRIES",
    "_RETRY_BASE_DELAY",
    "MongoStorage",
    "_is_transient_write_error",
    "_retry_write",
    "claim_owner",
    "col",
    "db_call",
    "get_peer_by_id",
    "get_peer_by_phone_number",
    "get_peer_by_username",
    "refresh_owner",
    "release_owner",
    "update_peers",
    "update_usernames",
]
