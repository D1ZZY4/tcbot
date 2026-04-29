"""Read-only listing commands: /fedgroups (Feature 10) and /fedstats (Feature 11)."""
import logging

from telegram import Update
from telegram.error import TelegramError
from telegram.ext import ContextTypes

from ..db import bans, fed_admins, federated_groups, fed_owners
from ..utils.format import user_link

logger = logging.getLogger(__name__)


async def cmd_fedgroups(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    msg = update.effective_message
    if msg is None:
        return
    text = await build_fedgroups_text()
    await msg.reply_text(text, parse_mode="HTML", disable_web_page_preview=True)


async def cmd_fedstats(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    msg = update.effective_message
    if msg is None:
        return
    text = await build_fedstats_text(context)
    await msg.reply_text(text, parse_mode="HTML", disable_web_page_preview=True)


async def build_fedgroups_text() -> str:
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


async def build_fedstats_text(context: ContextTypes.DEFAULT_TYPE) -> str:
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
