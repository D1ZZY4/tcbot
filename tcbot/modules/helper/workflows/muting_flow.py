# © Copyright 2024 - 2026 Transsion Core
# © Copyright 2024 - 2026 Dizzy
# © Copyright 2026 Ave Studio

"""Mute/unmute executor + conversation factory."""

from __future__ import annotations

import asyncio
import logging
import re
from datetime import timedelta
from typing import TYPE_CHECKING, Any

from telegram import Bot, ChatPermissions, Update

from tcbot import cfg
from tcbot import database as db
from tcbot.modules.helper import parse_logmsg, replies
from tcbot.modules.helper.formatter import (
    bold,
    esc,
    proof_line,
    user_ref,
)
from tcbot.modules.helper.workflows.proof_flow import BuildProof
from tcbot.modules.helper.workflows.reason_flow import BuildReason, build_modaction_conv
from tcbot.utils.dispatch import count_errors, fan_out
from tcbot.utils.timedate_format import utc_now

if TYPE_CHECKING:
    from collections.abc import Callable

    from telegram.ext import ContextTypes
    from telegram.ext.filters import BaseFilter

log = logging.getLogger(__name__)

_DURATION_RE = re.compile(r"^(\d+)(ye|mo|[smhdw])$", re.IGNORECASE)

# * Time-math constants for fmt_duration and parse_duration.
_SECS_PER_HOUR: int = 3_600
_SECS_PER_DAY: int = 86_400
_DAYS_PER_YEAR: int = 365

# * Per-action BuildReason and BuildProof instances; imported by muting.py
reason = BuildReason("mute")
proof = BuildProof("mute")


# ──────────────────────── Duration helpers ──────────────────────── #


def parse_duration(raw: str) -> timedelta | None:
    """Parse a single duration token like '3d', '1mo', '2ye'. Returns None if invalid."""
    m = _DURATION_RE.match(raw.strip())
    if not m:
        return None
    value = int(m.group(1))
    unit = m.group(2).lower()
    mapping = {
        "s": timedelta(seconds=value),
        "m": timedelta(minutes=value),
        "h": timedelta(hours=value),
        "d": timedelta(days=value),
        "w": timedelta(weeks=value),
        "mo": timedelta(days=value * 30),
        "ye": timedelta(days=value * _DAYS_PER_YEAR),
    }
    return mapping.get(unit)


def fmt_duration(td: timedelta | None) -> str:
    """Human-readable duration string for use in replies."""
    if td is None:
        return "permanently"
    total = int(td.total_seconds())
    if total < 60:
        return f"{total}s"
    if total < _SECS_PER_HOUR:
        return f"{total // 60}m"
    if total < _SECS_PER_DAY:
        return f"{total // _SECS_PER_HOUR}h"
    days = total // _SECS_PER_DAY
    if days < 7:
        return f"{days}d"
    if days < 30:
        return f"{days // 7}w"
    if days < _DAYS_PER_YEAR:
        return f"{days // 30}mo"
    return f"{days // _DAYS_PER_YEAR}ye"


# ────────────────────────── Mute executor ───────────────────────── #


