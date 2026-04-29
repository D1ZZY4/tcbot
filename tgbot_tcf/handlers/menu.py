"""Interactive start menu (Feature 24) and interactive help system (Feature 25).

The same menu surface is reachable from two entry points:
- /start in private chat (no deep-link argument): renders the start menu.
- /help, /commands: renders a static, plain command list (Feature 19).
- The "Help" button inside the start menu opens the interactive help with
  Back buttons that navigate inside the menu tree.

Only the user who issued /start may interact with the inline buttons.
All transitions edit the original message in-place.
"""
import logging

from telegram import InlineKeyboardButton, InlineKeyboardMarkup, Update
from telegram.constants import ChatType, ParseMode
from telegram.error import TelegramError
from telegram.ext import ContextTypes

from ..config import (
    ABOUT_TEXT,
    APPEAL_TOPIC,
    EXEC_GROUP,
    LOG_CHANNEL,
    MAIN_CHANNEL,
    MAIN_GROUP,
    PROOF_TOPIC,
)
from ..db import bans, fed_admins, federated_groups, fed_owners
from ..utils.format import user_link

logger = logging.getLogger(__name__)


WELCOME_TEXT = (
    "<b>Welcome to the Transsion Core Federation (TCF) Bot</b>\n\n"
    "TCF is a community-driven federation for Infinix, Tecno, and Itel groups. "
    "This bot manages affiliation, federation-wide bans, appeals, and broadcasts.\n\n"
    "Use the buttons below to explore."
)


# ---------------------------------------------------------------------------
# Per-user owner tracking so only the original /start user may navigate.
# ---------------------------------------------------------------------------

def _menu_owners(context: ContextTypes.DEFAULT_TYPE) -> dict:
    return context.application.bot_data.setdefault("menu_owners", {})


def _menu_key(chat_id: int, message_id: int) -> str:
    return f"{chat_id}:{message_id}"


def _remember_owner(context: ContextTypes.DEFAULT_TYPE, chat_id: int, message_id: int, user_id: int) -> None:
    owners = _menu_owners(context)
    owners[_menu_key(chat_id, message_id)] = user_id


def _is_owner(context: ContextTypes.DEFAULT_TYPE, chat_id: int, message_id: int, user_id: int) -> bool:
    owners = _menu_owners(context)
    expected = owners.get(_menu_key(chat_id, message_id))
    # If unknown (bot restart), allow interaction.
    return expected is None or expected == user_id


# ---------------------------------------------------------------------------
# Keyboards
# ---------------------------------------------------------------------------

def _start_keyboard() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(
        [
            [
                InlineKeyboardButton("About TCF", callback_data="menu_about"),
                InlineKeyboardButton("Help", callback_data="menu_help"),
            ],
            [
                InlineKeyboardButton("Statistics", callback_data="menu_stats"),
                InlineKeyboardButton("Federation Groups", callback_data="menu_groups"),
            ],
            [
                InlineKeyboardButton("Federation Info", callback_data="menu_fedinfo"),
            ],
        ]
    )


def _back_to_start_kb() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(
        [[InlineKeyboardButton("Back", callback_data="menu_back_start")]]
    )


# Module list for interactive help.
HELP_MODULES: list[tuple[str, str]] = [
    ("Ban /cban", "help_ban"),
    ("Unban /cunban", "help_unban"),
    ("Check Ban", "help_check"),
    ("Promote / Demote", "help_admin"),
    ("Transfer Owner", "help_transfer"),
    ("Broadcast", "help_broadcast"),
    ("Sync Ban", "help_syncban"),
    ("Disaffiliate", "help_defed"),
    ("Affiliate Group", "help_join"),
    ("Appeal", "help_appeal"),
    ("Listings & Stats", "help_lists"),
    ("Maintenance", "help_maint"),
]


def _help_modules_kb(with_back: bool) -> InlineKeyboardMarkup:
    rows: list[list[InlineKeyboardButton]] = []
    pairs = [HELP_MODULES[i:i + 2] for i in range(0, len(HELP_MODULES), 2)]
    for pair in pairs:
        rows.append([InlineKeyboardButton(label, callback_data=cb) for label, cb in pair])
    if with_back:
        rows.append([InlineKeyboardButton("Back", callback_data="menu_back_start")])
    return InlineKeyboardMarkup(rows)


def _help_detail_kb(with_back_to_start: bool) -> InlineKeyboardMarkup:
    rows = [[InlineKeyboardButton("Back", callback_data="menu_help")]]
    if with_back_to_start:
        # When inside the start-menu flow, allow jumping back to the start menu too.
        rows.append([InlineKeyboardButton("Main Menu", callback_data="menu_back_start")])
    return InlineKeyboardMarkup(rows)


