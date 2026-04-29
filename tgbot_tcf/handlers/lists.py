# © Copyright 2024 - 2026 Transsion Core
# © Copyright 2024 - 2026 Dizzy
# © Copyright 2026 Aveum Apps
"""Read-only listing handlers: /tcfgroups and /tcstats.

The text builders here are reused by :mod:`tgbot_tcf.handlers.menu` so
the same content powers both the slash commands and the inline menu views.
"""
import logging

from telegram import Update
from telegram.ext import ContextTypes

from ..database import admins_repo, bans_repo, groups_repo
from ..modules.messages import M
from ..utils.format import user_link
from .helper import messaging

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
    """Build the paginated affiliated-groups text used by command and menu."""
    groups = await groups_repo.list_active()
    if not groups:
        return M.NO_AFFILIATED_GROUPS
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
    owner_id = await admins_repo.get_owner_id()
    admins_count = await admins_repo.count_admins()
    groups_count = await groups_repo.count_active()
    bans_count = await bans_repo.count_active()

    if owner_id is not None:
        owner_name = await messaging.fetch_display_name(context, owner_id)
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


async def build_admins_text(
    context: ContextTypes.DEFAULT_TYPE, page: int = 0, page_size: int = 10
) -> str:
    """Build a paginated list of TC admins."""
    admins = [a async for a in admins_repo.iter_admins()]
    if not admins:
        return M.NO_TC_ADMINS
    start = page * page_size
    end = start + page_size
    page_admins = admins[start:end]
    lines = [f"<b>Transsion Core Admins</b> (Page {page + 1})"]
    for a in page_admins:
        uid = a["user_id"]
        name = await messaging.fetch_display_name(context, uid)
        lines.append(f"{name} (ID: {uid})")
    return "\n".join(lines)
