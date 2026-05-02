# © Copyright 2024 - 2026 Transsion Core
# © Copyright 2024 - 2026 Dizzy
# © Copyright 2026 Aveum Apps
"""Federation statistics command."""
from __future__ import annotations

from telegram import Update
from telegram.ext import ContextTypes, MessageHandler

from tcbot import cfg, database as db
from tcbot.modules.helper.formatter import esc, mention
from tcbot.utils.prefixes import build_prefixed_filters

__module_name__ = "Stats"
__help_text__ = (
    "<b>Commands & Aliases</b>\n"
    "<code>/tcstats</code>\n\n"

    "<b>Who can use it</b>\n"
    "Anyone — no special permissions needed.\n\n"

    "<b>Where to use it</b>\n"
    "Anywhere — bot PM, exec group, or any connected group.\n\n"

    "<b>What it does</b>\n"
    "Shows a quick overview of the federation: who the founder is, "
    "how many admins are active, how many bans are in effect, "
    "and how many groups are connected.\n\n"

    "<b>Example</b>\n"
    "<code>/tcstats</code>"
)


async def cmd_stats(update: Update, ctx: ContextTypes.DEFAULT_TYPE) -> None:
    owner_id = await db.admins_db.get_owner_id()
    owner_fname = await db.users_db.get_first_name(owner_id, "Owner") if owner_id else "Unknown"
    admins = await db.admins_db.admin_count()
    bans = await db.bans_db.active_ban_count()
    groups = await db.groups_db.active_group_count()
    owner_mention = mention(owner_id, owner_fname) if owner_id else "Unknown"

    text = (
        f"<b>Stats {esc(cfg.community_name)}</b>\n\n"
        f"Founder: {owner_mention}\n"
        f"Number of admins: {admins}\n"
        f"Number of bans: {bans}\n"
        f"Number of connected chats: {groups}"
    )
    await update.effective_message.reply_text(text, parse_mode="HTML")


__handlers__ = [MessageHandler(build_prefixed_filters("tcstats"), cmd_stats)]