# ---------------------------------------------------------------------------
# Help detail texts
# ---------------------------------------------------------------------------

HELP_DETAILS: dict[str, str] = {
    "help_ban": (
        "<b>Ban a user (Federation owner / admin)</b>\n\n"
        "Aliases: /cban, /comban, /fban\n"
        "Usage: reply to a user with /cban &lt;reason&gt;, or "
        "/cban &lt;user_id|@username&gt; &lt;reason&gt;\n"
        "Where: any affiliated group, the main group or its topics, or the bot PM. "
        "You do not need to be an admin of that chat.\n"
        "After issuing the command the bot prompts for proof (photo or video, "
        "albums supported) within 60 seconds. A Cancel button is shown."
    ),
    "help_unban": (
        "<b>Unban a user (Federation owner / admin)</b>\n\n"
        "Aliases: /cunban, /comunban, /funban\n"
        "Usage: reply to a user with /cunban, or "
        "/cunban &lt;user_id|@username&gt;\n"
        "Where: any affiliated group, the main group or its topics, or the bot PM."
    ),
    "help_check": (
        "<b>Check ban status</b>\n\n"
        "/checkme, /myban, /amibanned - check whether you are banned in the federation.\n"
        "/baninfo, /checkban, /banstatus &lt;user_id|@username|reply&gt; - "
        "look up ban details for any user. Available to everyone."
    ),
    "help_admin": (
        "<b>Promote and Demote (Federation owner only)</b>\n\n"
        "Promote: /cpromote, /compromote, /fpromote &lt;target&gt;\n"
        "Demote: /cdemote, /comdemote, /fdemote &lt;target&gt;\n"
        "Target may be a reply, user ID, or @username."
    ),
    "help_transfer": (
        "<b>Transfer Federation Ownership (Federation owner only)</b>\n\n"
        "Aliases: /transferowner, /tfowner, /fedowner &lt;target&gt;\n"
        "The previous owner becomes a regular Federation Admin."
    ),
    "help_broadcast": (
        "<b>Broadcast to all groups (Federation owner / admin)</b>\n\n"
        "Aliases: /broadcast, /announce, /fcast &lt;message&gt;\n"
        "Sends the message to every active affiliated group. Groups that fail "
        "to receive the message are marked inactive."
    ),
    "help_syncban": (
        "<b>Sync ban across all groups (Federation owner / admin)</b>\n\n"
        "Aliases: /syncban, /forcesync, /fbanall &lt;target&gt;\n"
        "Re-applies an existing federation ban to every active affiliated group "
        "where the bot has restrict-members rights."
    ),
    "help_defed": (
        "<b>Disaffiliate from the federation</b>\n\n"
        "Inside a group: /defed, /leavefed, /unfed - the group owner or any "
        "Federation owner / admin can remove the group from TCF.\n"
        "By group ID: /rmfed, /removefed, /deletefed &lt;group_id&gt; - "
        "Federation owner / admin only."
    ),
    "help_join": (
        "<b>Affiliate a group with TCF</b>\n\n"
        "When the bot is added to a group, the group owner sees Join / Cancel "
        "buttons. After adding the bot as an admin (delete messages, ban users, "
        "invite users), the owner can also use /joinfed, /requestjoin, /applyfed."
    ),
    "help_appeal": (
        "<b>Appeal a federation ban</b>\n\n"
        "If you are banned, run /checkme and tap Submit Appeal. Follow the "
        "instructions in the bot PM. Send a single message starting with "
        "#appeal containing the log link, your clarification, and your "
        "agreement to follow the rules."
    ),
    "help_lists": (
        "<b>Listings and statistics</b>\n\n"
        "/fedgroups, /groups, /listfed - list all affiliated groups.\n"
        "/fedstats, /stats, /fedinfo - federation statistics.\n"
        "/fedchannels, /channels, /fedconfig - configured channel and topic IDs.\n"
        "/about, /tcfabout, /fedabout - about TCF."
    ),
    "help_maint": (
        "<b>Maintenance (Federation owner / admin)</b>\n\n"
        "/cleanup, /purge, /fedclean - mark inactive any affiliated group the "
        "bot can no longer reach.\n"
        "/leaveall, /exitall, /fedleave - the Federation owner makes the bot "
        "leave every active affiliated group."
    ),
}


