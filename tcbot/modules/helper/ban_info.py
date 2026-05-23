# © Copyright 2024 - 2026 Transsion Core
# © Copyright 2024 - 2026 Dizzy
# © Copyright 2026 Aveum Apps

"""Shared ban-detail formatter – builds the rich ban information card from a ban document."""

from __future__ import annotations

import asyncio

from tcbot import cfg
from tcbot import database as db
from tcbot.modules.helper.formatter import code, esc, mention
from tcbot.modules.helper.parse_link import message_link
from tcbot.utils.timedate_format import fmt_dt

# ─────────────────────── Ban detail builder ─────────────────────── #


async def build_ban_detail(
    ban: dict, target_fname: str | None = None
) -> tuple[str, str | None]:
    """Return (formatted text, proof_link or None) for a ban document."""
    uid = ban["banned_user_id"]
    aid = ban.get("admin_user_id", 0)

    if target_fname is None:
        target_fname, admin_fname = await asyncio.gather(
            db.users_db.get_first_name(uid, str(uid)),
            db.users_db.get_first_name(aid, str(aid)),
        )
    else:
        admin_fname = await db.users_db.get_first_name(aid, str(aid))

    proof_chat, proof_thread = cfg.proofs
    proof_link = (
        message_link(proof_chat, ban["proof_message_id"], proof_thread)
        if ban.get("proof_message_id")
        else None
    )

    ts = ban.get("timestamp")
    date_str = fmt_dt(ts) if ts else "Unknown"

    text = (
        "<b>Ban Information</b>\n\n"
        f"User: {mention(uid, target_fname)}\n"
        f"User ID: {code(str(uid))}\n\n"
        f"Banned by: {mention(aid, admin_fname)}\n"
        f"Admin ID: {code(str(aid))}\n\n"
        f"Reason: {esc(ban.get('reason', 'No reason provided'))}\n"
        f"Ban ID: {code(ban['ban_id'])}\n"
        f"Date: {date_str}"
    )
    return text, proof_link
