# © Copyright 2024 - 2026 Transsion Core
# © Copyright 2024 - 2026 Dizzy
# © Copyright 2026 Ave Labs

"""Shared ban-detail formatter: builds the rich ban information card from a ban document."""

from __future__ import annotations

import asyncio
from typing import TYPE_CHECKING

from tcbot import cfg
from tcbot import database as db
from tcbot.modules.helper.parse_link import message_link
from tcbot.utils.formatter import code, mention
from tcbot.utils.i18n import Safe, t
from tcbot.utils.time_and_date import fmt_dt

if TYPE_CHECKING:
    from tcbot.database.documents import BanDoc

# ─────────────────────── Ban detail builder ─────────────────────── #


async def build_ban_detail(
    ban: BanDoc, target_fname: str | None = None, locale: str | None = None
) -> tuple[str, str | None]:
    """Return (formatted text, proof_link or None) for a ban document."""
    # * BanDoc is total=False: every key access below uses .get() with a
    # * display-safe fallback so a sparse record renders instead of raising.
    uid = ban.get("banned_user_id", 0)
    aid = ban.get("admin_user_id", 0)

    if target_fname is None:
        # Fetch mention data for both users in parallel
        r_target, r_admin = await asyncio.gather(
            db.users_cache.get_user_mention_data(uid),
            db.users_cache.get_user_mention_data(aid),
            return_exceptions=True,
        )
        target_fname, target_uname = (
            r_target if not isinstance(r_target, BaseException) else (str(uid), None)
        )
        admin_fname, admin_uname = (
            r_admin if not isinstance(r_admin, BaseException) else ("Admin", None)
        )
    else:
        r_admin = await db.users_cache.get_user_mention_data(aid)
        admin_fname, admin_uname = (
            r_admin if not isinstance(r_admin, BaseException) else ("Admin", None)
        )
        target_uname = None

    proof_chat, proof_thread = cfg.proofs
    proof_msg_id = ban.get("proof_message_id")
    proof_link = (
        message_link(proof_chat, proof_msg_id, proof_thread) if proof_msg_id else None
    )

    ts = ban.get("timestamp")
    date_str = fmt_dt(ts) if ts else "Unknown"

    text = (
        f"{t('checking.ban_info.title', locale)}\n\n"
        f"{t('checking.ban_info.user', locale, user=Safe(mention(uid, target_fname, target_uname)))}\n"
        f"{t('checking.ban_info.user_id', locale, id=Safe(code(str(uid))))}\n\n"
        f"{t('checking.ban_info.banned_by', locale, admin=Safe(mention(aid, admin_fname, admin_uname)))}\n"
        f"{t('checking.ban_info.admin_id', locale, id=Safe(code(str(aid))))}\n\n"
        f"{t('checking.ban_info.reason', locale, reason=ban.get('reason', None) or t('checking.events.no_reason', locale, plain=True))}\n"
        f"{t('checking.ban_info.ban_id', locale, id=Safe(code(ban.get('ban_id', ''))))}\n"
        f"{t('checking.ban_info.date', locale, date=Safe(date_str))}"
    )
    return text, proof_link
