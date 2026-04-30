# © Copyright 2024 - 2026 Transsion Core
# © Copyright 2024 - 2026 Dizzy
# © Copyright 2026 Aveum Apps
"""Ban / unban handlers (PROMPT Features 5, 6).

This handler owns the proof-collection session: timers, album debouncing,
and the in-memory ``bot_data`` map. The actual DB writes, proof uploads
and log-text construction are delegated to :mod:`tgbot_tcf.modules.bans`.
"""
from __future__ import annotations

import asyncio
import logging
from datetime import datetime
from typing import Any

from telegram import Update
from telegram.error import TelegramError
from telegram.ext import ContextTypes

from .. import ALBUM_DEBOUNCE_SECONDS, MAIN_GROUP, PROOF_WAIT_SECONDS
from ..modules import bans, keyboards, log_templates
from ..modules.messages import M
from ..utils.auth import is_tc_admin, is_tc_owner
from ..utils.format import safe_first_name
from ..utils.logger import log_to_channel
from .helper import auth, enforce_ban_across_groups, enforce_unban_across_groups, messaging, targets

logger = logging.getLogger(__name__)


# -------------------------------------------------------- session bookkeeping

def _session_key(chat_id: int, user_id: int) -> str:
    return f"tcban:{chat_id}:{user_id}"


def _get_sessions(context: ContextTypes.DEFAULT_TYPE) -> dict[str, Any]:
    app: Any = getattr(context, "application", None)
    if app is None:
        return {}
    return app.bot_data.setdefault("tcban_sessions", {})


def _drop_jobs(sess: dict[str, Any]) -> None:
    for job_key in ("timeout_job", "album_job"):
        job = sess.get(job_key)
        if job is None:
            continue
        try:
            job.schedule_removal()
        except Exception:
            pass


async def _timeout_session(context: ContextTypes.DEFAULT_TYPE) -> None:
    """Called by JobQueue when the proof window expires."""
    job: Any = context.job
    data: Any = getattr(job, "data", None)
    if not data:
        return
    key: str = data["key"]
    sessions = _get_sessions(context)
    sess: dict[str, Any] | None = sessions.pop(key, None)
    if sess is None:
        return
    await messaging.safe_edit_text(
        context,
        chat_id=sess["chat_id"],
        message_id=sess["prompt_msg_id"],
        text=M.BAN_PROOF_TIMEOUT,
        parse_mode=None,
    )


# ------------------------------------------------------------------ /tcban

