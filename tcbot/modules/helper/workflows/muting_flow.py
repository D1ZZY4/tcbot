# © Copyright 2024 - 2026 Transsion Core
# © Copyright 2024 - 2026 Dizzy
# © Copyright 2026 Aveum Apps
"""Mute/unmute executor helpers — duration parsing and direct restrict/unrestrict calls."""
from __future__ import annotations

import logging
import re
from datetime import datetime, timedelta, timezone

from telegram import ChatPermissions, Update
from telegram.ext import ContextTypes

from tcbot import database as db
from tcbot.modules.helper.formatter import code, mention

log = logging.getLogger(__name__)

_DURATION_RE = re.compile(r"^(\d+)(ye|mo|[smhdw])$", re.IGNORECASE)


## ---------------------------------------------------------------------------
## Duration helpers
## ---------------------------------------------------------------------------

def parse_duration(raw: str) -> timedelta | None:
    """Parse a single duration token like '3d', '1mo', '2ye'. Returns None if invalid."""
    m = _DURATION_RE.match(raw.strip())
    if not m:
        return None
    value = int(m.group(1))
    unit  = m.group(2).lower()
    mapping = {
        "s":  timedelta(seconds=value),
        "m":  timedelta(minutes=value),
        "h":  timedelta(hours=value),
        "d":  timedelta(days=value),
        "w":  timedelta(weeks=value),
        "mo": timedelta(days=value * 30),
        "ye": timedelta(days=value * 365),
    }
    return mapping.get(unit)


def fmt_duration(td: timedelta | None) -> str:
    """Human-readable duration string for use in replies."""
    if td is None:
        return "permanently"
    total = int(td.total_seconds())
    if total < 60:
        return f"{total}s"
    if total < 3600:
        return f"{total // 60}m"
    if total < 86400:
        return f"{total // 3600}h"
    days = total // 86400
    if days < 7:
        return f"{days}d"
    if days < 30:
        return f"{days // 7}w"
    if days < 365:
        return f"{days // 30}mo"
    return f"{days // 365}ye"


## ---------------------------------------------------------------------------
## Core execution
## ---------------------------------------------------------------------------

async def _execute_mute(bot, update: Update, meta: dict) -> None:
    """Apply the mute and edit the conversation prompt to a summary."""
    target_id    = meta["mute_target_id"]
    target_fname = meta["mute_target_fname"]
    reason       = meta.get("mute_reason") or "No reason provided"
    admin_id     = meta["mute_admin_id"]
    duration     = meta.get("mute_duration")
    proof_desc   = meta.get("mute_proof_desc")
    prompt_chat  = meta.get("mute_prompt_chat")
    prompt_id    = meta.get("mute_prompt_id")
    dur_str      = fmt_duration(duration)

    chat_id = update.effective_chat.id
    until   = datetime.now(timezone.utc) + duration if duration else None

    try:
        await bot.restrict_chat_member(
            chat_id, target_id,
            permissions=ChatPermissions(can_send_messages=False),
            until_date=until,
        )
        await db.mutes_db.log_mute(target_id, chat_id, reason, admin_id)
    except Exception as exc:
        log.error("Mute failed for %s in %s: %s", target_id, chat_id, exc)
        try:
            await bot.edit_message_text(
                f"Failed to mute {mention(target_id, target_fname)}: {exc}",
                chat_id=prompt_chat, message_id=prompt_id, parse_mode="HTML",
            )
        except Exception:
            pass
        return

    proof_line = f"\nProof: {proof_desc}" if proof_desc else ""
    summary = (
        f"{mention(target_id, target_fname)} {code(str(target_id))} "
        f"has been muted <b>{dur_str}</b>.\n"
        f"Reason: {reason}"
        f"{proof_line}"
    )

    try:
        await bot.edit_message_text(
            summary,
            chat_id=prompt_chat, message_id=prompt_id,
            parse_mode="HTML", reply_markup=None,
        )
    except Exception:
        msg = update.effective_message
        if msg:
            await msg.reply_text(summary, parse_mode="HTML")


## ---------------------------------------------------------------------------
## Unmute execution
## ---------------------------------------------------------------------------

async def execute_unmute(
    update: Update,
    ctx: ContextTypes.DEFAULT_TYPE,
    target_id: int,
    target_name: str,
) -> None:
    msg     = update.effective_message
    chat_id = update.effective_chat.id
    try:
        await ctx.bot.restrict_chat_member(
            chat_id, target_id,
            permissions=ChatPermissions(
                can_send_messages=True,
                can_send_polls=True,
                can_send_other_messages=True,
                can_add_web_page_previews=True,
                can_change_info=False,
                can_invite_users=True,
                can_pin_messages=False,
            ),
        )
        await msg.reply_text(
            f"{mention(target_id, target_name)} {code(str(target_id))} has been unmuted.",
            parse_mode="HTML",
        )
    except Exception as exc:
        log.error("Unmute failed for %s in %s: %s", target_id, chat_id, exc)
        await msg.reply_text(
            f"Failed to unmute {mention(target_id, target_name)}: {exc}",
            parse_mode="HTML",
        )
