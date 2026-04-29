# © Copyright 2024 - 2026 Transsion Core
# © Copyright 2024 - 2026 Dizzy
# © Copyright 2026 Aveum Apps
"""Start menu, interactive help system, and all menu callback routing."""
import logging

from telegram import InlineKeyboardButton, InlineKeyboardMarkup, Update
from telegram.constants import ParseMode
from telegram.error import TelegramError
from telegram.ext import ContextTypes
from typing import Any, Dict, Optional

from .. import ABOUT_TEXT
from .links import get_links_view
from .lists import build_admins_text, build_fedgroups_text, build_fedstats_text

logger = logging.getLogger(__name__)

WELCOME_TEXT = (
    "<b>Welcome to the Transsion Core Federation (TCF) Bot!</b>\n"
    "I'm here to help you manage Transsion Core groups, bans, appeals, and more. "
    "Use the buttons below to navigate."
)

HELP_INTRO_TEXT = (
    "<b>TCF Bot Help</b>\n"
    "I'm your assistant for managing the Transsion Core Federation. "
    "Select a topic below to learn more about what I can do."
)

PRIVACY_MAIN_TEXT = (
    "<b>Privacy Information</b>\n"
    "Select one of the below options for more information about how the bot "
    "handles your privacy."
)

PRIVACY_POLICY_TEXT = (
    "The Transsion Core Federation bot only collects data necessary for federation "
    "moderation: user IDs, group IDs, and message IDs related to bans and proofs. "
    "No personal messages, phone numbers, or media are stored beyond what you "
    "explicitly provide as proof. Your data is never shared with third parties and "
    "is only used to maintain a secure environment. All ban records are accessible "
    "only to Transsion Core admins."
)