async def cmd_cban(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Start a Transsion Core ban with proof collection."""
    msg = update.effective_message
    user = update.effective_user
    if msg is None or user is None:
        return

    if not await auth.require_authorized(msg, user.id):
        return

    if not (
        context.args
        or (msg.reply_to_message and msg.reply_to_message.from_user)
    ):
        await msg.reply_text(M.BAN_USAGE)
        return

    target = await targets.resolve_or_complain(update, context, msg)
    if target is None:
        return

    if target.id == user.id:
        await msg.reply_text(M.BAN_SELF_BLOCKED)
        return

    if target.id == context.bot.id:
        await msg.reply_text(M.BAN_SELF_BOT_BLOCKED)
        return

    if await is_tc_owner(target.id) or await is_tc_admin(target.id):
        await msg.reply_text(M.BAN_TC_ROLE_BLOCKED)
        return

    reason = targets.reason_from_args(context, update)
    if not reason or not reason.strip():
        await msg.reply_text(M.PROVIDE_BAN_REASON)
        return

    prompt = await msg.reply_text(
        M.BAN_PROOF_PROMPT, reply_markup=keyboards.proof_cancel()
    )

    key = _session_key(msg.chat.id, user.id)
    sessions = _get_sessions(context)
    if key in sessions:
        _drop_jobs(sessions.pop(key))

    app: Any = getattr(context, "application", None)
    job_queue = getattr(app, "job_queue", None) if app is not None else None
    timeout_job = None
    if job_queue is not None:
        timeout_job = job_queue.run_once(
            _timeout_session,
            when=PROOF_WAIT_SECONDS,
            data={"key": key},
            name=f"tcban_timeout_{key}",
        )

    sessions[key] = {
        "chat_id": msg.chat.id,
        "user_id": user.id,
        "user_first_name": safe_first_name(user),
        "prompt_msg_id": prompt.message_id,
        "target_id": target.id,
        "target_first_name": target.first_name,
        "reason": reason,
        "media": [],
        "media_group_id": None,
        "timeout_job": timeout_job,
        "album_job": None,
        "lock": asyncio.Lock(),
        "finalizing": False,
    }


# ------------------------------------------------------------ session control

async def on_cancel_proof(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    cq = update.callback_query
    if cq is None or cq.message is None or getattr(cq, "from_user", None) is None:
        return
    chat_id = cq.message.chat.id
    sessions = _get_sessions(context)
    from_user = getattr(cq, "from_user", None)
    if from_user is None:
        return
    key = _session_key(chat_id, from_user.id)
    sess: dict[str, Any] | None = sessions.get(key)
    if sess is None:
        await cq.answer(M.BAN_NO_ACTIVE_SESSION, show_alert=False)
        return
    if cq.message.message_id != sess["prompt_msg_id"]:
        await cq.answer()
        return

    sessions.pop(key, None)
    _drop_jobs(sess)
    await cq.answer()
    await messaging.safe_edit_callback(cq, M.BAN_OPERATION_CANCELLED, parse_mode=None)


async def on_proof_message(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Accept proof media during an active ban session."""
    msg = update.effective_message
    user = update.effective_user
    if msg is None or user is None:
        return

    sessions = _get_sessions(context)
    key = _session_key(msg.chat.id, user.id)
    sess: dict[str, Any] | None = sessions.get(key)
    if sess is None:
        return

    has_photo = bool(msg.photo)
    has_video = bool(msg.video)
    if not has_photo and not has_video:
        try:
            await msg.reply_text(M.BAN_PROOF_ONLY_MEDIA)
        except TelegramError:
            pass
        return

    if has_photo:
        kind = "photo"
        file_id = msg.photo[-1].file_id
    elif msg.video is not None:
        kind = "video"
        file_id = msg.video.file_id
    else:
        return

    sess["media"].append(
        {"kind": kind, "file_id": file_id, "media_group_id": msg.media_group_id}
    )

    if msg.media_group_id:
        sess["media_group_id"] = msg.media_group_id
        if sess.get("album_job"):
            try:
                sess["album_job"].schedule_removal()
            except Exception:
                pass
        app: Any = getattr(context, "application", None)
        job_queue = getattr(app, "job_queue", None) if app is not None else None
        if job_queue is not None:
            sess["album_job"] = job_queue.run_once(
                _finalize_job,
                when=ALBUM_DEBOUNCE_SECONDS,
                data={"key": key},
                name=f"tcban_album_{key}",
            )
    else:
        await _finalize(context, key)


async def _finalize_job(context: ContextTypes.DEFAULT_TYPE) -> None:
    job: Any = context.job
    data: Any = getattr(job, "data", None)
    if not data:
        return
    key: str = data["key"]
    await _finalize(context, key)


async def _finalize(context: ContextTypes.DEFAULT_TYPE, key: str) -> None:
    sessions = _get_sessions(context)
    sess: dict[str, Any] | None = sessions.get(key)
    if sess is None:
        return
    async with sess["lock"]:
        if sess.get("finalizing"):
            return
        sess["finalizing"] = True
    try:
        await _do_finalize(context, sess)
    finally:
        sessions.pop(key, None)
        _drop_jobs(sess)


# ----------------------------------------------------------- finalisation

async def _do_finalize(context: ContextTypes.DEFAULT_TYPE, sess: dict[str, Any]) -> None:
    """Upload proof, write the log entry, persist the ban, ack the admin."""
    target_id = sess["target_id"]
    target_first_name = sess["target_first_name"]
    admin_id = sess["user_id"]
    admin_first_name = sess["user_first_name"]
    reason = sess["reason"]
    chat_id = sess["chat_id"]
    prompt_msg_id = sess["prompt_msg_id"]
    media = sess["media"]

    existing = await bans.find_active_for_user(target_id)
    is_update = existing is not None
    now_dt = bans.now()

    if is_update:
        prev_proof_id = existing["proof_message_id"]
        original_dt: datetime = existing["timestamp"]
        previous_proof_link = (
            bans.proof_link_for(int(prev_proof_id))
            if prev_proof_id is not None
            else ""
        )
        caption = bans.caption_for_updated_ban(
            target_id=target_id,
            admin_id=admin_id,
            admin_name=admin_first_name,
            previous_proof_link=previous_proof_link,
            original_when=original_dt,
            update_when=now_dt,
        )
    else:
        original_dt = now_dt
        caption = bans.caption_for_new_ban(
            target_id=target_id,
            admin_id=admin_id,
            admin_name=admin_first_name,
            when=now_dt,
        )

    proof_message_id = await bans.post_proof_to_topic(context, media, caption)
    if proof_message_id is None:
        await messaging.safe_edit_text(
            context,
            chat_id=chat_id,
            message_id=prompt_msg_id,
            text=M.BAN_PROOF_FAILED_UPLOAD,
            parse_mode=None,
        )
        return

    proof_link = bans.proof_link_for(proof_message_id)
    me = await context.bot.get_me()
    bot_username = me.username or ""

    if is_update:
        prev_proof_link = (
            bans.proof_link_for(int(existing["proof_message_id"]))
            if existing.get("proof_message_id") is not None
            else ""
        )
        active_ban_id = existing["ban_id"]
        appeal_url = f"https://t.me/{bot_username}?start=appeal_{active_ban_id}"
        log_text = log_templates.updated_ban(
            admin_id=admin_id,
            admin_name=admin_first_name,
            previous_admin_id=existing["admin_user_id"],
            target_id=target_id,
            target_name=target_first_name,
            reason=reason,
            original_timestamp=original_dt,
            update_timestamp=now_dt,
        )
        keyboard = keyboards.ban_log_update(
            target_id=target_id,
            proof_link=proof_link,
            previous_proof_link=prev_proof_link,
            appeal_url=appeal_url,
        )
    else:
        # Provisional ban_id used for the appeal URL when this is a fresh ban.
        provisional_ban_id = f"{target_id}_{int(now_dt.timestamp())}"
        appeal_url = f"https://t.me/{bot_username}?start=appeal_{provisional_ban_id}"
        log_text = log_templates.new_ban(
            admin_id=admin_id,
            admin_name=admin_first_name,
            target_id=target_id,
            target_name=target_first_name,
            reason=reason,
            timestamp=now_dt,
        )
        keyboard = keyboards.ban_log_new(
            target_id=target_id, proof_link=proof_link, appeal_url=appeal_url
        )

    enforce_success, enforce_failure = await enforce_ban_across_groups(
        context, target_id
    )
    log_text += log_templates.enforcement_summary(
        success=enforce_success, failure=enforce_failure, action="Enforced"
    )

    log_message_id = await log_to_channel(context, log_text, reply_markup=keyboard)

    if is_update:
        await bans.persist_ban_update(
            existing=existing,
            proof_message_id=proof_message_id,
            log_message_id=log_message_id,
            admin_id=admin_id,
            reason=reason,
            update_when=now_dt,
        )
    else:
        await bans.persist_new_ban(
            target_id=target_id,
            admin_id=admin_id,
            reason=reason,
            proof_message_id=proof_message_id,
            log_message_id=log_message_id,
            when=now_dt,
        )

    await messaging.safe_edit_text(
        context,
        chat_id=chat_id,
        message_id=prompt_msg_id,
        text=M.BAN_SUCCESS.format(target_id=target_id, reason=reason),
        parse_mode=None,
    )


# ----------------------------------------------------------------- /tcunban

async def cmd_cunban(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Unban a user from Transsion Core."""
    msg = update.effective_message
    user = update.effective_user
    if msg is None or user is None:
        return

    if not await auth.require_authorized(msg, user.id):
        return

    target = await targets.resolve_or_complain(update, context, msg)
    if target is None:
        return

    if target.id == user.id:
        await msg.reply_text(M.UNBAN_SELF_BLOCKED)
        return

    record = await bans.find_active_for_user(target.id)
    if record is None:
        await msg.reply_text(M.USER_NOT_BANNED)
        return

    args = context.args or []
    if msg.reply_to_message and msg.reply_to_message.from_user:
        unban_reason = " ".join(args).strip()
    else:
        unban_reason = " ".join(args[1:]).strip()

    await bans.deactivate_ban(record["ban_id"])

    review_msg_id = record.get("review_message_id")
    if review_msg_id:
        await messaging.safe_edit_text(
            context,
            chat_id=MAIN_GROUP,
            message_id=review_msg_id,
            text=M.APPEAL_RESOLVED_ALREADY_UNBANNED,
            parse_mode=None,
        )

    enforce_success, enforce_failure = await enforce_unban_across_groups(
        context, target.id
    )

    log_text = log_templates.unban(
        admin_id=user.id,
        admin_name=safe_first_name(user),
        target_id=target.id,
        target_name=target.first_name,
        reason=unban_reason or None,
    )
    log_text += log_templates.enforcement_summary(
        success=enforce_success, failure=enforce_failure, action="Unbanned"
    )
    await log_to_channel(context, log_text)
    await msg.reply_text(M.UNBAN_SUCCESS.format(target_id=target.id))
