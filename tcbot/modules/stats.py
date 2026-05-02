# © Copyright 2024 - 2026 Transsion Core
# © Copyright 2024 - 2026 Dizzy
# © Copyright 2026 Aveum Apps
"""Federation statistics command."""
from __future__ import annotations

from telegram import InlineKeyboardButton, InlineKeyboardMarkup, Update
from telegram.ext import CallbackQueryHandler, ContextTypes, MessageHandler, filters

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
_SEARCH_KEY = "stats_bans_search"


# ---------------------------------------------------------------------------
# Keyboards
# ---------------------------------------------------------------------------

def _stats_kb() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup([
        [InlineKeyboardButton("Admins/Staff",    callback_data="stats_admins")],
        [InlineKeyboardButton("Connected Chats", callback_data="stats_chats")],
        [InlineKeyboardButton("User Bans",       callback_data="stats_bans:0")],
    ])


def _simple_back_kb() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup([
        [InlineKeyboardButton("Back", callback_data="stats_main")],
    ])


def _bans_kb(page: int, total_pages: int) -> InlineKeyboardMarkup:
    rows = []
    nav = []
    if page > 0:
        nav.append(InlineKeyboardButton("Prev", callback_data=f"stats_bans:{page - 1}"))
    if page < total_pages - 1:
        nav.append(InlineKeyboardButton("Next", callback_data=f"stats_bans:{page + 1}"))
    if nav:
        rows.append(nav)
    rows.append([InlineKeyboardButton("Search", callback_data="stats_bans_search")])
    rows.append([InlineKeyboardButton("Back",   callback_data="stats_main")])
    return InlineKeyboardMarkup(rows)


# ---------------------------------------------------------------------------
# Shared helpers
# ---------------------------------------------------------------------------

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


# ---------------------------------------------------------------------------
# Handlers
# ---------------------------------------------------------------------------

async def cmd_stats(update: Update, ctx: ContextTypes.DEFAULT_TYPE) -> None:
    text = await _stats_text()
    await update.effective_message.reply_text(text, parse_mode="HTML", reply_markup=_stats_kb())


async def on_stats_main(update: Update, ctx: ContextTypes.DEFAULT_TYPE) -> None:
    q = update.callback_query
    await q.answer()
    ctx.user_data.pop(_SEARCH_KEY, None)
    text = await _stats_text()
    await q.edit_message_text(text, parse_mode="HTML", reply_markup=_stats_kb())


async def on_stats_admins(update: Update, ctx: ContextTypes.DEFAULT_TYPE) -> None:
    q = update.callback_query
    await q.answer()

    admins = await db.admins_db.all_admins()
    lines = [f"<b>Admins/Staff ({len(admins)})</b>\n"]
    for adm in admins:
        fname = await db.users_db.get_first_name(adm["user_id"], str(adm["user_id"]))
        lines.append(f"- {fname} {code(str(adm['user_id']))}")

    await q.edit_message_text(
        "\n".join(lines), parse_mode="HTML",
        reply_markup=_simple_back_kb(),
    )


async def on_stats_chats(update: Update, ctx: ContextTypes.DEFAULT_TYPE) -> None:
    q = update.callback_query
    await q.answer()

    groups = await db.groups_db.active_groups()
    lines = [f"<b>Connected Chats ({len(groups)})</b>\n"]
    for grp in groups:
        lines.append(f"- {esc(grp['title'])} {code(str(grp['chat_id']))}")

    await q.edit_message_text(
        "\n".join(lines), parse_mode="HTML",
        reply_markup=_simple_back_kb(),
    )


async def on_stats_bans(update: Update, ctx: ContextTypes.DEFAULT_TYPE) -> None:
    q = update.callback_query
    await q.answer()
    page = int(q.data.split(":")[1])

    bans = await db.bans_db.active_bans()
    total = len(bans)
    total_pages = max(1, (total + _PAGE_SIZE - 1) // _PAGE_SIZE)
    chunk = bans[page * _PAGE_SIZE: (page + 1) * _PAGE_SIZE]

    lines = [f"<b>User Bans ({total})</b>\n"]
    for ban in chunk:
        uid = ban["banned_user_id"]
        fname = await db.users_db.get_first_name(uid, str(uid))
        lines.append(f"- {esc(fname)} {code(str(uid))}")

    await q.edit_message_text(
        "\n".join(lines), parse_mode="HTML",
        reply_markup=_bans_kb(page, total_pages),
    )


async def on_stats_bans_search(update: Update, ctx: ContextTypes.DEFAULT_TYPE) -> None:
    q = update.callback_query
    await q.answer("Send me a name or user ID to search", show_alert=True)
    ctx.user_data[_SEARCH_KEY] = True


async def on_bans_search_input(update: Update, ctx: ContextTypes.DEFAULT_TYPE) -> None:
    if not ctx.user_data.get(_SEARCH_KEY):
        return
    ctx.user_data.pop(_SEARCH_KEY, None)

    query = update.effective_message.text.strip().lower()
    bans = await db.bans_db.active_bans()

    results = []
    for ban in bans:
        uid = ban["banned_user_id"]
        if query.isdigit() and str(uid) == query:
            results.append(ban)
        elif not query.isdigit():
            fname = await db.users_db.get_first_name(uid, "")
            if query in fname.lower():
                results.append(ban)

    if not results:
        await update.effective_message.reply_text(
            f"No banned user found matching <code>{esc(query)}</code>.",
            parse_mode="HTML",
            reply_markup=InlineKeyboardMarkup([
                [InlineKeyboardButton("Back to Bans", callback_data="stats_bans:0")],
            ]),
        )
        return

    lines = [f"<b>Search results for \"{esc(query)}\" ({len(results)})</b>\n"]
    for ban in results:
        uid = ban["banned_user_id"]
        fname = await db.users_db.get_first_name(uid, str(uid))
        lines.append(f"- {esc(fname)} {code(str(uid))}")

    await update.effective_message.reply_text(
        "\n".join(lines), parse_mode="HTML",
        reply_markup=InlineKeyboardMarkup([
            [InlineKeyboardButton("Back to Bans", callback_data="stats_bans:0")],
        ]),
    )


__handlers__ = [
    MessageHandler(build_prefixed_filters("tcstats"), cmd_stats),
    CallbackQueryHandler(on_stats_main,         pattern=r"^stats_main$"),
    CallbackQueryHandler(on_stats_admins,        pattern=r"^stats_admins$"),
    CallbackQueryHandler(on_stats_chats,         pattern=r"^stats_chats$"),
    CallbackQueryHandler(on_stats_bans,          pattern=r"^stats_bans:\d+$"),
    CallbackQueryHandler(on_stats_bans_search,   pattern=r"^stats_bans_search$"),
    MessageHandler(filters.TEXT & ~filters.COMMAND, on_bans_search_input),
]
