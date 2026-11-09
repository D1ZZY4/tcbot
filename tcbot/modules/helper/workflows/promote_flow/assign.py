# © Copyright 2024 - 2026 Transsion Core
# © Copyright 2024 - 2026 Dizzy
# © Copyright 2026 Ave Labs

"""Direct role-assignment executors for promotions."""

from __future__ import annotations

import asyncio
from typing import TYPE_CHECKING

from tcbot import cfg
from tcbot import database as db
from tcbot.modules.helper import parse_logmsg
from tcbot.modules.helper.locale import locale_for_user
from tcbot.utils.dispatch import throw_if_cancelled
from tcbot.utils.formatter import user_ref
from tcbot.utils.i18n import Safe, t
from tcbot.utils.logger import get_logger

if TYPE_CHECKING:
    from telegram import Bot

# * Logger keeps the pre-split name so log output is unchanged.
log = get_logger("tcbot.modules.helper.workflows.promote_flow")


async def assign_admin(
    bot: Bot,
    admin_id: int,
    admin_fname: str,
    target_id: int,
    target_fname: str,
    current_role: str | None,
    locale: str | None = None,
) -> tuple[bool, str]:
    """Founder-only path: directly add the target to tc_admins and log it."""
    # * Write the primary record first; if this fails the target is never promoted,
    # * leaving a consistent state (no partial write).
    try:
        await db.users_roles.add_admin(target_id, admin_id)
    except Exception:
        log.exception("_assign_admin: add_admin failed for target=%d", target_id)
        return False, t("admins.promote.save_fail", locale)
    # * Secondary cleanup: purge any old tc_roles entry and update the user cache.
    # * These are non-critical; a failure leaves the user correctly promoted so we
    # * log a warning instead of aborting.
    cleanup: list = [db.users_cache.upsert_user(target_id, None, target_fname)]
    if current_role in ("developer", "tester"):
        cleanup.append(db.users_roles.remove_role(target_id))
    cleanup_results = await asyncio.gather(*cleanup, return_exceptions=True)
    throw_if_cancelled(cleanup_results)
    for _r in cleanup_results:
        if isinstance(_r, BaseException):
            log.warning(
                "_assign_admin cleanup step failed for target=%d: %s", target_id, _r
            )
    lc, lt = cfg.logs
    log_text = parse_logmsg.promoted(
        target_id, target_fname, "admin", admin_id, admin_fname
    )
    target_locale = await locale_for_user(target_id)
    admin_results = await asyncio.gather(
        bot.send_message(lc, log_text, parse_mode="MarkdownV2", message_thread_id=lt),
        bot.send_message(
            target_id,
            t(
                "admins.promote.dm.admin",
                target_locale,
                community=cfg.community_name,
                plain=True,
            ),
        ),
        return_exceptions=True,
    )
    throw_if_cancelled(admin_results)
    for result in admin_results:
        if isinstance(result, BaseException):
            log.warning(
                "_assign_admin log/DM send failed for target=%d: %s",
                target_id,
                result,
            )
    return True, t(
        "admins.promote.done_admin",
        locale,
        user=Safe(user_ref(target_id, target_fname)),
        community=cfg.community_name,
    )


async def assign_subrole(
    bot: Bot,
    admin_id: int,
    admin_fname: str,
    target_id: int,
    target_fname: str,
    current_role: str | None,
    role: str,
    locale: str | None = None,
) -> tuple[bool, str]:
    """Founder/Admin path for Developer/Tester role assignment."""
    if current_role == "admin":
        label = db.users_roles.ROLE_LABEL.get(role, role)
        return (
            False,
            t(
                "admins.promote.already_admin",
                locale,
                role=label,
            ),
        )
    # * set_role uses update_one(upsert=True) so it atomically replaces an existing
    # * developer/tester entry without a prior remove_role call.  This eliminates
    # * the partial-state window where the target holds no role between delete and insert.
    try:
        await db.users_roles.set_role(target_id, role, admin_id)
    except Exception:
        log.exception(
            "_assign_subrole: set_role failed for target=%d role=%s",
            target_id,
            role,
        )
        return False, t("admins.promote.role_fail", locale)
    # * Cache upsert is non-critical; log but do not abort.
    try:
        await db.users_cache.upsert_user(target_id, None, target_fname)
    except Exception as exc:
        log.warning(
            "_assign_subrole: upsert_user failed for target=%d: %s", target_id, exc
        )
    role_label = db.users_roles.ROLE_LABEL.get(role, role)
    lc, lt = cfg.logs
    log_text = parse_logmsg.promoted(
        target_id, target_fname, role, admin_id, admin_fname
    )
    target_locale = await locale_for_user(target_id)
    subrole_results = await asyncio.gather(
        bot.send_message(lc, log_text, parse_mode="MarkdownV2", message_thread_id=lt),
        bot.send_message(
            target_id,
            t(
                "admins.promote.dm.role",
                target_locale,
                role=role_label,
                community=cfg.community_name,
                plain=True,
            ),
        ),
        return_exceptions=True,
    )
    throw_if_cancelled(subrole_results)
    for result in subrole_results:
        if isinstance(result, BaseException):
            log.warning(
                "_assign_subrole log/DM send failed for target=%d: %s",
                target_id,
                result,
            )
    return (
        True,
        t(
            "admins.promote.done_role",
            locale,
            user=Safe(user_ref(target_id, target_fname)),
            community=cfg.community_name,
            role=role_label,
        ),
    )