HELP_DETAILS: dict[str, str] = {
    "help_ban": (
        "<b>Ban Module</b>\n"
        "Commands: /tcban, /ban, /tcfban\n"
        "Usage: /tcban &lt;target&gt; &lt;reason&gt; (target can be reply, user ID, or @username)\n"
        "Who can use: Transsion Core Owner and Admins.\n"
        "Where: Any affiliated group, the main forum, exec group, or PM.\n"
        "Note: A proof is required. After issuing the command, you'll be asked "
        "to upload photo/video evidence."
    ),
    "help_unban": (
        "<b>Unban Module</b>\n"
        "Commands: /tcunban, /unban, /tcfunban\n"
        "Usage: /tcunban &lt;target&gt; [optional reason]\n"
        "Who can use: Transsion Core Owner and Admins.\n"
        "Where: Any affiliated group, main forum, exec group, or PM.\n"
        "If an appeal was pending, it will be automatically closed."
    ),
    "help_check": (
        "<b>Check Ban Module</b>\n"
        "Commands: /checkme, /myban, /amibanned\n"
        "Usage: Simply type /checkme anywhere.\n"
        "Who can use: Everyone.\n"
        "If banned, you'll see details and a button to submit an appeal."
    ),
    "help_baninfo": (
        "<b>Ban Info Module</b>\n"
        "Commands: /baninfo, /checkban, /banstatus\n"
        "Usage: /baninfo &lt;target&gt;\n"
        "Who can use: Everyone.\n"
        "Shows detailed information about a user's ban status."
    ),
    "help_admin": (
        "<b>Promote/Demote Module</b>\n"
        "Commands: /tcpromote, /promote, /tcfpromote  (promote)\n"
        "/tcdemote, /demote, /tcfdemote  (demote)\n"
        "Usage: /tcpromote &lt;target&gt; (promote); /tcdemote &lt;target&gt; (demote)\n"
        "Who can use: Promote - Transsion Core Admins (creates request) or Owner "
        "(immediate). Demote - Owner only.\n"
        "Note: Self-demote produces a special message about the bot's role."
    ),
    "help_transfer": (
        "<b>Transfer Owner Module</b>\n"
        "Commands: /tctransfer, /transfer, /tcowner\n"
        "Usage: /tctransfer &lt;target&gt;\n"
        "Who can use: Transsion Core Owner only.\n"
        "Transfers ownership to another user. The old owner becomes a regular admin."
    ),
    "help_broadcast": (
        "<b>Broadcast Module</b>\n"
        "Commands: /tcbroadcast, /broadcast, /tcannounce\n"
        "Usage: /tcbroadcast &lt;message&gt;\n"
        "Who can use: Transsion Core Owner and Admins.\n"
        "Sends the message to all affiliated groups."
    ),
    "help_syncban": (
        "<b>Sync Ban Module</b>\n"
        "Commands: /tcsync, /syncban, /tcfbanall\n"
        "Usage: /tcsync &lt;target&gt;\n"
        "Who can use: Transsion Core Owner and Admins.\n"
        "Enforces an existing active ban across all affiliated groups."
    ),
    "help_affiliation": (
        "<b>Group Affiliation Module</b>\n"
        "Commands: /jointc, /requestjoin, /applytc (explicit join)\n"
        "/detc, /leavetc, /untc (disaffiliate current group)\n"
        "/rmtc, /removetc, /deletetc &lt;group_id&gt; (remove by ID)\n"
        "Who can use: Join - group owner; disaffiliate - group owner or TC admin; "
        "remove - TC admins.\n"
        "Note: Bot added automatically asks to join."
    ),
    "help_defed": (
        "<b>Disaffiliate Module</b>\n"
        "Inside a group: /detc, /leavetc, /untc - the group owner or any TC "
        "owner/admin can remove the group from TCF.\n"
        "By group ID (any chat): /rmtc, /removetc, /deletetc &lt;group_id&gt; - "
        "TC owner or admin only."
    ),
    "help_appeal": (
        "<b>Appeal Module</b>\n"
        "If you are banned, you can submit an appeal by clicking 'Submit Appeal' "
        "on the ban log message in @TranssionCoreFederationLogs, or by using "
        "/start appeal_&lt;ban_id&gt; in my private chat.\n"
        "The bot will then guide you through the process. You need to reply with "
        "a message starting with #appeal, containing:\n"
        "- Log link: (from the log channel)\n"
        "- Clarification: (your honest explanation)\n"
        "- Agreement: (your commitment not to repeat the violation)\n\n"
        "Your appeal will be reviewed by Transsion Core admins. The banning admin "
        "has 12 hours to decide; after that, any admin can approve or reject it. "
        "If approved, the ban is lifted; if rejected, the ban remains. "
        "You'll be notified of the decision."
    ),
    "help_join": (
        "<b>Join/Leave Module</b>\n"
        "Commands: /jointc, /requestjoin, /applytc (join)\n"
        "/detc, /leavetc, /untc (leave Transsion Core)\n"
        "Who can use: Join - group owner; leave - group owner or TC admin."
    ),
    "help_stats": (
        "<b>Statistics Module</b>\n"
        "Commands: /tcstats, /stats, /tcinfo\n"
        "Usage: /tcstats\n"
        "Who can use: Everyone.\n"
        "Displays current Transsion Core stats: owner, admin count, affiliated groups, active bans."
    ),
    "help_cleanup": (
        "<b>Cleanup Module</b>\n"
        "Commands: /cleanup, /purge, /tcclean\n"
        "Usage: /cleanup\n"
        "Who can use: Transsion Core Owner and Admins.\n"
        "Checks all affiliated groups and removes those where the bot is no longer present."
    ),
}

HELP_MODULE_ROWS: list[list[tuple[str, str]]] = [
    [("Ban", "help_ban"), ("Unban", "help_unban")],
    [("Check Ban", "help_check"), ("Ban Info", "help_baninfo")],
    [("Promote/Demote", "help_admin"), ("Transfer Owner", "help_transfer")],
    [("Broadcast", "help_broadcast"), ("Sync Ban", "help_syncban")],
    [("Group Affiliation", "help_affiliation"), ("Disaffiliate", "help_defed")],
    [("Appeal", "help_appeal"), ("Join/Leave", "help_join")],
    [("Statistics", "help_stats"), ("Cleanup", "help_cleanup")],
]


def _state(context: ContextTypes.DEFAULT_TYPE) -> Dict[str, Any]:
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


def _get_entry(
    context: ContextTypes.DEFAULT_TYPE, chat_id: int, message_id: int
) -> Optional[Dict[str, Any]]:
    return _state(context).get(_key(chat_id, message_id))


def _is_owner(
    context: ContextTypes.DEFAULT_TYPE, chat_id: int, message_id: int, user_id: int
) -> bool:
    s = _get_entry(context, chat_id, message_id)
    return s is None or s["user_id"] == user_id


def _mode(context: ContextTypes.DEFAULT_TYPE, chat_id: int, message_id: int) -> str:
    s = _get_entry(context, chat_id, message_id)
    return s["mode"] if s else "menu"


