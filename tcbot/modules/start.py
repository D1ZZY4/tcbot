# © Copyright 2024 - 2026 Transsion Core
# © Copyright 2024 - 2026 Dizzy
# © Copyright 2026 Aveum Apps
"""Start command, full interactive menu, and help system."""
from __future__ import annotations

import logging

from telegram import CallbackQuery, InlineKeyboardButton, InlineKeyboardMarkup, Update
from telegram.ext import CallbackQueryHandler, ContextTypes, MessageHandler, filters

from tcbot import database as db
from tcbot.config import cfg
from tcbot.modules.helper import keyboards
from tcbot.modules.helper.formatter import code, esc, mention
from tcbot.utils.prefixes import build_prefixed_filters

log = logging.getLogger(__name__)

__module_name__ = None

_PAGE_SIZE = 10

_MENU_TEXT = (
    "<b>Hey There! My Name is TC-Bot.</b>\n"
    "I help manage Transsion Core groups, bans, and appeals. "
    "Use the buttons below to learn more or view important links."
)

_ABOUT_TEXT = (
    "<b>What is TCF?</b>\n"
    "Transsion Core Federation (TCF) is a community-driven federation for Infinix, Tecno, and Itel groups. "
    "Our main focus is maintaining group security and a conducive environment so members can discuss comfortably.\n"
    "<i>TCF is not an official part of Transsion Holdings. This is strictly an independent community.</i>\n\n"
    "<b>History</b>\n"
    "Established in 2024. Originally named TFI, but it was disbanded due to internal issues. "
    "Shortly after, TCF was formed to continue managing the community with better stability."
)

_PRIVACY_TEXT = (
    "<b>Privacy Information</b>\n\n"
    "The TCF Bot collects and stores the following data:\n"
    "- Your Telegram user ID and first name (cached when you interact with the bot)\n"
    "- Ban records if you are federation-banned\n"
    "- Appeal submissions\n\n"
    "Data is stored securely and is only accessible to TCF staff.\n"
    "No data is shared with third parties."
)

_PRIVACY_POLICY_TEXT = (
    "<b>TCF Privacy Policy</b>\n\n"
    "1. <b>Data collection:</b> We collect Telegram user IDs, first names, and usernames "
    "only when you interact with a TCF-connected group or this bot.\n\n"
    "2. <b>Data use:</b> Collected data is used solely for federation moderation purposes.\n\n"
    "3. <b>Data retention:</b> Ban records are retained indefinitely. "
    "Member cache data may be pruned periodically.\n\n"
    "4. <b>Your rights:</b> Contact a TCF admin to request data deletion.\n\n"
    "5. <b>Contact:</b> Reach staff via the TCF main group."
)

_LINKS_TEXT = (
    "<b>Transsion Core Federation - Official Links</b>\n"
    "Use the buttons below to access our channels and groups. "
    "For developers interested in contributing to Transsion device development, "
    "join TRAVEL - an independent community for collaboration and networking."
)

## ---------------------------------------------------------------------------
## Help content per module topic
## ---------------------------------------------------------------------------

