"""Start menu (Feature 24) and interactive help system (Features 19 & 25).

Two entry points share the same module pages:
- "menu" mode: opened from /start in PM. The module list shows a "Back"
  button that returns to the start menu (callback_data="menu_back_start").
- "cmd" mode: opened from /help or /commands. The module list has no
  "Back to start" button.

In both modes, detail pages have a "Back" button (callback_data="menu_help_main")
that returns to the module list, and the bot remembers the entry mode for that
specific (chat_id, message_id) so navigation stays consistent.

Only the user who opened the menu may use its buttons.
"""
import logging

from telegram import InlineKeyboardButton, InlineKeyboardMarkup, Update
from telegram.constants import ParseMode
from telegram.error import TelegramError
from telegram.ext import ContextTypes

from ..config import ABOUT_TEXT
from .links import get_links_view
from .lists import build_fedgroups_text, build_fedstats_text

logger = logging.getLogger(__name__)


WELCOME_TEXT = (
    "<b>Welcome to the Transsion Core Federation (TCF) Bot</b>\n\n"
    "TCF is a community-driven federation for Infinix, Tecno, and Itel groups. "
    "I help manage federation membership, bans, appeals, and broadcasts.\n\n"
    "Use the buttons below to explore."
)

HELP_INTRO_TEXT = (
    "<b>TCF Federation Bot Help</b>\n"
    "I am a federation management bot for Transsion Core Federation (TCF). "
    "Below are the available modules. Select one to learn more."
)


# ---------------------------------------------------------------------------
# Per-message state: who opened it and how (so we know which Back to show).
# ---------------------------------------------------------------------------

def _state(context: ContextTypes.DEFAULT_TYPE) -> dict:
    return context.application.bot_data.setdefault("menu_state", {})


def _key(chat_id: int, message_id: int) -> str:
    return f"{chat_id}:{message_id}"


def _remember(
    context: ContextTypes.DEFAULT_TYPE,
    chat_id: int,
    message_id: int,
    user_id: int,
    mode: str,
) -> None:
    _state(context)[_key(chat_id, message_id)] = {"user_id": user_id, "mode": mode}


def _get(context: ContextTypes.DEFAULT_TYPE, chat_id: int, message_id: int) -> dict | None:
    return _state(context).get(_key(chat_id, message_id))


def _is_owner(
    context: ContextTypes.DEFAULT_TYPE, chat_id: int, message_id: int, user_id: int
) -> bool:
    s = _get(context, chat_id, message_id)
    return s is None or s["user_id"] == user_id


def _mode(context: ContextTypes.DEFAULT_TYPE, chat_id: int, message_id: int) -> str:
    s = _get(context, chat_id, message_id)
    return s["mode"] if s else "menu"


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
                InlineKeyboardButton("Federation Links", callback_data="menu_fedlinks"),
            ],
        ]
    )


def _back_to_start_kb() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(
        [[InlineKeyboardButton("Back", callback_data="menu_back_start")]]
    )


# Help module list per Feature 19 spec, exact pairings.
HELP_MODULE_ROWS: list[list[tuple[str, str]]] = [
    [("Ban", "help_ban"), ("Unban", "help_unban")],
    [("Check Ban", "help_check"), ("Ban Info", "help_baninfo")],
    [("Promote/Demote", "help_admin"), ("Transfer Owner", "help_transfer")],
    [("Broadcast", "help_broadcast"), ("Sync Ban", "help_syncban")],
    [("Group Affiliation", "help_affiliation"), ("Disaffiliate", "help_defed")],
    [("Appeal", "help_appeal"), ("Join/Leave", "help_join")],
    [("Statistics", "help_stats"), ("Cleanup", "help_cleanup")],
]


def _help_modules_kb(with_back_to_start: bool) -> InlineKeyboardMarkup:
    rows = [
        [InlineKeyboardButton(label, callback_data=cb) for label, cb in row]
        for row in HELP_MODULE_ROWS
    ]
    if with_back_to_start:
        rows.append([InlineKeyboardButton("Back", callback_data="menu_back_start")])
    return InlineKeyboardMarkup(rows)


