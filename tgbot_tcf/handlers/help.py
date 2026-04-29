"""Help and informational commands."""
import logging

from telegram import Update
from telegram.constants import ChatType
from telegram.ext import ContextTypes

from ..config import ABOUT_TEXT
from .appeal import start_appeal
from .menu import send_start_menu

logger = logging.getLogger(__name__)


HELP_TEXT = (
    "<b>Transsion Core Federation Bot</b>\n\n"
    "<b>For everyone</b>\n"
    "/checkme, /myban, /amibanned - Check if you are banned in TCF.\n"
    "/baninfo, /checkban, /banstatus &lt;target&gt; - View ban details for a user.\n"
    "/fedgroups, /groups, /listfed - List federation-affiliated groups.\n"
    "/fedstats, /stats, /fedinfo - Federation statistics.\n"
    "/fedchannels, /channels, /fedconfig - Show configured channel/group IDs.\n"
    "/about, /tcfabout, /fedabout - About the federation.\n"
    "/help, /commands - Show this help message.\n\n"
    "<b>Group affiliation</b>\n"
    "/joinfed, /requestjoin, /applyfed - Request to affiliate the current group.\n"
    "/defed, /leavefed, /unfed - Disaffiliate the current group.\n\n"
    "<b>Federation admins / owner</b>\n"
    "/cban, /comban, /fban &lt;target&gt; &lt;reason&gt; - Ban a user across the federation (requires proof).\n"
    "/cunban, /comunban, /funban &lt;target&gt; - Unban a user from the federation.\n"
    "/syncban, /forcesync, /fbanall &lt;target&gt; - Re-enforce a ban across all groups.\n"
    "/broadcast, /announce, /fcast &lt;message&gt; - Broadcast a message to all groups.\n"
    "/rmfed, /removefed, /deletefed &lt;group_id&gt; - Remove a group from the federation.\n"
    "/cleanup, /purge, /fedclean - Clean up groups the bot was kicked from.\n\n"
    "<b>Owner only</b>\n"
    "/cpromote, /compromote, /fpromote &lt;target&gt; - Promote to Federation Admin.\n"
    "/cdemote, /comdemote, /fdemote &lt;target&gt; - Demote a Federation Admin.\n"
    "/transferowner, /tfowner, /fedowner &lt;target&gt; - Transfer federation ownership.\n"
    "/leaveall, /exitall, /fedleave - Leave every affiliated group."
)


async def cmd_help(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    msg = update.effective_message
    if msg is None:
        return
    await msg.reply_text(HELP_TEXT, parse_mode="HTML", disable_web_page_preview=True)


async def cmd_about(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    msg = update.effective_message
    if msg is None:
        return
    await msg.reply_text(ABOUT_TEXT, disable_web_page_preview=True)


async def cmd_start(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    msg = update.effective_message
    args = context.args or []
    if args and args[0].startswith("appeal_"):
        ban_id = args[0][len("appeal_"):]
        await start_appeal(update, context, ban_id)
        return
    # In private chat, show the interactive start menu (Feature 24).
    # Outside PM, fall back to the static help text.
    if msg is not None and msg.chat.type == ChatType.PRIVATE:
        await send_start_menu(update, context)
        return
    await cmd_help(update, context)
