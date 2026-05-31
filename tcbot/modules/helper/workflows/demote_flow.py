# © Copyright 2024 - 2026 Transsion Core
# © Copyright 2024 - 2026 Dizzy
# © Copyright 2026 Aveum Apps

"""Centralised demotion logic — manual via /tcdemote and auto-demote on ban/kick."""

from __future__ import annotations

import asyncio
import logging

from telegram import Bot

from tcbot import cfg
from tcbot import database as db
from tcbot.modules.helper import parse_logmsg

log = logging.getLogger(__name__)


# ────────────────────────── Demote class ────────────────────────── #


class Demote:
    """All federation-demotion logic.

    * ``execute(trigger=None)`` runs the manual /tcdemote path.
    * ``execute(trigger="ban")`` / ``"kick"`` runs the auto-demote path used by
      the ban and kick flows before the actual moderation action.
    """

    @staticmethod
    async def remove_role(target_id: int, target_role: str) -> bool:
        """Remove the user's role from the correct collection."""
        if target_role == "admin":
            return await db.users_roles.remove_admin(target_id)
        return await db.users_roles.remove_role(target_id)

    @classmethod
    async def execute(
        cls,
        bot: Bot,
        target_id: int,
        target_fname: str,
        target_role: str,
        executor_id: int,
        executor_fname: str,
        *,
        trigger: str | None = None,
    ) -> bool:
        """Remove the role, post a federation log, and DM the target.

        Returns True if the role was actually removed.
        """
        removed = await cls.remove_role(target_id, target_role)
        if not removed:
            return False

        lc, lt = cfg.logs
        log_text = parse_logmsg.demoted(
            target_id,
            target_fname,
            target_role,
            executor_id,
            executor_fname,
            trigger=trigger,
        )

        role_label = db.users_roles.ROLE_LABEL.get(
            target_role, target_role.capitalize()
        )
        if trigger is None:
            user_msg = (
                f"Your {role_label} role in {cfg.community_name} has been removed by "
                f"{executor_fname}."
            )
        else:
            verb = "banned" if trigger == "ban" else "kicked"
            user_msg = (
                f"Your <b>{role_label}</b> role in {cfg.community_name} has been removed - "
                f"you were {verb} from the federation."
            )

        await asyncio.gather(
            bot.send_message(lc, log_text, parse_mode="HTML", message_thread_id=lt),
            bot.send_message(target_id, user_msg, parse_mode="HTML"),
            return_exceptions=True,
        )
        return True
