# © Copyright 2024 - 2026 Transsion Core
# © Copyright 2024 - 2026 Dizzy
# © Copyright 2026 Aveum Apps

"""Group mute and unmute command handlers – validates permissions and delegates to muting_flow."""

from __future__ import annotations

import logging

from telegram import Update
from telegram.ext import ContextTypes, ConversationHandler, MessageHandler

from tcbot import cfg
from tcbot import database as db
from tcbot.database.users_db import ROLE_LABEL, get_effective_role
from tcbot.modules.helper import decorators, extraction
from tcbot.modules.helper.decorators import resolve_and_check
from tcbot.modules.helper.formatter import code, mention
from tcbot.modules.helper.workflows.muting_flow import (
    _DURATION_RE,
    execute_unmute,
    fmt_duration,
    mute_conversation,
    parse_duration,
    proof,
    reason,
)
from tcbot.modules.helper.workflows.reason_flow import (
    WAITING_PROOF,
    WAITING_REASON,
    parse_inline_reason,
)
from tcbot.utils.prefixes import build_prefixed_filters, parse_cmd_args

log = logging.getLogger(__name__)


# ────────────────────── Module & Help Message ───────────────────── #

__module_name__ = "Mute"
__help_text__ = (
    "<b>Commands & Aliases</b>\n"
    "<code>/tcmute</code> (alias: <code>/tcm</code>)\n"
    "<code>/tcunmute</code> (aliases: <code>/tcunm</code>, <code>/tcum</code>)\n\n"
    "<b>Who can use it</b>\n"
    "Tester and above (Founder / Admin / Developer / Tester).\n\n"
    "<b>Where to use it</b>\n"
    "Inside any connected group.\n\n"
    "<b>What it does</b>\n"
    "<code>/tcmute</code>: restricts a user from sending messages, media, stickers, and GIFs "
    "across <b>all connected groups</b> simultaneously. "
    "After the command, the bot asks for a reason and optionally proof (photo/video) - "
    "both steps can be skipped. If the user is already muted, the existing restriction is "
    "replaced with the new duration and reason. A summary shows how many groups the mute "
    "was applied in.\n\n"
    "<code>/tcunmute</code>: restores the user's full send permissions across all connected "
    "groups. A summary shows how many groups the unmute was applied in.\n\n"
    "<b>Duration formatting</b> (optional - place before the reason):\n"
    "→ Seconds: <code>s</code>. Example: <code>30s</code> for 30 seconds.\n"
    "→ Minutes: <code>m</code>. Example: <code>15m</code> for 15 minutes.\n"
    "→ Hours: <code>h</code>. Example: <code>2h</code> for 2 hours.\n"
    "→ Days: <code>d</code>. Example: <code>7d</code> for 7 days.\n"
    "→ Weeks: <code>w</code>. Example: <code>2w</code> for 2 weeks.\n"
    "→ Months: <code>mo</code>. Example: <code>3mo</code> for 3 months.\n"
    "→ Years: <code>ye</code>. Example: <code>2ye</code> for 2 years.\n"
    "Omit a duration token to apply a permanent mute (until unmute).\n\n"
    "<b>How to specify the target</b>\n"
    "Reply to a message, or provide a user ID / @username after the command.\n\n"
    "<b>Examples</b>\n"
    "<code>/tcmute @username 3d spamming</code> - 3-day mute, reason inline\n"
    "<code>/tcm @username 1w</code> - 1-week mute, bot will ask for reason\n"
    "<code>/tcm @username</code> - permanent mute, bot walks you through it\n"
    "<code>/tcunmute @username</code> - lift mute immediately across all groups"
)


# ───────────────────── Command Mute </tcmute> ───────────────────── #


