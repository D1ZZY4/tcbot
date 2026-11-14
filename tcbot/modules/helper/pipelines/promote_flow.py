# © Copyright 2024 - 2026 Transsion Core
# © Copyright 2024 - 2026 Dizzy
# © Copyright 2026 Ave Labs

"""Centralised promotion logic: role assignment and Admin promotion request flow."""

from __future__ import annotations

import asyncio
from typing import TYPE_CHECKING

from tcbot import cfg
from tcbot import database as db
from tcbot.modules.helper import keyboards, messages
from tcbot.modules.helper.guards import banned_target_refusal
from tcbot.modules.helper.locale import locale_for_user
from tcbot.modules.helper.messages import send_log
from tcbot.utils.dispatch import throw_if_cancelled
from tcbot.utils.formatter import user_ref
from tcbot.utils.i18n import Safe, t
from tcbot.utils.logger import get_logger

if TYPE_CHECKING:
    from telegram import Bot

log = get_logger(__name__)

# ───────────────────────── Role assignment ──────────────────────── #


async def assign_admin(
    bot: Bot,
    admin_id: int,
    admin_fname: str,
    target_id: int,
    target_fname: str,
    locale: str | None = None,
) -> tuple[bool, str]:
    """Founder-only path: directly give the target the admin role and log it."""
    try:
        await db.users_roles.add_admin(target_id, admin_id)
    except Exception:
        log.exception("_assign_admin: add_admin failed for target=%d", target_id)
        return False, t("admins.promote.save_fail", locale)
    # * The assignment revokes the role the target held before it, in the
    # * same transaction, so no second cleanup write is needed. One that
    # * revoked the roles again afterwards would also revoke the admin
    # * role it had just written.
    cleanup_results = await asyncio.gather(
        db.users_cache.upsert_user(target_id, None, target_fname),
        return_exceptions=True,
    )
    throw_if_cancelled(cleanup_results)
    for _r in cleanup_results:
        if isinstance(_r, BaseException):
            log.warning(
                "_assign_admin cleanup step failed for target=%d: %s", target_id, _r
            )
    log_text = messages.promoted(
        target_id, target_fname, "admin", admin_id, admin_fname
    )
    target_locale = await locale_for_user(target_id)
    admin_results = await asyncio.gather(
        send_log(bot, log_text),
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
        label = db.users_roles.role_label(role)
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
    role_label = db.users_roles.role_label(role)
    log_text = messages.promoted(target_id, target_fname, role, admin_id, admin_fname)
    target_locale = await locale_for_user(target_id)
    subrole_results = await asyncio.gather(
        send_log(bot, log_text),
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
    # * A banned user must not reach the Founder's approval card: the
    # * request path is public, so the guard belongs here as well as on
    # * the approval itself.
    refusal = await banned_target_refusal(
        target_id, locale, log_label="promote request ban-guard"
    )
    if refusal is not None:
        return False, refusal
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
    if isinstance(request_id, db.queues_db.DuplicateKeyError):
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
    req_text = messages.promote_request_log(
        target_id, target_fname, target_username, request_id
    )
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
            await send_log(
                bot,
                req_text,
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
        """Return the tiers an executor with the given role may hand out.

        Single owner of the grant table: the role picker and the
        executor read the same list, so an executor can never be offered
        a tier the executor would then refuse to grant.
        """
        if executor_role == "founder":
            return ["admin", "developer", "tester"]
        if executor_role == "admin":
            return ["developer", "tester"]
        return []

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
        # * The grant table is read here, not only in the role picker: the
        # * command and the callback both check the executor, but the
        # * helper owns the rule so a future caller cannot hand out rank
        # * from a tier that may not grant it.
        allowed = cls.available_roles_for(executor_role)
        if current_role == "founder":
            return False, t("admins.promote.target_is_founder", locale)
        if db.users_roles.role_rank(current_role) >= db.users_roles.role_rank(role):
            label = db.users_roles.role_label(current_role)
            return False, t("admins.promote.holds_role", locale, role=label)
        # * Single chokepoint for every direct promotion (the command and the
        # * role-picker callback both land here): a banned user must not gain
        # * federation rank, because the ban is enforced per group by
        # * Telegram and not by the bot's own role resolution.
        refusal = await banned_target_refusal(
            target_id, locale, log_label="promote ban-guard"
        )
        if refusal is not None:
            return False, refusal
        if role == "admin":
            # * Only the Founder grants the Admin tier outright. An Admin
            # * may request it, and the Founder decides on the request.
            if executor_role == "founder":
                return await assign_admin(
                    bot,
                    admin_id,
                    admin_fname,
                    target_id,
                    target_fname,
                    locale,
                )
            if executor_role == "admin":
                return await cls.request_admin(
                    bot, admin_id, target_id, target_fname, locale=locale
                )
            return False, t("admins.promote.no_assign_perms", locale)
        if role not in allowed:
            return False, t("admins.promote.no_assign_perms", locale)
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
