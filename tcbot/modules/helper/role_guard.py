# © Copyright 2024 - 2026 Transsion Core
# © Copyright 2024 - 2026 Dizzy
# © Copyright 2026 Aveum Apps

"""Shared role-permission helpers – ``resolve_and_check()`` and ``auto_demote()`` for moderation flows."""

from __future__ import annotations

import asyncio
import logging

from telegram import Bot

from tcbot import cfg
from tcbot import database as db
from tcbot.database.roles_db import ROLE_LABEL, get_effective_role, role_rank
from tcbot.modules.helper import parse_logmsg

log = logging.getLogger(__name__)


async def resolve_and_check(
    msg,
    executor_id: int,
    target_id: int,
    *,
    min_role: str,
) -> tuple[str | None, str | None]:
    """Validate executor permission and target eligibility.

    Returns (executor_role, target_role) on success, or (None, None) after
    replying with an error message.  Both DB checks run in parallel.

    min_role: minimum role needed - "developer" for ban/unban, "tester" for
    kick/mute/warn.
    """
    executor_role, target_role = await asyncio.gather(
        get_effective_role(executor_id),
        get_effective_role(target_id),
    )
    if role_rank(executor_role) < role_rank(min_role):
        await msg.reply_text("You don't have the rank for this one. 🚫")
        return None, None

    if target_role:
        if role_rank(executor_role) <= role_rank(target_role):
            label = ROLE_LABEL.get(target_role, target_role.capitalize())
            await msg.reply_text(
                f"That's a {label} - they outrank you here, can't take action on them."
            )
            return None, None

    return executor_role, target_role


async def auto_demote(
    bot: Bot,
    target_id: int,
    target_fname: str,
    target_role: str,
    executor_id: int,
    executor_fname: str,
    action: str,
) -> None:
    """Remove a role from a user after a ban or kick, then log and notify them in parallel."""
    if target_role == "admin":
        await db.admins_db.remove_admin(target_id)
    else:
        await db.roles_db.remove_role(target_id)

    lc, lt = cfg.logs
    verb = "banned" if action == "ban" else "kicked"
    label = ROLE_LABEL.get(target_role, target_role.capitalize())

    await asyncio.gather(
        bot.send_message(
            lc,
            parse_logmsg.role_auto_demoted(
                target_id,
                target_fname,
                target_role,
                executor_id,
                executor_fname,
                action,
            ),
            parse_mode="HTML",
            message_thread_id=lt,
        ),
        bot.send_message(
            target_id,
            f"Your <b>{label}</b> role in {cfg.community_name} has been removed - "
            f"you were {verb} from the federation.",
            parse_mode="HTML",
        ),
        return_exceptions=True,
    )