def _start_keyboard() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(
        [
            [
                InlineKeyboardButton("About", callback_data="menu_about"),
                InlineKeyboardButton("Help", callback_data="menu_help"),
            ],
            [
                InlineKeyboardButton("Groups", callback_data="menu_groups"),
                InlineKeyboardButton("Additional", callback_data="menu_additional"),
            ],
            [InlineKeyboardButton("Information", callback_data="menu_information")],
            [InlineKeyboardButton("Privacy", callback_data="menu_privacy")],
        ]
    )


def _back_to_start_kb() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(
        [[InlineKeyboardButton("Back", callback_data="menu_back_start")]]
    )


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
        rows.append(
            [InlineKeyboardButton("Main Menu", callback_data="menu_back_start")]
        )
    return InlineKeyboardMarkup(rows)


def _info_kb() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(
        [
            [
                InlineKeyboardButton("Admins", callback_data="info_admins"),
                InlineKeyboardButton("Connected Chats", callback_data="info_chats"),
            ],
            [InlineKeyboardButton("Back", callback_data="menu_back_start")],
        ]
    )


def _info_back_kb() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(
        [[InlineKeyboardButton("Back", callback_data="menu_information")]]
    )


async def send_start_menu(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Send the interactive start menu."""
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


async def send_help_command(
    update: Update, context: ContextTypes.DEFAULT_TYPE
) -> None:
    """Send the help module list (no start-menu Back button)."""
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


async def on_menu_callback(
    update: Update, context: ContextTypes.DEFAULT_TYPE
) -> None:
    """Route all start menu, help, information, and privacy callbacks."""
    cq = update.callback_query
    if (
        cq is None
        or cq.message is None
        or getattr(cq, "from_user", None) is None
        or getattr(cq, "data", None) is None
    ):
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
        await _edit(cq, ABOUT_TEXT, _back_to_start_kb())
        return

    if data == "menu_help":
        await _edit(cq, HELP_INTRO_TEXT, _help_modules_kb(with_back_to_start=True))
        return

    if data == "menu_help_main":
        await _edit(
            cq,
            HELP_INTRO_TEXT,
            _help_modules_kb(with_back_to_start=(mode == "menu")),
        )
        return

    if data == "menu_groups":
        groups_text = await build_fedgroups_text()
        kb = InlineKeyboardMarkup(
            [[InlineKeyboardButton("Back", callback_data="menu_back_start")]]
        )
        await _edit(cq, groups_text, kb)
        return

    if data == "menu_additional":
        text, links_kb = get_links_view()
        rows = list(links_kb.inline_keyboard) + [
            [InlineKeyboardButton("Back", callback_data="menu_back_start")]
        ]
        await _edit(cq, text, InlineKeyboardMarkup(rows))
        return

    if data == "menu_information":
        info_text = await build_fedstats_text(context)
        info_text = info_text.replace("<b>TCF Statistics</b>", "<b>Transsion Core Information</b>")
        await _edit(cq, info_text, _info_kb())
        return

    if data == "info_admins":
        admins_text = await build_admins_text(context)
        await _edit(cq, admins_text, _info_back_kb())
        return

    if data == "info_chats":
        chats_text = await build_fedgroups_text()
        await _edit(cq, chats_text, _info_back_kb())
        return

    if data == "menu_privacy":
        kb = InlineKeyboardMarkup(
            [
                [InlineKeyboardButton("Privacy Policy", callback_data="menu_privacy_policy")],
                [InlineKeyboardButton("Back", callback_data="menu_back_start")],
            ]
        )
        await _edit(cq, PRIVACY_MAIN_TEXT, kb)
        return

    if data == "menu_privacy_policy":
        kb = InlineKeyboardMarkup(
            [[InlineKeyboardButton("Back", callback_data="menu_privacy")]]
        )
        await _edit(cq, PRIVACY_POLICY_TEXT, kb, parse_mode=None)
        return

    if data in HELP_DETAILS:
        await _edit(cq, HELP_DETAILS[data], _help_detail_kb(mode))
        return


async def _edit(
    cq: Any,
    text: str,
    kb: InlineKeyboardMarkup,
    parse_mode: ParseMode | None = ParseMode.HTML,
) -> None:
    """Edit the menu message; silently ignore 'not modified' errors."""
    try:
        await cq.edit_message_text(
            text,
            reply_markup=kb,
            parse_mode=parse_mode,
            disable_web_page_preview=True,
        )
    except TelegramError as exc:
        logger.debug("Menu edit ignored: %s", exc)
