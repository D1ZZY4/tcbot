# © Copyright 2024 - 2026 Transsion Core
# © Copyright 2024 - 2026 Dizzy
# © Copyright 2026 Ave Labs

"""MTProto store single-owner lease: claim, refresh, and release."""

from __future__ import annotations

import asyncio
import time
from typing import TYPE_CHECKING

from pymongo import ReturnDocument
from pymongo.errors import DuplicateKeyError

from tcbot.database.mongos import db_call
from tcbot.utils.logger import get_logger

from .retry import _retry_write

if TYPE_CHECKING:
    from typing import Any

    from tcbot.database.mtproto_store.storage import MongoStorage

# * Logger keeps the pre-split name so log output is unchanged.
log = get_logger("tcbot.database.mtproto_store")


async def claim_owner(store: MongoStorage, owner: str, *, ttl_s: float) -> bool:
    """Atomically claim the single-owner lease for *owner*.

    Succeeds on a free lease, an expired lease (previous holder died
    without releasing), or a first-time insert won against a
    concurrent claimant (the loser gets DuplicateKeyError). A live
    lease held by anyone else refuses. Only CancelledError
    propagates; every other failure returns False so callers degrade
    instead of sharing one auth key twice.
    """
    now = time.time()
    lease_id = store._lease_id()

    async def _take() -> Any:
        return await db_call(
            store._coll().find_one_and_update(
                {
                    "_id": lease_id,
                    "$or": [{"owner": owner}, {"expires_at": {"$lt": now}}],
                },
                {"$set": {"owner": owner, "expires_at": now + ttl_s}},
                return_document=ReturnDocument.AFTER,
            )
        )

    try:
        if await _retry_write(_take) is not None:
            return True
    except asyncio.CancelledError:
        raise
    except Exception:
        log.exception("MTProto lease claim failed")
        return False

    # * No row (first boot) or a live foreign lease: exactly one
    # * concurrent insert wins; the loser degrades instead of sharing
    # * the auth key.
    async def _first() -> None:
        await db_call(
            store._coll().insert_one(
                {"_id": lease_id, "owner": owner, "expires_at": now + ttl_s}
            )
        )

    try:
        await _retry_write(_first)
        return True
    except asyncio.CancelledError:
        raise
    except DuplicateKeyError:
        return False
    except Exception:
        log.exception("MTProto lease first-claim insert failed")
        return False


async def refresh_owner(store: MongoStorage, owner: str, *, ttl_s: float) -> bool:
    """Renew the lease; False when someone else owns it (fencing)."""
    res = await db_call(
        store._coll().update_one(
            {"_id": store._lease_id(), "owner": owner},
            {"$set": {"expires_at": time.time() + ttl_s}},
        )
    )
    return res.matched_count > 0


async def release_owner(store: MongoStorage, owner: str) -> None:
    """Best-effort lease release; expiry covers leftovers after a crash."""
    try:
        await db_call(
            store._coll().delete_one({"_id": store._lease_id(), "owner": owner})
        )
    except asyncio.CancelledError:
        raise
    except Exception as exc:
        log.debug("MTProto lease release failed (expiry covers it): %s", exc)