def _help_detail_kb(mode: str) -> InlineKeyboardMarkup:
    rows = [[InlineKeyboardButton("Back", callback_data="menu_help_main")]]
    if mode == "menu":
        rows.append([InlineKeyboardButton("Main Menu", callback_data="menu_back_start")])
    return InlineKeyboardMarkup(rows)


# ---------------------------------------------------------------------------
# Help detail texts (one per HELP_MODULE_ROWS entry)
# ---------------------------------------------------------------------------

HELP_DETAILS: dict[str, str] = {
    "help_ban": (
        "<b>Ban Module</b>\n\n"
        "Federation owners and admins can ban a user across the entire "
        "federation. The bot will then prompt for proof (photo or video, "
        "albums supported) before the ban is committed.\n\n"
        "Commands: /cban, /comban, /fban (also .cban, !cban)\n"
        "Usage: reply to a user with /cban &lt;reason&gt;, or "
        "/cban &lt;user_id|@username&gt; &lt;reason&gt;\n"
        "Who: federation owners and admins.\n"
        "Where: any affiliated group, the main group or its topics, the exec "
        "group, or the bot PM."
    ),
    "help_unban": (
        "<b>Unban Module</b>\n\n"
        "Lift an active federation ban.\n\n"
        "Commands: /cunban, /comunban, /funban (also .cunban, !cunban)\n"
        "Usage: reply to a user with /cunban, or "
        "/cunban &lt;user_id|@username&gt;\n"
        "Who: federation owners and admins.\n"
        "Where: same as Ban."
    ),
    "help_check": (
        "<b>Check Ban Module</b>\n\n"
        "Find out whether you are banned in TCF.\n\n"
        "Commands: /checkme, /myban, /amibanned\n"
        "Who: anyone.\n"
        "Where: any chat. If you are banned the bot replies with the reason "
        "and a Submit Appeal button."
    ),
    "help_baninfo": (
        "<b>Ban Info Module</b>\n\n"
        "Look up the ban details for any user.\n\n"
        "Commands: /baninfo, /checkban, /banstatus &lt;user_id|@username|reply&gt;\n"
        "Who: anyone.\n"
        "Where: any chat."
    ),
    "help_admin": (
        "<b>Promote / Demote Module</b>\n\n"
        "Manage Federation Admins.\n\n"
        "Promote: /cpromote, /compromote, /fpromote &lt;target&gt;\n"
        "Demote: /cdemote, /comdemote, /fdemote &lt;target&gt;\n"
        "Who: federation owner only."
    ),
    "help_transfer": (
        "<b>Transfer Ownership Module</b>\n\n"
        "Transfer Federation Ownership to another user. The previous owner "
        "becomes a regular Federation Admin.\n\n"
        "Commands: /transferowner, /tfowner, /fedowner &lt;target&gt;\n"
        "Who: federation owner only."
    ),
    "help_broadcast": (
        "<b>Broadcast Module</b>\n\n"
        "Send a plain-text announcement to every active affiliated group.\n\n"
        "Commands: /broadcast, /announce, /fcast &lt;message&gt;\n"
        "Who: federation owners and admins.\n"
        "Note: groups that fail to receive the message are marked inactive."
    ),
    "help_syncban": (
        "<b>Sync Ban Module</b>\n\n"
        "Re-enforce an existing federation ban across every active "
        "affiliated group where the bot has restrict-members rights.\n\n"
        "Commands: /syncban, /forcesync, /fbanall &lt;target&gt;\n"
        "Who: federation owners and admins."
    ),
    "help_affiliation": (
        "<b>Group Affiliation Module</b>\n\n"
        "When the bot is added to a group, the group owner sees Join / Cancel "
        "buttons. After making the bot an admin (delete messages, ban users, "
        "invite users), the group owner can also affiliate later via:\n\n"
        "Commands: /joinfed, /requestjoin, /applyfed\n"
        "Who: the group owner."
    ),
    "help_defed": (
        "<b>Disaffiliate Module</b>\n\n"
        "Inside a group: /defed, /leavefed, /unfed - the group owner or any "
        "federation owner / admin can remove the group from TCF.\n"
        "By group ID (any chat): /rmfed, /removefed, /deletefed &lt;group_id&gt; "
        "- federation owner or admin only."
    ),
    "help_appeal": (
        "<b>Appeal Module</b>\n\n"
        "If you are banned, run /checkme and tap Submit Appeal. Then in the "
        "bot PM send a single message starting with #appeal containing the "
        "log link, your clarification, and your agreement to follow the rules.\n\n"
        "Within the first 12 hours after submission, only the original "
        "banning admin may approve or reject. After that, any federation "
        "admin or owner can decide."
    ),
    "help_join": (
        "<b>Join / Leave Module</b>\n\n"
        "/joinfed, /requestjoin, /applyfed - group owner asks the bot to "
        "affiliate a group with TCF.\n"
        "/leaveall, /exitall, /fedleave - federation owner makes the bot "
        "leave every active affiliated group."
    ),
    "help_stats": (
        "<b>Statistics Module</b>\n\n"
        "Federation statistics and listings.\n\n"
        "Commands:\n"
        "/fedgroups, /groups, /listfed - list active affiliated groups.\n"
        "/fedstats, /stats, /fedinfo - federation statistics.\n"
        "/fedlinks, /links, /fedconfig - official TCF links.\n"
        "Who: anyone."
    ),
    "help_cleanup": (
        "<b>Cleanup Module</b>\n\n"
        "Mark inactive any affiliated group the bot can no longer reach.\n\n"
        "Commands: /cleanup, /purge, /fedclean\n"
        "Who: federation owners and admins."
    ),
}


