# © Copyright 2024 - 2026 Transsion Core
# © Copyright 2024 - 2026 Dizzy
# © Copyright 2026 Aveum Apps

from __future__ import annotations

from telegram import Update
from telegram.ext import ContextTypes, MessageHandler

from tcbot import cfg, database as db
from tcbot.database.roles_db import ROLE_LABEL, get_effective_role
from tcbot.modules.helper import decorators, extraction
from tcbot.modules.helper.formatter import mention
from tcbot.modules.helper.workflows.muting_conv import build_handler
from tcbot.modules.helper.workflows.muting_flow import execute_unmute
from tcbot.utils.prefixes import build_prefixed_filters, parse_cmd_args


## ── Module & Help ─────────────────────────────────────────────────────────

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

    "<b>Duration tokens</b> (optional - place before the reason):\n"
    "<code>3s</code> seconds · <code>5m</code> minutes · <code>2h</code> hours\n"
    "<code>7d</code> days · <code>1w</code> weeks · <code>3mo</code> months · <code>2ye</code> years\n"
    "Omit a duration token to apply a permanent mute.\n\n"

    "<b>How to specify the target</b>\n"
    "Reply to a message, or provide a user ID / @username after the command.\n\n"

    "<b>Examples</b>\n"
    "<code>/tcmute @username 3d spamming</code> - 3-day mute, reason inline\n"
    "<code>/tcm @username 1w</code> - 1-week mute, bot will ask for reason\n"
    "<code>/tcm @username</code> - permanent mute, bot walks you through it\n"
    "<code>/tcunmute @username</code> - lift mute immediately across all groups"
)


## ── /tcunmute command ──────────────────────────────────────────────────────

@decorators.ratelimiter(limit=5, period=60)
@decorators.basic_mod_only
@decorators.log_execution
async def cmd_unmute(update: Update, ctx: ContextTypes.DEFAULT_TYPE) -> None:
    msg  = update.effective_message
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
        fname      = await db.users_db.get_first_name(target_id, str(target_id))
        await msg.reply_text(
            f"Just so you know, {mention(target_id, fname)} is a {cfg.community_name} {role_label}. "
            "Proceeding with unmute anyway.",
            parse_mode="HTML",
        )

    await execute_unmute(update, ctx, target_id, target_name or str(target_id))


## ── Handlers ───────────────────────────────────────────────────────────────

_UNMUTE_FILTER = (
    build_prefixed_filters("tcunmute")
    | build_prefixed_filters("tcunm")
    | build_prefixed_filters("tcum")
)

__handlers__ = [
    build_handler(),
    MessageHandler(_UNMUTE_FILTER, cmd_unmute),
]
