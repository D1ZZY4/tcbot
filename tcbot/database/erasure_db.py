# © Copyright 2024 - 2026 Transsion Core
# © Copyright 2024 - 2026 Dizzy
# © Copyright 2026 Ave Labs

"""Operator entry point for the Telegram account erasure queue."""

from __future__ import annotations

from sqlalchemy import text

from tcbot.database.engine import db_call, run_returning


async def request_erasure(user_id: int, reason: str) -> int:
    """Queue one account erasure and return its request id.

    The database function refuses an unknown user, an already erased user,
    and an empty reason, so the caller never has to duplicate those rules.
    """
    # * The function inserts the request and its audit event. Run it through
    # * the write boundary, not the autocommit read connection: a write must
    # * not depend on read_connection staying permissive.
    rows = await db_call(
        lambda: run_returning(
            text(
                "SELECT request_user_erasure(:user_id, :reason, 'operator') "
                "AS request_id"
            ).bindparams(user_id=user_id, reason=reason)
        )
    )
    value = rows[0]["request_id"] if rows else None
    return int(value) if value is not None else 0
