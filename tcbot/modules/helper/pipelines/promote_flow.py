# © Copyright 2024 - 2026 Transsion Core
# © Copyright 2024 - 2026 Dizzy
# © Copyright 2026 Ave Labs

"""Centralised promotion logic: role assignment and Admin promotion request flow."""

from __future__ import annotations

import asyncio
from typing import TYPE_CHECKING

from pymongo.errors import DuplicateKeyError

from tcbot import cfg
from tcbot import database as db
from tcbot.modules.helper import keyboards, parse_logmsg
from tcbot.modules.helper.locale import locale_for_user
from tcbot.utils.dispatch import throw_if_cancelled
from tcbot.utils.formatter import user_ref
from tcbot.utils.i18n import Safe, t
from tcbot.utils.logger import get_logger

if TYPE_CHECKING:
    from telegram import Bot

log = get_logger(__name__)

# ───────────────────────── Role assignment ──────────────────────── #


ROLE_ALIASES: dict[str, str] = {
    "admin": "admin",
    "developer": "developer",
    "dev": "developer",
    "tester": "tester",
    "test": "tester",
}


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
    try:
        await db.users_roles.add_admin(target_id, admin_id)
    except Exception:
        log.exception("_assign_admin: add_admin failed for target=%d", target_id)
        return False, t("admins.promote.save_fail", locale)
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
    try:
        await db.users_roles.set_role(target_id, role, admin_id)
    except Exception:
        log.exception(
            "_assign_subrole: set_role failed for target=%d role=%s",
            target_id,
            role,
        )
        return False, t("admins.promote.role_fail", locale)
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


# ────────────────────────── Admin request ───────────────────────── #


async def request_admin(
    bot: Bot,
    admin_id: int,
    target_id: int,
    target_fname: str,
    target_username: str | None = None,
    locale: str | None = None,
) -> tuple[bool, str]:
    """Enqueue an Admin promotion request and notify the Founder."""
    try:
        existing = await db.queues_db.get_request(target_id)
    except Exception:
        log.warning(
            "request_admin pre-check failed for target=%d; relying on unique index",
            target_id,
        )
        existing = None
    if existing:
        return False, t(
            "admins.promote.pending",
            locale,
            user=Safe(user_ref(target_id, target_fname)),
        )
    request_id, owner_id = await asyncio.gather(
        db.queues_db.enqueue(target_id, target_username, target_fname, admin_id),
        db.users_roles.get_owner_id(fresh=True),
        return_exceptions=True,
    )
    throw_if_cancelled((request_id, owner_id))
    # * Concurrent requests resolve through the unique pending index.
    if isinstance(request_id, DuplicateKeyError):
        log.info(
            "Promotion request race for target=%d; using existing entry",
            target_id,
        )
        return False, t(
            "admins.promote.pending",
            locale,
            user=Safe(user_ref(target_id, target_fname)),
        )
    if isinstance(request_id, BaseException):
        log.error("Failed to enqueue promotion request: %s", request_id)
        return False, t("admins.promote.queue_fail", locale)
    if isinstance(owner_id, BaseException):
        log.warning("Failed to fetch owner id for promo notify: %s", owner_id)
        owner_id = None
    req_text = parse_logmsg.promote_request_log(
        target_id, target_fname, target_username, request_id
    )
    lc, lt = cfg.logs
    notified = False
    if owner_id:
        try:
            await bot.send_message(
                owner_id,
                req_text,
                parse_mode="MarkdownV2",
                reply_markup=keyboards.promo_decision_kb(request_id),
            )
            notified = True
        except Exception as exc:
            log.warning("Owner DM failed, falling back to log channel: %s", exc)
    if not notified:
        try:
            await bot.send_message(
                lc,
                req_text,
                parse_mode="MarkdownV2",
                message_thread_id=lt,
                reply_markup=keyboards.promo_decision_kb(request_id),
            )
        except Exception:
            log.exception("Promo request notify failed")
    return (True, t("admins.promote.submitted", locale))


# ───────────────────────────── Promote ──────────────────────────── #


class Promote:
    """All federation-promotion logic."""

    @staticmethod
    def available_roles_for(executor_role: str) -> list[str]:
        """Return the roles an executor with the given role is allowed to assign."""
        if executor_role == "founder":
            return ["admin", "developer", "tester"]
        if executor_role == "admin":
            return ["developer", "tester"]
        return []

    @staticmethod
    async def _assign_admin(
        bot: Bot,
        admin_id: int,
        admin_fname: str,
        target_id: int,
        target_fname: str,
        current_role: str | None,
        locale: str | None = None,
    ) -> tuple[bool, str]:
        return await assign_admin(
            bot, admin_id, admin_fname, target_id, target_fname, current_role, locale
        )

    @staticmethod
    async def _assign_subrole(
        bot: Bot,
        admin_id: int,
        admin_fname: str,
        target_id: int,
        target_fname: str,
        current_role: str | None,
        role: str,
        locale: str | None = None,
    ) -> tuple[bool, str]:
        return await assign_subrole(
            bot,
            admin_id,
            admin_fname,
            target_id,
            target_fname,
            current_role,
            role,
            locale,
        )

    @classmethod
    async def request_admin(
        cls,
        bot: Bot,
        admin_id: int,
        target_id: int,
        target_fname: str,
        target_username: str | None = None,
        locale: str | None = None,
    ) -> tuple[bool, str]:
        """Enqueue an Admin promotion request and notify the Founder."""
        return await request_admin(
            bot, admin_id, target_id, target_fname, target_username, locale
        )

    @classmethod
    async def execute(
        cls,
        bot: Bot,
        admin_id: int,
        admin_fname: str,
        executor_role: str,
        target_id: int,
        target_fname: str,
        current_role: str | None,
        role: str,
        locale: str | None = None,
    ) -> tuple[bool, str]:
        """Execute a role assignment. Returns (success, reply_text)."""
        if current_role == "founder":
            return False, t("admins.promote.target_is_founder", locale)
        if db.users_roles.role_rank(current_role) >= db.users_roles.role_rank(role):
            label = db.users_roles.ROLE_LABEL.get(
                current_role or "", current_role or ""
            )
            return False, t("admins.promote.holds_role", locale, role=label)
        if role == "admin":
            if executor_role == "founder":
                return await cls._assign_admin(
                    bot,
                    admin_id,
                    admin_fname,
                    target_id,
                    target_fname,
                    current_role,
                    locale,
                )
            return await cls.request_admin(
                bot, admin_id, target_id, target_fname, locale=locale
            )
        if executor_role not in ("founder", "admin"):
            return False, t("admins.promote.no_assign_perms", locale)
        return await cls._assign_subrole(
            bot,
            admin_id,
            admin_fname,
            target_id,
            target_fname,
            current_role,
            role,
            locale,
        )


__all__ = ["ROLE_ALIASES", "Promote"]
