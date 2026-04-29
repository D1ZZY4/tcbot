# © Copyright 2024 - 2026 Transsion Core
# © Copyright 2024 - 2026 Dizzy
# © Copyright 2026 Aveum Apps
"""Authorization guards used at the top of every privileged handler.

Each helper returns ``True`` when the calling user has the required role
and otherwise replies with the PROMPT-locked ``"You are not authorized."``
string and returns ``False`` so the handler can early-return cleanly.
"""
from __future__ import annotations

from typing import Any

from ...modules.messages import M
from ...utils.auth import is_authorized as _is_authorized
from ...utils.auth import is_tc_admin as _is_tc_admin
from ...utils.auth import is_tc_owner as _is_tc_owner


async def require_authorized(msg: Any, user_id: int) -> bool:
    """``True`` when the user is TC owner or admin; replies + ``False`` otherwise."""
    if await _is_authorized(user_id):
        return True
    await msg.reply_text(M.NOT_AUTHORIZED)
    return False


async def require_owner(msg: Any, user_id: int) -> bool:
    """``True`` when the user is the Transsion Core Owner."""
    if await _is_tc_owner(user_id):
        return True
    await msg.reply_text(M.NOT_AUTHORIZED)
    return False


async def require_owner_for_transfer(msg: Any, user_id: int) -> bool:
    """Like :func:`require_owner` but uses the PROMPT-locked transfer copy."""
    if await _is_tc_owner(user_id):
        return True
    await msg.reply_text(M.TRANSFER_NOT_OWNER)
    return False


async def is_owner(user_id: int) -> bool:
    return await _is_tc_owner(user_id)


async def is_admin(user_id: int) -> bool:
    return await _is_tc_admin(user_id)


async def is_authorized(user_id: int) -> bool:
    return await _is_authorized(user_id)
