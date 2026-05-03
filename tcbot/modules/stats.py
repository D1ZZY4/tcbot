# © Copyright 2024 - 2026 Transsion Core
# © Copyright 2024 - 2026 Dizzy
# © Copyright 2026 Aveum Apps
"""Federation statistics command."""
from __future__ import annotations

import asyncio

from telegram import InlineKeyboardButton, InlineKeyboardMarkup, Update
from telegram.ext import CallbackQueryHandler, ContextTypes, MessageHandler

from tcbot import cfg, database as db
from tcbot.modules.helper.formatter import esc, mention
from tcbot.modules.helper.workflows.stats_chats_flow import handlers as _chats_handlers
from tcbot.modules.helper.workflows.stats_flow import handlers as _ban_handlers
from tcbot.utils.prefixes import build_prefixed_filters

__module_name__ = "Stats"
__help_text__ = (
    "<b>Commands & Aliases</b>\n"
    "<code>/tcstats</code>\n\n"

    "<b>Who can use it</b>\n"
    "Anyone, no special permissions needed.\n\n"

    "<b>Where to use it</b>\n"
    "Bot PM, exec group, or any connected group.\n\n"

    "<b>What it does</b>\n"
    "Shows a quick overview of the federation: who the founder is, "
    "how many staff members are active across all roles, "
    "how many bans are in effect, and how many groups are connected.\n"
    "Tap <b>Staff Roster</b> to see the full breakdown by role.\n\n"

    "<b>Example</b>\n"
    "<code>/tcstats</code>"
)


def _stats_kb() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup([
        [InlineKeyboardButton("Staff Roster",    callback_data="stats_admins")],
        [InlineKeyboardButton("Connected Chats", callback_data="stats_chats:0")],
        [InlineKeyboardButton("User Bans",       callback_data="stats_bans:0")],
    ])


def _simple_back_kb() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup([
        [InlineKeyboardButton("Back", callback_data="stats_main")],
    ])


async def _stats_text() -> str:
    (owner_id, admin_cnt, dev_list, tester_list,
     bans, groups) = await asyncio.gather(
        db.admins_db.get_owner_id(),
        db.admins_db.admin_count(),
        db.roles_db.all_by_role("developer"),
        db.roles_db.all_by_role("tester"),
        db.bans_db.active_ban_count(),
        db.groups_db.active_group_count(),
    )
    owner_fname   = await db.users_db.get_first_name(owner_id, "Owner") if owner_id else "Unknown"
    owner_mention = mention(owner_id, owner_fname) if owner_id else "Unknown"
    staff_total   = 1 + admin_cnt + len(dev_list) + len(tester_list)
    return (
        f"<b>Stats — {esc(cfg.community_name)}</b>\n\n"
        f"Founder: {owner_mention}\n"
        f"Staff: {staff_total} total\n"
        f"Active bans: {bans}\n"
        f"Connected chats: {groups}"
    )


async def cmd_stats(update: Update, ctx: ContextTypes.DEFAULT_TYPE) -> None:
    text = await _stats_text()
    await update.effective_message.reply_text(text, parse_mode="HTML", reply_markup=_stats_kb())


async def on_stats_main(update: Update, ctx: ContextTypes.DEFAULT_TYPE) -> None:
    q = update.callback_query
    await q.answer()
    text = await _stats_text()
    await q.edit_message_text(text, parse_mode="HTML", reply_markup=_stats_kb())


async def on_stats_admins(update: Update, ctx: ContextTypes.DEFAULT_TYPE) -> None:
    q = update.callback_query
    await q.answer()

    owner_id, admins, developers, testers = await asyncio.gather(
        db.admins_db.get_owner_id(),
        db.admins_db.all_admins(),
        db.roles_db.all_by_role("developer"),
        db.roles_db.all_by_role("tester"),
    )

    lines: list[str] = [f"<b>Staff Roster — {esc(cfg.community_name)}</b>\n"]

    ## Founder
    if owner_id:
        fname = await db.users_db.get_first_name(owner_id, "Founder")
        lines.append("<b>Founder</b>")
        lines.append(f"— {mention(owner_id, fname)}\n")

    ## Admins
    lines.append(f"<b>Admins ({len(admins)})</b>")
    if admins:
        for adm in admins:
            fname = await db.users_db.get_first_name(adm["user_id"], str(adm["user_id"]))
            lines.append(f"— {mention(adm['user_id'], fname)}")
    else:
        lines.append("— None assigned")
    lines.append("")

    ## Developers
    lines.append(f"<b>Developers ({len(developers)})</b>")
    if developers:
        for dev in developers:
            fname = await db.users_db.get_first_name(dev["user_id"], str(dev["user_id"]))
            lines.append(f"— {mention(dev['user_id'], fname)}")
    else:
        lines.append("— None assigned")
    lines.append("")

    ## Testers
    lines.append(f"<b>Testers ({len(testers)})</b>")
    if testers:
        for tst in testers:
            fname = await db.users_db.get_first_name(tst["user_id"], str(tst["user_id"]))
            lines.append(f"— {mention(tst['user_id'], fname)}")
    else:
        lines.append("— None assigned")

    await q.edit_message_text(
        "\n".join(lines), parse_mode="HTML",
        reply_markup=_simple_back_kb(),
    )


__handlers__ = [
    MessageHandler(build_prefixed_filters("tcstats"), cmd_stats),
    CallbackQueryHandler(on_stats_main,   pattern=r"^stats_main$"),
    CallbackQueryHandler(on_stats_admins, pattern=r"^stats_admins$"),
    *_chats_handlers,
    *_ban_handlers,
]
