# © Copyright 2024 - 2026 Transsion Core
# © Copyright 2024 - 2026 Dizzy
# © Copyright 2026 Aveum Apps
"""Read-only listing commands: /tcfgroups and /tcstats."""
import logging

from telegram import Update
from telegram.error import TelegramError
from telegram.ext import ContextTypes

from ..database import bans, federated_groups, tc_admins, tc_owners
from ..utils.format import user_link

logger = logging.getLogger(__name__)


async def cmd_fedgroups(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """List all active federated groups."""
    msg = update.effective_message
    if msg is None:
        return
    text = await build_fedgroups_text()
    await msg.reply_text(text, parse_mode="HTML", disable_web_page_preview=True)


async def cmd_fedstats(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Show Transsion Core statistics."""
    msg = update.effective_message
    if msg is None:
        return
    text = await build_fedstats_text(context)
    await msg.reply_text(text, parse_mode="HTML", disable_web_page_preview=True)


async def build_fedgroups_text(page: int = 0, page_size: int = 10) -> str:
    """Build paginated affiliated groups text."""
    cursor = federated_groups.find({"is_active": True})
    groups = [g async for g in cursor]
    if not groups:
        return "No groups are currently affiliated with TCF."
    start = page * page_size
    end = start + page_size
    page_groups = groups[start:end]
    lines = [f"<b>Affiliated TCF Groups</b> (Page {page + 1})"]
    for g in page_groups:
        title = g.get("title") or str(g["chat_id"])
        lines.append(f"{title} (ID: {g['chat_id']})")
    return "\n".join(lines)


async def build_fedstats_text(context: ContextTypes.DEFAULT_TYPE) -> str:
    """Build the TCF statistics text."""
    owner = await tc_owners.find_one({})
    admins_count = await tc_admins.count_documents({})
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
        "<b>TCF Statistics</b>\n"
        f"Owner: {owner_line}\n"
        f"Admin Count: {admins_count}\n"
        f"Affiliated Groups: {groups_count}\n"
        f"Active Bans: {bans_count}"
    )


async def build_admins_text(context: ContextTypes.DEFAULT_TYPE, page: int = 0, page_size: int = 10) -> str:
    """Build a paginated list of TC admins."""
    cursor = tc_admins.find({})
    admins = [a async for a in cursor]
    if not admins:
        return "There are no Transsion Core Admins at this time."
    start = page * page_size
    end = start + page_size
    page_admins = admins[start:end]
    lines = [f"<b>Transsion Core Admins</b> (Page {page + 1})"]
    for a in page_admins:
        uid = a["user_id"]
        try:
            chat = await context.bot.get_chat(uid)
            name = chat.first_name or str(uid)
        except TelegramError:
            name = str(uid)
        lines.append(f"{name} (ID: {uid})")
    return "\n".join(lines)
