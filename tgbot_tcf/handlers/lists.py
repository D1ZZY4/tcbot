# © Copyright 2024 - 2026 Transsion Core
# © Copyright 2024 - 2026 Dizzy
# © Copyright 2026 Aveum Apps
"""Read-only listing handlers: /tcfgroups and /tcstats.

The text builders here are reused by :mod:`tgbot_tcf.handlers.menu` so
the same content powers both the slash commands and the inline menu views.
"""
from __future__ import annotations

import asyncio
import logging

from telegram import Update
from telegram.constants import ParseMode
from telegram.ext import ContextTypes

from ..database import admins_repo, bans_repo, groups_repo
from ..modules.messages import M
from ..utils.format import user_link
from ..utils.users import resolve_identity

logger = logging.getLogger(__name__)


async def cmd_fedgroups(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """List all active federated groups."""
    msg = update.effective_message
    if msg is None:
        return
    text = await build_fedgroups_text()
    await msg.reply_text(text, parse_mode=ParseMode.HTML, disable_web_page_preview=True)


async def cmd_fedstats(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Show Transsion Core statistics."""
    msg = update.effective_message
    if msg is None:
        return
    text = await build_fedstats_text(context)
    await msg.reply_text(text, parse_mode=ParseMode.HTML, disable_web_page_preview=True)


async def cmd_tcadmins(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Show the Transsion Core Owner and every TC Admin in one view."""
    msg = update.effective_message
    if msg is None:
        return
    text = await build_admins_text(context)
    await msg.reply_text(
        text, parse_mode=ParseMode.HTML, disable_web_page_preview=True
    )


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
        owner_name = (await resolve_identity(context, owner_id)).display_name
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


async def build_admins_text(context: ContextTypes.DEFAULT_TYPE) -> str:
    """Render the Owner + TC Admins overview in the spec-locked format.

    Layout::

        There is Admin in
        <branding>

        Owner: <Nickname> [<user_id>]
        Admins:
        - <nickname> [@username] | <user_id>
        - <nickname> | <user_id>          (when the admin has no @username)

    When neither an Owner nor any Admin exists, ``NO_TC_ADMINS`` is
    returned so the caller can simply send the result.
    """
    owner_id = await admins_repo.get_owner_id()
    admins = [
        a async for a in admins_repo.iter_admins() if a["user_id"] != owner_id
    ]

    if owner_id is None and not admins:
        return M.NO_TC_ADMINS

    lines: list[str] = [M.ADMINS_LIST_HEADER, M.BRANDING_LINE, ""]

    if owner_id is not None:
        owner_ident = await resolve_identity(context, owner_id)
        lines.append(
            f"Owner: {user_link(owner_id, owner_ident.display_name)} [{owner_id}]"
        )

    if admins:
        lines.append("Admins:")
        identities = await asyncio.gather(
            *(resolve_identity(context, a["user_id"]) for a in admins)
        )
        for a, ident in zip(admins, identities, strict=True):
            uid = a["user_id"]
            link = user_link(uid, ident.display_name)
            if ident.username:
                lines.append(f"- {link} [@{ident.username}] | {uid}")
            else:
                lines.append(f"- {link} | {uid}")

    return "\n".join(lines)
