# © Copyright 2024 - 2026 Transsion Core
# © Copyright 2024 - 2026 Dizzy
# © Copyright 2026 Aveum Apps
## Group mute / unmute commands
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

__module_name__ = "Mute"
__help_text__ = (
    "<b>Commands & Aliases</b>\n"
    "<code>/tcmute</code> (alias: <code>/tcm</code>)\n"
    "<code>/tcunmute</code> (alias: <code>/tcunm</code>)\n\n"

    "<b>Who can use it</b>\n"
    "Tester and above (Founder / Admin / Developer / Tester).\n\n"

    "<b>Where to use it</b>\n"
    "Inside any connected group.\n\n"

    "<b>What it does</b>\n"
    "<code>/tcmute</code>: restricts a user from sending messages in the current group. "
    "After the command, the bot will ask for a reason and optionally a proof (photo/video). "
    "You can also skip both steps. If the user is already muted, this resets the duration.\n\n"
    "<code>/tcunmute</code>: restores the user's full send permissions.\n\n"

    "<b>Duration tokens</b> (optional, place before the reason):\n"
    "<code>3s</code> seconds · <code>5m</code> minutes · <code>2h</code> hours\n"
    "<code>7d</code> days · <code>1w</code> weeks · <code>3mo</code> months · <code>2ye</code> years\n"
    "Omit duration to mute permanently.\n\n"

    "<b>How to specify the target</b>\n"
    "Reply to a message, or provide a user ID / @username.\n\n"

    "<b>Examples</b>\n"
    "<code>/tcmute @username 3d spamming</code>: mute for 3 days, reason inline\n"
    "<code>/tcm @username 1w</code>: mute for 1 week, bot will ask for reason\n"
    "<code>/tcm @username</code>: permanent mute, bot walks you through it\n"
    "<code>/tcunmute @username</code>: unmute immediately"
)


@decorators.basic_mod_only
async def cmd_unmute(update: Update, ctx: ContextTypes.DEFAULT_TYPE) -> None:
    msg  = update.effective_message
    args = parse_cmd_args(msg.text)
    target_id, target_name = await extraction.extract_target(update, args, ctx.bot)
    if not target_id:
        await msg.reply_text(
            "Specify a target — reply to a message or provide a user ID."
        )
        return

    if target_id == ctx.bot.id:
        bot_info = await ctx.bot.get_me()
        await msg.reply_text(
            f"That's {mention(ctx.bot.id, bot_info.first_name or 'me')} — "
            "can't mute a bot anyway, so nothing to undo here. 😄",
            parse_mode="HTML",
        )
        return

    target_role = await get_effective_role(target_id)
    if target_role == "founder":
        fname = await db.users_db.get_first_name(target_id, "the Founder")
        await msg.reply_text(
            f"That's {mention(target_id, fname)}, the Founder — "
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


_UNMUTE_FILTER = (
    build_prefixed_filters("tcunmute")
    | build_prefixed_filters("tcunm")
)

__handlers__ = [
    build_handler(),
    MessageHandler(_UNMUTE_FILTER, cmd_unmute),
]
