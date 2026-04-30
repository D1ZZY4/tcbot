# © Copyright 2024 - 2026 Transsion Core
# © Copyright 2024 - 2026 Dizzy
# © Copyright 2026 Aveum Apps

"""
Owner / admin role management business logic.

PROMPT Feature 9 (promote), 10 (demote), 11 (transfer owner) and 14
(promotion-request review) all live here. The Telegram handler in
:mod:`tgbot_tcf.handlers.admins` is the thin interface that decides who
asks the question; this module decides what to do with the answer.
"""
from __future__ import annotations

import uuid
from datetime import datetime
from typing import Any, Dict, Optional

from ..database import admins_repo, requests_repo
from ..utils.format import utcnow


# ------------------------------------------------------------------ promote

async def promote_immediately(*, target_id: int, by_owner_id: int) -> None:
    """Owner promote: add the user as a Transsion Core Admin straight away."""
    await admins_repo.add_admin(
        user_id=target_id,
        promoted_by=by_owner_id,
        promoted_date=utcnow(),
    )


async def create_promotion_request(*, target_id: int, requested_by: int) -> str:
    """Admin promote: park the request for owner approval. Returns request_id."""
    request_id = str(uuid.uuid4())
    await requests_repo.create(
        request_id=request_id,
        target_id=target_id,
        promoted_by=requested_by,
        requested_date=utcnow(),
    )
    return request_id


# ------------------------------------------------------------ request review

async def fetch_request(request_id: str) -> Optional[Dict[str, Any]]:
    return await requests_repo.find_by_id(request_id)


async def list_pending_requests() -> list[Dict[str, Any]]:
    return await requests_repo.list_pending()


async def approve_request(
    *, request_id: str, by_owner_id: int
) -> Optional[Dict[str, Any]]:
    """Promote the target if not already a TC admin, then resolve the request."""
    record = await requests_repo.find_by_id(request_id)
    if not record or record.get("status") != "pending":
        return None
    target_id = record["target_id"]
    now = utcnow()
    if not await admins_repo.is_admin(target_id):
        await admins_repo.add_admin(
            user_id=target_id, promoted_by=by_owner_id, promoted_date=now
        )
    await requests_repo.resolve(
        request_id=request_id,
        status="approved",
        resolved_by=by_owner_id,
        resolved_date=now,
    )
    return record


async def reject_request(
    *, request_id: str, by_owner_id: int
) -> Optional[Dict[str, Any]]:
    record = await requests_repo.find_by_id(request_id)
    if not record or record.get("status") != "pending":
        return None
    await requests_repo.resolve(
        request_id=request_id,
        status="rejected",
        resolved_by=by_owner_id,
        resolved_date=utcnow(),
    )
    return record


# ------------------------------------------------------------------- demote

async def demote_user(target_id: int) -> bool:
    """Return ``True`` if the user was a TC admin and has now been removed."""
    return await admins_repo.remove_admin(target_id)


# ----------------------------------------------------------------- transfer

async def transfer_ownership(*, new_owner_id: int, old_owner_id: int) -> None:
    """Replace the owner; demote-then-readmit the old owner as a TC admin."""
    when = utcnow()
    await admins_repo.replace_owner(new_owner_id)
    # If the new owner happened to be a TC admin, drop their admin row
    # since they now hold the higher role.
    await admins_repo.remove_admin(new_owner_id)
    await admins_repo.upsert_admin_if_missing(
        user_id=old_owner_id,
        promoted_by=old_owner_id,
        promoted_date=when,
    )


# Convenience time helper (so callers do not import utcnow themselves)
def now() -> datetime:
    return utcnow()
