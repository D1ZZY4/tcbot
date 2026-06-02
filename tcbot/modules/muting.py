# © Copyright 2024 - 2026 Transsion Core
# © Copyright 2024 - 2026 Dizzy
# © Copyright 2026 Aveum Apps

"""Group mute and unmute command handlers: validates permissions and delegates to muting_flow."""

from __future__ import annotations

import asyncio
import logging

from telegram import Update
from telegram.ext import ContextTypes, ConversationHandler, MessageHandler

from tcbot import cfg
from tcbot.modules.helper import decorators, extraction, identity
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
    "Federation-wide mute and unmute: restricts a user from sending messages "
    "across <b>all connected groups</b> at once."
)

__help_sections__: list[tuple[str, str]] = [
    (
        "Commands & Aliases",
        "<code>/tcmute</code> (alias: <code>/tcm</code>)\n"
        "<code>/tcunmute</code> (aliases: <code>/tcunm</code>, <code>/tcum</code>)",
    ),
    (
        "Who can use",
        "Tester and above (Founder / Admin / Developer / Tester).",
    ),
    (
        "Where to use",
        "Inside any connected group.",
    ),
    (
        "What it does",
        "<b>/tcmute</b>: restricts a user from sending messages, media, stickers, and GIFs "
        "across <b>all connected groups</b> simultaneously. After the command, the bot "
        "asks for a reason and optionally proof - both steps can be skipped. If the user "
        "is already muted, the existing restriction is replaced. A summary shows how many "
        "groups the mute was applied in.\n\n"
        "<b>/tcunmute</b>: restores the user's full send permissions across all connected "
        "groups. A summary shows how many groups the unmute was applied in.",
    ),
    (
        "Time format",
        "Place the duration before the reason. Omit a duration to apply a permanent mute.\n\n"
        "→ <code>s</code> Seconds: <code>30s</code> = 30 seconds\n"
        "→ <code>m</code> Minutes: <code>15m</code> = 15 minutes\n"
        "→ <code>h</code> Hours: <code>2h</code> = 2 hours\n"
        "→ <code>d</code> Days: <code>7d</code> = 7 days\n"
        "→ <code>w</code> Weeks: <code>2w</code> = 2 weeks\n"
        "→ <code>mo</code> Months: <code>3mo</code> = 3 months\n"
        "→ <code>ye</code> Years: <code>2ye</code> = 2 years",
    ),
    (
        "Target syntax",
        "Reply to a message, or provide a user ID / @username after the command.",
    ),
    (
        "Examples",
        "<code>/tcmute @username 3d spamming</code>: 3-day mute, reason inline\n"
        "<code>/tcm @username 1w</code>: 1-week mute, bot will ask for reason\n"
        "<code>/tcm @username</code>: permanent mute, bot walks you through it\n"
        "<code>/tcunmute @username</code>: lift mute immediately across all groups",
    ),
]


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

    ident, (executor_role, target_role) = await asyncio.gather(
        identity.classify(ctx.bot, admin.id, target_id, target_fname),
        resolve_and_check(msg, admin.id, target_id, min_role="tester"),
    )
    refusal = identity.refuse_message("mute", ident)
    if refusal is not None:
        await msg.reply_text(refusal, parse_mode="HTML")
        return ConversationHandler.END

    if executor_role is None:
        return ConversationHandler.END

    duration = None
    if remaining_args and _DURATION_RE.match(remaining_args[0]):
        duration = parse_duration(remaining_args.pop(0))

    inline_reason = parse_inline_reason(remaining_args, has_explicit_target=False)
    target_mention = mention(target_id, target_fname or str(target_id))
    dur_str = fmt_duration(duration)
    extra_info = f"{code(str(target_id))}: {dur_str}"

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
    admin = update.effective_user
    args = parse_cmd_args(msg.text)
    target_id, target_name = await extraction.extract_target(update, args, ctx.bot)
    if not target_id:
        await msg.reply_text(
            "Specify a target - reply to a message or provide a user ID."
        )
        return

    ident = await identity.classify(ctx.bot, admin.id, target_id, target_name)
    refusal = identity.refuse_message("unmute", ident)
    if refusal is not None:
        await msg.reply_text(refusal, parse_mode="HTML")
        return

    notice = identity.staff_notice("unmute", ident, cfg.community_name)
    if notice is not None:
        await msg.reply_text(notice, parse_mode="HTML")

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