async def _execute_mute(bot: Bot, update: Update, meta: dict) -> None:
    """Apply a federation-wide mute across all connected groups and edit the prompt to a summary."""
    target_id = meta["mute_target_id"]
    target_fname = meta["mute_target_fname"]
    reason_text = meta.get("mute_reason") or replies.NO_REASON
    admin_id = meta["mute_admin_id"]
    duration = meta.get("mute_duration")
    proof_desc = meta.get("mute_proof_desc")
    prompt_chat = meta.get("mute_prompt_chat")
    prompt_id = meta.get("mute_prompt_id")
    dur_str = fmt_duration(duration)

    until = utc_now() + duration if duration else None
    perms = ChatPermissions(can_send_messages=False)
    duration_secs = int(duration.total_seconds()) if duration else None

    # * Apply across all connected groups + primary groups - semaphore-bounded
    groups = await db.groups_db.active_groups()
    _primary_ids = [cid for cid in (cfg.main_group, cfg.exec_group) if cid]
    _existing_ids = {grp["chat_id"] for grp in groups}
    groups = groups + [
        {"chat_id": pid, "title": ""}
        for pid in _primary_ids
        if pid not in _existing_ids
    ]
    results = await fan_out(
        [
            bot.restrict_chat_member(
                grp["chat_id"],
                target_id,
                permissions=perms,
                until_date=until,
            )
            for grp in groups
        ]
    )
    failed = count_errors(results)

    proof_suffix = proof_line(proof_desc)
    summary = (
        f"{user_ref(target_id, target_fname)} "
        f"has been muted {bold(dur_str)}.\n"
        f"Reason: {esc(reason_text)}"
        f"{proof_suffix}\n"
        f"Applied to {len(groups) - failed}/{len(groups)} groups."
    )

    admin_fname = meta.get("mute_admin_fname", "Admin")
    lc, lt = cfg.logs
    log_text = parse_logmsg.mute_log(
        target_id,
        target_fname,
        admin_id,
        admin_fname,
        reason_text,
        dur_str,
    )

    # * Log to DB, post to log channel, and edit summary - all in parallel
    chat_id = update.effective_chat.id
    results2 = await asyncio.gather(
        db.mutes_db.log_mute(
            target_id, chat_id, reason_text, admin_id, duration_secs=duration_secs
        ),
        bot.send_message(lc, log_text, parse_mode="HTML", message_thread_id=lt),
        bot.edit_message_text(
            summary,
            chat_id=prompt_chat,
            message_id=prompt_id,
            parse_mode="HTML",
            reply_markup=None,
        ),
        return_exceptions=True,
    )
    if isinstance(results2[0], BaseException):
        log.error("log_mute DB write failed for target=%d: %s", target_id, results2[0])
    if isinstance(results2[1], BaseException):
        log.error("Mute log send failed: %s", results2[1])
    if isinstance(results2[2], BaseException):
        msg = update.effective_message
        if msg:
            try:
                await msg.reply_text(summary, parse_mode="HTML")
            except Exception as exc:
                log.debug("Mute summary fallback reply failed: %s", exc)


# ───────────────────────── Unmute executor ──────────────────────── #


async def execute_unmute(
    update: Update,
    ctx: ContextTypes.DEFAULT_TYPE,
    target_id: int,
    target_name: str,
) -> None:
    """Restore full send permissions across all connected groups."""
    msg = update.effective_message
    full_perms = ChatPermissions(
        can_send_messages=True,
        can_send_polls=True,
        can_send_other_messages=True,
        can_add_web_page_previews=True,
        can_change_info=False,
        can_invite_users=True,
        can_pin_messages=False,
    )

    # * Unrestrict across all connected groups + primary groups - semaphore-bounded
    groups = await db.groups_db.active_groups()
    _pri_ids = [cid for cid in (cfg.main_group, cfg.exec_group) if cid]
    _ex_ids = {grp["chat_id"] for grp in groups}
    groups = groups + [
        {"chat_id": pid, "title": ""} for pid in _pri_ids if pid not in _ex_ids
    ]
    results = await fan_out(
        [
            ctx.bot.restrict_chat_member(
                grp["chat_id"],
                target_id,
                permissions=full_perms,
            )
            for grp in groups
        ]
    )
    failed = count_errors(results)

    admin = update.effective_user
    lc, lt = cfg.logs
    log_text = parse_logmsg.unmute_log(
        target_id,
        target_name,
        admin.id,
        admin.first_name,
    )

    reply = (
        f"{user_ref(target_id, target_name)} has been unmuted - "
        f"restored in {len(groups) - failed}/{len(groups)} groups."
    )

    # * Send log to channel and reply in parallel
    if lc:
        results2 = await asyncio.gather(
            ctx.bot.send_message(lc, log_text, parse_mode="HTML", message_thread_id=lt),
            msg.reply_text(reply, parse_mode="HTML"),
            return_exceptions=True,
        )
        if isinstance(results2[0], BaseException):
            log.error("Unmute log send failed: %s", results2[0])
    else:
        try:
            await msg.reply_text(reply, parse_mode="HTML")
        except Exception as exc:
            log.debug("execute_unmute no-log reply failed: %s", exc)


# ──────────────────────── Executor adapter ──────────────────────── #


async def _exec_mute(update: Update, ctx: ContextTypes.DEFAULT_TYPE) -> None:
    """Copy mute data from user_data, clean up, then call _execute_mute."""
    meta = {k: v for k, v in ctx.user_data.items() if k.startswith("mute_")}
    for k in list(meta):
        ctx.user_data.pop(k, None)
    await _execute_mute(ctx.bot, update, meta)


# ─────────────────── ConversationHandler factory ────────────────── #


def mute_conversation(
    entry_fn: Callable[..., Any],
    entry_filter: BaseFilter,
    *,
    escape_filter: BaseFilter | None = None,
) -> object:
    """Return the mute ConversationHandler via the central reason_flow factory."""
    return build_modaction_conv(
        reason,
        proof,
        entry_fn,
        _exec_mute,
        entry_filter,
        escape_filter=escape_filter,
    )
