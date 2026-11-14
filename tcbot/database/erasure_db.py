# © Copyright 2024 - 2026 Transsion Core
# © Copyright 2024 - 2026 Dizzy
# © Copyright 2026 Ave Labs

"""Operator entry point for the Telegram account erasure queue."""

from __future__ import annotations

from sqlalchemy import text

from tcbot.database.engine import db_call, fetch_value


async def request_erasure(user_id: int, reason: str) -> int:
    """Queue one account erasure and return its request id.

    The database function refuses an unknown user, an already erased user,
    and an empty reason, so the caller never has to duplicate those rules.
    """
    value = await db_call(
        lambda: fetch_value(
            text(
                "SELECT request_user_erasure(:user_id, :reason, 'operator')"
            ).bindparams(user_id=user_id, reason=reason)
        )
    )
    return int(value or 0)
