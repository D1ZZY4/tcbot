# © Copyright 2024 - 2026 Transsion Core
# © Copyright 2024 - 2026 Dizzy
# © Copyright 2026 Aveum Apps

"""Promote execution flow – role assignment and request logic shared by admins.py."""

from __future__ import annotations

import asyncio
import logging

from telegram import Bot

from tcbot import cfg, database as db
from tcbot.database.roles_db import ROLE_LABEL, get_effective_role, role_rank
from tcbot.modules.helper import keyboards, parse_logmsg
from tcbot.modules.helper.formatter import mention

log = logging.getLogger(__name__)

_ROLE_ALIASES: dict[str, str] = {
    "admin":     "admin",
    "developer": "developer",
    "dev":       "developer",
    "tester":    "tester",
    "test":      "tester",
}


def _available_roles_for(executor_role: str) -> list[str]:
    if executor_role == "founder":
        return ["admin", "developer", "tester"]
    if executor_role == "admin":
        return ["developer", "tester"]
    return []


## ── Shared promote executor ────────────────────────────────────────────────

async def _execute_promote(
    bot: Bot,
    admin_id: int,
    admin_fname: str,
    executor_role: str,
    target_id: int,
    target_fname: str,
    current_role: str | None,
    role: str,
) -> tuple[bool, str]:
    """Execute a role assignment and return (success, reply_text)."""
    if current_role == "founder":
        return False, "That's the Founder - can't assign a role over them. 👑"

    if role_rank(current_role) >= role_rank(role):
        label = ROLE_LABEL.get(current_role, current_role)
        return False, f"That user already holds the {label} role or higher."

    lc, lt = cfg.logs

    if role == "admin":
        if executor_role == "founder":
            ## DB writes in parallel
            if current_role in ("developer", "tester"):
                await asyncio.gather(
                    db.admins_db.add_admin(target_id, admin_id),
                    db.roles_db.remove_role(target_id),
                    db.users_db.upsert_user(target_id, None, target_fname),
                )
            else:
                await asyncio.gather(
                    db.admins_db.add_admin(target_id, admin_id),
                    db.users_db.upsert_user(target_id, None, target_fname),
                )
            log_text = parse_logmsg.admin_promoted(target_id, target_fname, admin_id, admin_fname)
            ## log and notify in parallel
            await asyncio.gather(
                bot.send_message(lc, log_text, parse_mode="HTML", message_thread_id=lt),
                bot.send_message(
                    target_id,
                    f"You've been promoted to Admin in {cfg.community_name} - welcome to the staff team! 🎉",
                ),
                return_exceptions=True,
            )
            return True, (
                f"Done. {mention(target_id, target_fname)} is now a {cfg.community_name} Admin."
            )

        ## executor is admin → send request to owner for approval
        existing = await db.queues_db.get_request(target_id)
        if existing:
            return False, (
                f"There's already a pending promotion request for "
                f"{mention(target_id, target_fname)}."
            )
        ## enqueue + get_owner_id in parallel
        request_id, owner_id = await asyncio.gather(
            db.queues_db.enqueue(target_id, None, target_fname, admin_id),
            db.admins_db.get_owner_id(),
        )
        req_text = parse_logmsg.promo_request_log(target_id, target_fname, None, request_id)
        notified   = False
        if owner_id:
            try:
                await bot.send_message(
                    owner_id, req_text, parse_mode="HTML",
                    reply_markup=keyboards.promo_decision_kb(request_id),
                )
                notified = True
            except Exception as exc:
                log.warning("Owner DM failed, falling back to log channel: %s", exc)
        if not notified:
            try:
                await bot.send_message(
                    lc, req_text, parse_mode="HTML",
                    message_thread_id=lt,
                    reply_markup=keyboards.promo_decision_kb(request_id),
                )
            except Exception as exc:
                log.error("Promo request notify failed: %s", exc)
        return True, "Submitted - the Founder has been notified and will review it shortly. ✅"

    ## role in ("developer", "tester")
    if executor_role not in ("founder", "admin"):
        return False, "You don't have permission to assign this role."

    if current_role == "admin":
        label = ROLE_LABEL.get(role, role)
        return False, f"That user is already an Admin. Demote them first before assigning {label}."

    if current_role in ("developer", "tester"):
        await db.roles_db.remove_role(target_id)

    ## set_role + upsert_user in parallel
    await asyncio.gather(
        db.roles_db.set_role(target_id, role, admin_id),
        db.users_db.upsert_user(target_id, None, target_fname),
    )

    role_label = ROLE_LABEL.get(role, role)
    log_text   = parse_logmsg.role_assigned(target_id, target_fname, role, admin_id, admin_fname)
    ## log and notify in parallel
    await asyncio.gather(
        bot.send_message(lc, log_text, parse_mode="HTML", message_thread_id=lt),
        bot.send_message(
            target_id,
            f"You've been assigned the {role_label} role in {cfg.community_name} - welcome to the team! 🎉",
        ),
        return_exceptions=True,
    )
    return True, f"Done. {mention(target_id, target_fname)} is now a {cfg.community_name} {role_label}."