# ---------------------------------------------------------------------------
# Public entry points
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
    _remember(context, sent.chat.id, sent.message_id, user.id, "menu")


async def send_help_command(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    msg = update.effective_message
    user = update.effective_user
    if msg is None or user is None:
        return
    sent = await msg.reply_text(
        HELP_INTRO_TEXT,
        reply_markup=_help_modules_kb(with_back_to_start=False),
        parse_mode=ParseMode.HTML,
        disable_web_page_preview=True,
    )
    _remember(context, sent.chat.id, sent.message_id, user.id, "cmd")


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
        await cq.answer(
            "Only the user who opened this menu can use these buttons.",
            show_alert=True,
        )
        return

    await cq.answer()
    data = cq.data
    mode = _mode(context, chat_id, message_id)

    if data == "menu_back_start":
        await _edit(cq, WELCOME_TEXT, _start_keyboard())
        return
    if data == "menu_about":
        await _edit(cq, ABOUT_TEXT, _back_to_start_kb(), parse_mode=None)
        return
    if data == "menu_help":
        # Entered help via the start menu: list shows Back-to-start.
        await _edit(cq, HELP_INTRO_TEXT, _help_modules_kb(with_back_to_start=True))
        return
    if data == "menu_help_main":
        # Back from a detail page to the module list.
        await _edit(
            cq,
            HELP_INTRO_TEXT,
            _help_modules_kb(with_back_to_start=(mode == "menu")),
        )
        return
    if data == "menu_stats":
        await _edit(cq, await build_fedstats_text(context), _back_to_start_kb())
        return
    if data == "menu_groups":
        await _edit(cq, await build_fedgroups_text(), _back_to_start_kb())
        return
    if data == "menu_fedlinks":
        text, links_kb = get_links_view()
        rows = list(links_kb.inline_keyboard) + [
            [InlineKeyboardButton("Back", callback_data="menu_back_start")]
        ]
        await _edit(cq, text, InlineKeyboardMarkup(rows))
        return

    if data in HELP_DETAILS:
        await _edit(cq, HELP_DETAILS[data], _help_detail_kb(mode))
        return


async def _edit(
    cq,
    text: str,
    kb: InlineKeyboardMarkup,
    parse_mode=ParseMode.HTML,
) -> None:
    try:
        await cq.edit_message_text(
            text,
            reply_markup=kb,
            parse_mode=parse_mode,
            disable_web_page_preview=True,
        )
    except TelegramError as exc:
        logger.debug("menu edit ignored: %s", exc)