# ---------------------------------------------------------------------------
# /start handler (no deep link, private chat)
# ---------------------------------------------------------------------------

async def send_start_menu(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    msg = update.effective_message
    user = update.effective_user
    if msg is None or user is None:
        return
    sent = await msg.reply_text(
        WELCOME_TEXT,
        reply_markup=_start_keyboard(),
        parse_mode=ParseMode.HTML,
        disable_web_page_preview=True,
    )
    _remember_owner(context, sent.chat.id, sent.message_id, user.id)


# ---------------------------------------------------------------------------
# Callback router
# ---------------------------------------------------------------------------

async def on_menu_callback(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    cq = update.callback_query
    if cq is None or cq.message is None or cq.from_user is None or cq.data is None:
        return
    chat_id = cq.message.chat.id
    message_id = cq.message.message_id

    if not _is_owner(context, chat_id, message_id, cq.from_user.id):
        await cq.answer("Only the user who opened this menu can use these buttons.", show_alert=True)
        return

    await cq.answer()
    data = cq.data

    if data == "menu_back_start":
        await _edit(cq, WELCOME_TEXT, _start_keyboard())
        return
    if data == "menu_about":
        await _edit(cq, ABOUT_TEXT, _back_to_start_kb(), parse_mode=None)
        return
    if data == "menu_help":
        await _edit(cq, _help_intro_text(), _help_modules_kb(with_back=True))
        return
    if data == "menu_stats":
        text = await _stats_text(context)
        await _edit(cq, text, _back_to_start_kb())
        return
    if data == "menu_groups":
        text = await _groups_text()
        await _edit(cq, text, _back_to_start_kb())
        return
    if data == "menu_fedinfo":
        await _edit(cq, _channels_text(), _back_to_start_kb(), parse_mode=None)
        return

    if data in HELP_DETAILS:
        await _edit(cq, HELP_DETAILS[data], _help_detail_kb(with_back_to_start=True))
        return


async def _edit(cq, text: str, kb: InlineKeyboardMarkup, parse_mode=ParseMode.HTML) -> None:
    try:
        await cq.edit_message_text(
            text,
            reply_markup=kb,
            parse_mode=parse_mode,
            disable_web_page_preview=True,
        )
    except TelegramError as exc:
        # Ignore "Message is not modified" and similar transient errors.
        logger.debug("menu edit ignored: %s", exc)


# ---------------------------------------------------------------------------
# Dynamic content helpers (mirror the read-only command output)
# ---------------------------------------------------------------------------

def _help_intro_text() -> str:
    return (
        "<b>Help</b>\n\n"
        "Pick a topic to see its details. Use Back to return to the main menu."
    )


async def _stats_text(context: ContextTypes.DEFAULT_TYPE) -> str:
    owner = await fed_owners.find_one({})
    admins_count = await fed_admins.count_documents({})
    groups_count = await federated_groups.count_documents({"is_active": True})
    bans_count = await bans.count_documents({"is_active": True})
    if owner:
        owner_id = owner["user_id"]
        try:
            chat = await context.bot.get_chat(owner_id)
            owner_name = chat.first_name or str(owner_id)
        except TelegramError:
            owner_name = str(owner_id)
        owner_line = user_link(owner_id, owner_name)
    else:
        owner_line = "Not set"
    return (
        "<b>TCF Federation Statistics</b>\n"
        f"Owner: {owner_line}\n"
        f"Federation Admins: {admins_count}\n"
        f"Affiliated Groups: {groups_count}\n"
        f"Active Bans: {bans_count}"
    )


async def _groups_text() -> str:
    cursor = federated_groups.find({"is_active": True})
    groups = [g async for g in cursor]
    if not groups:
        return "No groups are currently affiliated with TCF."
    lines = ["<b>Affiliated TCF Groups</b>"]
    for g in groups[:50]:
        title = g.get("title") or str(g["chat_id"])
        lines.append(f"{title} (ID: {g['chat_id']})")
    if len(groups) > 50:
        lines.append(f"... and {len(groups) - 50} more groups.")
    return "\n".join(lines)


def _channels_text() -> str:
    return (
        "Log Channel: " + str(LOG_CHANNEL) + "\n"
        "Main Group: " + str(MAIN_GROUP) + "\n"
        "Proof Topic: " + str(PROOF_TOPIC) + "\n"
        "Appeal Topic: " + str(APPEAL_TOPIC) + "\n"
        "Main Channel: " + str(MAIN_CHANNEL) + "\n"
        "Exec Group: " + str(EXEC_GROUP)
    )