_HELP_CONTENT: dict[str, tuple[str, str]] = {
    "help_ban": (
        "Ban",
        "<code>/tcban &lt;target&gt; &lt;reason&gt;</code> – ban a user federation-wide.\n"
        "Reply to a message or provide a user ID / @username as the target.\n"
        "Aliases: <code>/ban</code>, <code>/tcfban</code>",
    ),
    "help_unban": (
        "Unban",
        "<code>/tcunban &lt;target&gt;</code> – lift a federation ban.\n"
        "Aliases: <code>/unban</code>, <code>/tcfunban</code>",
    ),
    "help_check": (
        "Check Ban",
        "<code>/checkme</code> – check your own federation ban status.\n"
        "Aliases: <code>/myban</code>, <code>/amibanned</code>",
    ),
    "help_baninfo": (
        "Ban Info",
        "<code>/baninfo &lt;target&gt;</code> – check ban details for any user.\n"
        "Aliases: <code>/checkban</code>, <code>/banstatus</code>",
    ),
    "help_admins": (
        "Promote/Demote",
        "<code>/tcpromote &lt;target&gt;</code> – promote a user to admin.\n"
        "Aliases: <code>/promote</code>, <code>/tcfpromote</code>\n\n"
        "<code>/tcdemote &lt;target&gt;</code> – remove admin status (owner only).\n"
        "Aliases: <code>/demote</code>, <code>/tcfdemote</code>\n\n"
        "<code>/tcpromoterequests</code> – submit a promotion request.\n"
        "Aliases: <code>/promoreqs</code>, <code>/tcreqs</code>\n\n"
        "<code>/tcpromotelist</code> – list pending requests (staff only).",
    ),
    "help_transfer": (
        "Transfer Owner",
        "<code>/tctransfer &lt;target&gt;</code> – transfer ownership (owner only).\n"
        "Aliases: <code>/transfer</code>, <code>/tcowner</code>",
    ),
    "help_broadcast": (
        "Broadcast",
        "<code>/tcbroadcast &lt;message&gt;</code> – send to all affiliated groups.\n"
        "Provide text or reply to a message. Staff only.\n"
        "Aliases: <code>/broadcast</code>, <code>/tcannounce</code>",
    ),
    "help_appeal": (
        "Appeal",
        "Submit a ban appeal via the <b>Submit Appeal</b> button on your ban log,\n"
        "or by using <code>/start appeal_&lt;ban_id&gt;</code> in my private chat.\n\n"
        "Reply with a message starting with <code>#appeal</code> containing:\n"
        "- <b>Log link:</b> (from @TranssionCoreFederationLogs)\n"
        "- <b>Clarification:</b> (your honest explanation)\n"
        "- <b>Agreement:</b> (your commitment not to repeat the violation)\n\n"
        "<b>Example:</b>\n"
        "<pre>#appeal\n"
        "Log link: https://t.me/TranssionCoreFederationLogs/1\n"
        "Clarification: I spammed unintentionally.\n"
        "Agreement: I will not use automation tools again.</pre>\n\n"
        "Your appeal will be reviewed by Transsion Core admins. "
        "The banning admin has 12 hours to decide; after that, any admin can approve or reject it.\n"
        "If approved, the ban is lifted; if rejected, the ban remains. You will be notified of the decision.",
    ),
    "help_connect": (
        "Group Affiliation",
        "<code>/jointc</code> – request affiliation with TCF (group admin only).\n"
        "Aliases: <code>/requestjoin</code>, <code>/applytc</code>\n\n"
        "When the bot is added to a group, it automatically prompts the group owner to join.",
    ),
    "help_disconnect": (
        "Disaffiliate",
        "<code>/detc</code> – remove the current group from TCF (group owner or TC admin).\n"
        "Aliases: <code>/leavetc</code>, <code>/untc</code>\n\n"
        "<code>/rmtc &lt;chat_id&gt;</code> – force-remove by ID (staff only).\n"
        "Aliases: <code>/removetc</code>, <code>/deletetc</code>",
    ),
    "help_cleanup": (
        "Cleanup",
        "<code>/cleanup</code> – remove defunct groups (TC staff only).\n"
        "Aliases: <code>/purge</code>, <code>/tcclean</code>",
    ),
    "help_joinleave": (
        "Join/Leave",
        "<code>/leaveall</code> – leave all affiliated groups (owner only).\n"
        "Aliases: <code>/exitall</code>, <code>/tcleave</code>",
    ),
    "help_stats": (
        "Statistics",
        "<code>/tcstats</code> – show federation statistics.\n"
        "Aliases: <code>/stats</code>, <code>/tcinfo</code>",
    ),
}


## ---------------------------------------------------------------------------
## /start command
## ---------------------------------------------------------------------------

async def cmd_start(update: Update, ctx: ContextTypes.DEFAULT_TYPE) -> None:
    msg = update.effective_message
    text = (msg.text or "").strip()
    parts = text.split(None, 1)
    arg = parts[1].strip() if len(parts) > 1 else ""

    if arg == "about":
        await msg.reply_text(
            _ABOUT_TEXT, parse_mode="HTML",
            reply_markup=keyboards.back_to_start_kb(),
        )
        return

    ## appeal_<ban_id> is handled by ConversationHandler in appealing.py
    ## For all other starts (including no arg), show main menu
    await msg.reply_text(
        _MENU_TEXT, parse_mode="HTML",
        reply_markup=keyboards.main_menu_kb(),
    )


async def cmd_help(update: Update, ctx: ContextTypes.DEFAULT_TYPE) -> None:
    await update.effective_message.reply_text(
        "<b>TCF Bot Help</b>\n"
        "I manage Transsion Core groups, bans, appeals, and more. Select a topic below:",
        parse_mode="HTML",
        reply_markup=keyboards.help_topics_kb(),
    )


## ---------------------------------------------------------------------------
## Menu callbacks
## ---------------------------------------------------------------------------

async def on_menu_back_start(update: Update, ctx: ContextTypes.DEFAULT_TYPE) -> None:
    q: CallbackQuery = update.callback_query
    await q.answer()
    await q.edit_message_text(
        _MENU_TEXT, parse_mode="HTML",
        reply_markup=keyboards.main_menu_kb(),
    )


