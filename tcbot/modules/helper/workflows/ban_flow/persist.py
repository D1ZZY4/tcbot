# © Copyright 2024 - 2026 Transsion Core
# © Copyright 2024 - 2026 Dizzy
# © Copyright 2026 Ave Labs

"""Ban record writes: update an existing ban or insert a fresh one."""

from __future__ import annotations

from typing import TYPE_CHECKING, Any

from tcbot import database as db
from tcbot.modules.helper import keyboards, parse_logmsg, replies
from tcbot.modules.helper.parse_link import appeal_deep_link
from tcbot.utils.logger import get_logger
from tcbot.utils.time_and_date import to_utc, utc_now

if TYPE_CHECKING:
    from datetime import datetime

    from telegram import Bot

    from tcbot.database.documents import BanDoc

log = get_logger(__name__)


async def _execute_ban_update(
    bot: Bot,
    existing: BanDoc,
    meta: dict[str, Any],
    proof_msg_id: int | None,
    proof_link: str | None,
    prev_proof_link: str | None,
    logs_chat: int,
    logs_thread: int | None,
) -> tuple[int, bool]:
    """Build log text, keyboard, and DB update for an existing ban re-enforcement.

    Returns ``(log_msg_id, db_ok)`` so the caller can fail closed when the
    ``bans`` write fails instead of enforcing chats without a record.
    """
    target_id: int = meta.get("ban_target_id") or 0
    target_fname: str = meta.get("ban_target_fname", str(target_id))
    admin_id: int = meta.get("ban_admin_id") or 0
    admin_fname: str = meta.get("ban_admin_fname", "Admin")
    reason: str = meta.get(
        "ban_reason", replies.no_reason(meta.get("ban_locale"), plain=True)
    )
    ban_id = str(existing.get("ban_id", ""))
    old_admin_id = int(existing.get("admin_user_id", admin_id))
    bot_username = bot.username or ""
    old_proof_msg_id = int(existing.get("proof_message_id", 0))
    old_log_msg_id = int(existing.get("log_message_id", 0))
    new_proof_msg_id = proof_msg_id if proof_msg_id else old_proof_msg_id

    try:
        old_admin_fname = await db.users_cache.get_first_name(old_admin_id, "Admin")
    except Exception:
        old_admin_fname = "Admin"

    log_text = parse_logmsg.ban_update_log(
        target_id,
        target_fname,
        admin_id,
        admin_fname,
        old_admin_id,
        old_admin_fname,
        reason,
        ban_id,
        to_utc(existing.get("timestamp", utc_now())),
    )
    _appeal_url = appeal_deep_link(bot_username, ban_id)
    kb = (
        keyboards.ban_log_update(
            target_id, proof_link, prev_proof_link, _appeal_url, meta.get("ban_locale")
        )
        if proof_link and prev_proof_link
        else (
            keyboards.ban_log_new(
                target_id, proof_link, _appeal_url, meta.get("ban_locale")
            )
            if proof_link
            else None
        )
    )

    send_kwargs: dict = {"parse_mode": "MarkdownV2", "message_thread_id": logs_thread}
    if kb:
        send_kwargs["reply_markup"] = kb
    # * Sequential, not gather: the DB row is authoritative and the log post
    # * is observable. Racing them lets a DB failure leave a phantom ban card
    # * in the logs channel (dead appeal link, /check miss), so the log only
    # * goes out after the write succeeds.
    try:
        await db.bans_db.update_ban(
            ban_id,
            reason,
            admin_id,
            new_proof_msg_id,
            0,
            old_proof_msg_id,
            old_log_msg_id,
        )
    except Exception:
        log.exception("update_ban failed for ban_id=%s", ban_id)
        return 0, False

    try:
        log_msg = await bot.send_message(logs_chat, log_text, **send_kwargs)
    except Exception:
        log.exception("Ban log send failed for ban_id=%s", ban_id)
        return 0, True
    log_msg_id = log_msg.message_id
    log.info("Ban log posted: ban_id=%s msg_id=%s", ban_id, log_msg_id)
    return log_msg_id, True


async def _execute_new_ban(
    bot: Bot,
    meta: dict[str, Any],
    proof_msg_id: int | None,
    proof_link: str | None,
    now: datetime,
    logs_chat: int,
    logs_thread: int | None,
    ban_id: str,
) -> tuple[int, bool]:
    """Build log text, keyboard, and DB insert for a fresh ban.

    Returns ``(log_msg_id, db_ok)`` so the caller can fail closed when the
    ``bans`` write fails instead of enforcing chats without a record.
    """
    target_id: int = meta.get("ban_target_id") or 0
    target_fname: str = meta.get("ban_target_fname", str(target_id))
    admin_id: int = meta.get("ban_admin_id") or 0
    admin_fname: str = meta.get("ban_admin_fname", "Admin")
    reason: str = meta.get(
        "ban_reason", replies.no_reason(meta.get("ban_locale"), plain=True)
    )
    bot_username = bot.username or ""

    log_text = parse_logmsg.ban_log(
        target_id,
        target_fname,
        admin_id,
        admin_fname,
        reason,
        ban_id,
        now,
    )
    kb = (
        keyboards.ban_log_new(
            target_id,
            proof_link,
            appeal_deep_link(bot_username, ban_id),
            meta.get("ban_locale"),
        )
        if proof_link
        else None
    )

    send_kwargs = {"parse_mode": "MarkdownV2", "message_thread_id": logs_thread}
    if kb:
        send_kwargs["reply_markup"] = kb
    # * Sequential, not gather: same phantom-log rationale as
    # * _execute_ban_update above; the insert must land before the card.
    try:
        await db.bans_db.create_ban(
            target_id, reason, admin_id, proof_msg_id or 0, 0, ban_id
        )
    except Exception:
        log.exception("create_ban failed for ban_id=%s", ban_id)
        return 0, False

    try:
        log_msg = await bot.send_message(logs_chat, log_text, **send_kwargs)
    except Exception:
        log.exception("Ban log send failed for ban_id=%s", ban_id)
        return 0, True
    log_msg_id = log_msg.message_id
    log.info("Ban log posted: ban_id=%s msg_id=%s", ban_id, log_msg_id)
    return log_msg_id, True