@decorators.ratelimiter(limit=5, period=60)
@decorators.basic_mod_only
@decorators.log_execution
async def cmd_mute(update: Update, ctx: ContextTypes.DEFAULT_TYPE) -> int:
    msg = update.effective_message
    admin = update.effective_user

    raw_args = parse_cmd_args(msg.text)
    has_explicit_target = bool(raw_args) and (
        raw_args[0].lstrip("-").isdigit() or raw_args[0].startswith("@")
    )
    target_id, target_fname = await extraction.extract_target(update, raw_args, ctx.bot)

    remaining_args = list(raw_args[1:] if has_explicit_target else raw_args)

    if not target_id:
        await msg.reply_text(
            "Cannot resolve target. Reply to a message or provide a user ID."
        )
        return ConversationHandler.END

    if target_id == ctx.bot.id:
        await msg.reply_text(
            "Muting me won't do much - I don't send messages on my own anyway. 😄"
        )
        return ConversationHandler.END

    if target_id == admin.id:
        await msg.reply_text("Can't mute yourself - that's not how this works. 🙃")
        return ConversationHandler.END

    _, target_role = await resolve_and_check(
        msg, admin.id, target_id, min_role="tester"
    )
    if _ is None:
        return ConversationHandler.END

    duration = None
    if remaining_args and _DURATION_RE.match(remaining_args[0]):
        duration = parse_duration(remaining_args.pop(0))

    inline_reason = parse_inline_reason(remaining_args, has_explicit_target=False)
    target_mention = mention(target_id, target_fname or str(target_id))
    dur_str = fmt_duration(duration)
    extra_info = f"{code(str(target_id))} — {dur_str}"

    ctx.user_data.update(
        {
            "mute_target_id": target_id,
            "mute_target_fname": target_fname or str(target_id),
            "mute_duration": duration,
            "mute_admin_id": admin.id,
            "mute_admin_fname": admin.first_name,
            "mute_prompt_chat": msg.chat.id,
            "mute_reason": "",
            "mute_proof_desc": None,
            "mute_extra_info": extra_info,
        }
    )

    if inline_reason:
        ctx.user_data["mute_reason"] = inline_reason
        prompt = await msg.reply_text(
            proof.noted_prompt(
                "mute", inline_reason, target_mention, extra_info=extra_info
            ),
            parse_mode="HTML",
            reply_markup=proof.keyboard(),
        )
        ctx.user_data["mute_prompt_id"] = prompt.message_id
        return WAITING_PROOF

    prompt = await msg.reply_text(
        reason.prompt(target_mention, "mute", extra_info=extra_info),
        parse_mode="HTML",
        reply_markup=reason.keyboard(),
    )
    ctx.user_data["mute_prompt_id"] = prompt.message_id
    return WAITING_REASON


# ─────────────────── Command Unmute </tcunmute> ─────────────────── #


@decorators.ratelimiter(limit=5, period=60)
@decorators.basic_mod_only
@decorators.log_execution
async def cmd_unmute(update: Update, ctx: ContextTypes.DEFAULT_TYPE) -> None:
    msg = update.effective_message
    args = parse_cmd_args(msg.text)
    target_id, target_name = await extraction.extract_target(update, args, ctx.bot)
    if not target_id:
        await msg.reply_text(
            "Specify a target - reply to a message or provide a user ID."
        )
        return

    if target_id == ctx.bot.id:
        await msg.reply_text(
            f"That's {mention(ctx.bot.id, ctx.bot.first_name or 'me')} - "
            "can't mute a bot anyway, so nothing to undo here. 😄",
            parse_mode="HTML",
        )
        return

    target_role = await get_effective_role(target_id)
    if target_role == "founder":
        fname = await db.users_db.get_first_name(target_id, "the Founder")
        await msg.reply_text(
            f"That's {mention(target_id, fname)}, the Founder - "
            "definitely not muted. Nothing to undo. 👑",
            parse_mode="HTML",
        )
        return
    if target_role in ("admin", "developer", "tester"):
        role_label = ROLE_LABEL.get(target_role, target_role)
        fname = await db.users_db.get_first_name(target_id, str(target_id))
        await msg.reply_text(
            f"Just so you know, {mention(target_id, fname)} is a {cfg.community_name} {role_label}. "
            "Proceeding with unmute anyway.",
            parse_mode="HTML",
        )

    await execute_unmute(update, ctx, target_id, target_name or str(target_id))


# ──────────────────────────── Handlers ──────────────────────────── #

_MUTE_CMDS = build_prefixed_filters("tcmute") | build_prefixed_filters("tcm")
_UNMUTE_CMDS = (
    build_prefixed_filters("tcunmute")
    | build_prefixed_filters("tcunm")
    | build_prefixed_filters("tcum")
)

__handlers__ = [
    mute_conversation(cmd_mute, _MUTE_CMDS, escape_filter=_UNMUTE_CMDS),
    MessageHandler(_UNMUTE_CMDS, cmd_unmute),
]