async def on_menu_about(update: Update, ctx: ContextTypes.DEFAULT_TYPE) -> None:
    q: CallbackQuery = update.callback_query
    await q.answer()
    await q.edit_message_text(
        _ABOUT_TEXT, parse_mode="HTML",
        reply_markup=keyboards.back_to_start_kb(),
    )


async def on_menu_help(update: Update, ctx: ContextTypes.DEFAULT_TYPE) -> None:
    q: CallbackQuery = update.callback_query
    await q.answer()
    await q.edit_message_text(
        "<b>TCF Bot Help</b>\n"
        "I manage Transsion Core groups, bans, appeals, and more. Select a topic below:",
        parse_mode="HTML",
        reply_markup=keyboards.help_topics_kb(),
    )


async def on_help_topic(update: Update, ctx: ContextTypes.DEFAULT_TYPE) -> None:
    q: CallbackQuery = update.callback_query
    await q.answer()
    topic = q.data
    if topic not in _HELP_CONTENT:
        await q.edit_message_text("Topic not found.", reply_markup=keyboards.back_to_help_kb())
        return
    name, text = _HELP_CONTENT[topic]
    await q.edit_message_text(
        f"<b>{name}</b>\n\n{text}",
        parse_mode="HTML",
        reply_markup=keyboards.back_to_help_kb(),
    )


