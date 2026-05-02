# © Copyright 2024 - 2026 Transsion Core
# © Copyright 2024 - 2026 Dizzy
# © Copyright 2026 Aveum Apps
"""Federation statistics command."""
from __future__ import annotations

from telegram import InlineKeyboardButton, InlineKeyboardMarkup, Update
from telegram.ext import CallbackQueryHandler, ContextTypes, MessageHandler

from tcbot import cfg, database as db
from tcbot.modules.helper.formatter import code, esc, mention
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

_PAGE_SIZE = 10


def _stats_kb() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup([
        [InlineKeyboardButton("Admins/Staff",    callback_data="stats_admins:0")],
        [InlineKeyboardButton("Connected Chats", callback_data="stats_chats:0")],
    ])


def _back_kb(prefix: str, page: int, total_pages: int) -> InlineKeyboardMarkup:
    rows = []
    nav = []
    if page > 0:
        nav.append(InlineKeyboardButton("Prev", callback_data=f"{prefix}:{page - 1}"))
    if page < total_pages - 1:
        nav.append(InlineKeyboardButton("Next", callback_data=f"{prefix}:{page + 1}"))
    if nav:
        rows.append(nav)
    rows.append([InlineKeyboardButton("Back", callback_data="stats_main")])
    return InlineKeyboardMarkup(rows)


async def _stats_text() -> str:
    owner_id = await db.admins_db.get_owner_id()
    owner_fname = await db.users_db.get_first_name(owner_id, "Owner") if owner_id else "Unknown"
    admins = await db.admins_db.admin_count()
    bans = await db.bans_db.active_ban_count()
    groups = await db.groups_db.active_group_count()
    owner_mention = mention(owner_id, owner_fname) if owner_id else "Unknown"
    return (
        f"<b>Stats {esc(cfg.community_name)}</b>\n\n"
        f"Founder: {owner_mention}\n"
        f"Number of admins: {admins}\n"
        f"Number of bans: {bans}\n"
        f"Number of connected chats: {groups}"
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
    page = int(q.data.split(":")[1])

    admins = await db.admins_db.all_admins()
    total = len(admins)
    total_pages = max(1, (total + _PAGE_SIZE - 1) // _PAGE_SIZE)
    chunk = admins[page * _PAGE_SIZE: (page + 1) * _PAGE_SIZE]

    lines = [f"<b>Admins/Staff ({total})</b>\n"]
    for adm in chunk:
        fname = await db.users_db.get_first_name(adm["user_id"], str(adm["user_id"]))
        lines.append(f"- {fname} {code(str(adm['user_id']))}")

    await q.edit_message_text(
        "\n".join(lines), parse_mode="HTML",
        reply_markup=_back_kb("stats_admins", page, total_pages),
    )


async def on_stats_chats(update: Update, ctx: ContextTypes.DEFAULT_TYPE) -> None:
    q = update.callback_query
    await q.answer()
    page = int(q.data.split(":")[1])

    groups = await db.groups_db.active_groups()
    total = len(groups)
    total_pages = max(1, (total + _PAGE_SIZE - 1) // _PAGE_SIZE)
    chunk = groups[page * _PAGE_SIZE: (page + 1) * _PAGE_SIZE]

    lines = [f"<b>Connected Chats ({total})</b>\n"]
    for grp in chunk:
        lines.append(f"- {esc(grp['title'])} {code(str(grp['chat_id']))}")

    await q.edit_message_text(
        "\n".join(lines), parse_mode="HTML",
        reply_markup=_back_kb("stats_chats", page, total_pages),
    )


__handlers__ = [
    MessageHandler(build_prefixed_filters("tcstats"), cmd_stats),
    CallbackQueryHandler(on_stats_main,   pattern=r"^stats_main$"),
    CallbackQueryHandler(on_stats_admins, pattern=r"^stats_admins:\d+$"),
    CallbackQueryHandler(on_stats_chats,  pattern=r"^stats_chats:\d+$"),
]