async def on_menu_groups(update: Update, ctx: ContextTypes.DEFAULT_TYPE) -> None:
    q: CallbackQuery = update.callback_query
    await q.answer()
    page = int(q.data.split(":")[1]) if ":" in q.data else 0

    groups = await db.groups_db.active_groups()
    if not groups:
        await q.edit_message_text(
            "No groups are currently affiliated with TCF.",
            reply_markup=keyboards.back_to_start_kb(),
        )
        return

    total = len(groups)
    total_pages = max(1, (total + _PAGE_SIZE - 1) // _PAGE_SIZE)
    start = page * _PAGE_SIZE
    chunk = groups[start: start + _PAGE_SIZE]

    lines = [f"<b>Affiliated Groups ({total})</b>  Page {page + 1}/{total_pages}\n"]
    for grp in chunk:
        lines.append(f"- {esc(grp['title'])} {code(str(grp['chat_id']))}")

    rows = []
    nav = []
    if page > 0:
        nav.append(InlineKeyboardButton("Prev", callback_data=f"menu_groups:{page - 1}"))
    if page < total_pages - 1:
        nav.append(InlineKeyboardButton("Next", callback_data=f"menu_groups:{page + 1}"))
    if nav:
        rows.append(nav)
    rows.append([InlineKeyboardButton("Back", callback_data="menu_back_start")])

    await q.edit_message_text(
        "\n".join(lines), parse_mode="HTML",
        reply_markup=InlineKeyboardMarkup(rows),
    )


async def on_menu_additional(update: Update, ctx: ContextTypes.DEFAULT_TYPE) -> None:
    q: CallbackQuery = update.callback_query
    await q.answer()
    await q.edit_message_text(
        _LINKS_TEXT,
        parse_mode="HTML",
        reply_markup=InlineKeyboardMarkup([
            [
                InlineKeyboardButton("Main Channel", url="https://t.me/TranssionCoreFederation"),
                InlineKeyboardButton("Discussion Group", url="https://t.me/TranssionCoreFederationGroup"),
            ],
            [
                InlineKeyboardButton("Logs Channel", url="https://t.me/TranssionCoreFederationLogs"),
                InlineKeyboardButton("Exec Group", url="https://t.me/+A105pfnCvkhiZWM1"),
            ],
            [
                InlineKeyboardButton("TRAVEL (Dev Community)", url="http://t.me/+S2C_ppFvHlAwMzNl"),
            ],
            [InlineKeyboardButton("Back", callback_data="menu_back_start")],
        ]),
    )


async def on_menu_information(update: Update, ctx: ContextTypes.DEFAULT_TYPE) -> None:
    q: CallbackQuery = update.callback_query
    await q.answer()

    owner_id = await db.admins_db.get_owner_id()
    owner_fname = await db.users_db.get_first_name(owner_id, "Owner") if owner_id else "Unknown"
    admins = await db.admins_db.admin_count()
    bans = await db.bans_db.active_ban_count()
    groups = await db.groups_db.active_group_count()

    owner_mention = mention(owner_id, owner_fname) if owner_id else "Unknown"

    lines = [
        "<b>Transsion Core Information</b>",
        f"Owner: {owner_mention}",
        f"Admins: {admins}",
        f"Active Bans: {bans}",
        f"Connected Chats: {groups}",
    ]
    await q.edit_message_text(
        "\n".join(lines),
        parse_mode="HTML",
        reply_markup=keyboards.info_sub_kb(),
    )


async def on_info_admins(update: Update, ctx: ContextTypes.DEFAULT_TYPE) -> None:
    q: CallbackQuery = update.callback_query
    await q.answer()
    page = int(q.data.split(":")[1]) if ":" in q.data else 0

    admins = await db.admins_db.all_admins()
    total = len(admins)
    total_pages = max(1, (total + _PAGE_SIZE - 1) // _PAGE_SIZE)
    chunk = admins[page * _PAGE_SIZE: (page + 1) * _PAGE_SIZE]

    lines = [f"<b>TCF Admins ({total})</b>  Page {page + 1}/{total_pages}\n"]
    for adm in chunk:
        fname = await db.users_db.get_first_name(adm["user_id"], str(adm["user_id"]))
        lines.append(f"- {fname} {code(str(adm['user_id']))}")

    await q.edit_message_text(
        "\n".join(lines),
        parse_mode="HTML",
        reply_markup=keyboards.info_list_nav_kb(page, total_pages, "info_admins", "menu_information"),
    )


async def on_info_chats(update: Update, ctx: ContextTypes.DEFAULT_TYPE) -> None:
    q: CallbackQuery = update.callback_query
    await q.answer()
    page = int(q.data.split(":")[1]) if ":" in q.data else 0

    groups = await db.groups_db.active_groups()
    total = len(groups)
    total_pages = max(1, (total + _PAGE_SIZE - 1) // _PAGE_SIZE)
    chunk = groups[page * _PAGE_SIZE: (page + 1) * _PAGE_SIZE]

    lines = [f"<b>Connected Chats ({total})</b>  Page {page + 1}/{total_pages}\n"]
    for grp in chunk:
        lines.append(f"- {esc(grp['title'])} {code(str(grp['chat_id']))}")

    await q.edit_message_text(
        "\n".join(lines),
        parse_mode="HTML",
        reply_markup=keyboards.info_list_nav_kb(page, total_pages, "info_chats", "menu_information"),
    )


async def on_menu_privacy(update: Update, ctx: ContextTypes.DEFAULT_TYPE) -> None:
    q: CallbackQuery = update.callback_query
    await q.answer()
    await q.edit_message_text(
        _PRIVACY_TEXT, parse_mode="HTML",
        reply_markup=keyboards.privacy_kb(),
    )


async def on_menu_privacy_policy(update: Update, ctx: ContextTypes.DEFAULT_TYPE) -> None:
    q: CallbackQuery = update.callback_query
    await q.answer()
    await q.edit_message_text(
        _PRIVACY_POLICY_TEXT, parse_mode="HTML",
        reply_markup=keyboards.back_to_privacy_kb(),
    )


## ---------------------------------------------------------------------------
## Handler list
## ---------------------------------------------------------------------------

## /start (with or without args), but NOT appeal_ deep links (handled by ConversationHandler)
_START_FILTER = (
    filters.Regex(r"^/start$")
    | filters.Regex(r"^/start\s+about$")
    ## Don't capture appeal_ here – that goes to ConversationHandler in appealing.py
)
## Also accept prefixed variants except for appeal deep link
_START_PREFIXED = build_prefixed_filters("start")

_HELP_FILTER = (
    build_prefixed_filters("help")
    | build_prefixed_filters("commands")
)

_HELP_TOPIC_PATTERN = (
    r"^help_(ban|unban|check|baninfo|admins|transfer|broadcast|appeal|connect|disconnect|cleanup|joinleave|stats)$"
)

__handlers__ = [
    MessageHandler(_START_FILTER | _START_PREFIXED, cmd_start),
    MessageHandler(_HELP_FILTER, cmd_help),
    ## Menu callbacks
    CallbackQueryHandler(on_menu_back_start, pattern=r"^menu_back_start$"),
    CallbackQueryHandler(on_menu_about, pattern=r"^menu_about$"),
    CallbackQueryHandler(on_menu_help, pattern=r"^menu_help$"),
    CallbackQueryHandler(on_help_topic, pattern=_HELP_TOPIC_PATTERN),
    CallbackQueryHandler(on_menu_groups, pattern=r"^menu_groups(:\d+)?$"),
    CallbackQueryHandler(on_menu_additional, pattern=r"^menu_additional$"),
    CallbackQueryHandler(on_menu_information, pattern=r"^menu_information$"),
    CallbackQueryHandler(on_info_admins, pattern=r"^info_admins:\d+$"),
    CallbackQueryHandler(on_info_chats, pattern=r"^info_chats:\d+$"),
    CallbackQueryHandler(on_menu_privacy, pattern=r"^menu_privacy$"),
    CallbackQueryHandler(on_menu_privacy_policy, pattern=r"^menu_privacy_policy$"),
]
