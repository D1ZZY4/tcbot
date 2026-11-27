# © Copyright 2024 - 2026 Transsion Core
# © Copyright 2024 - 2026 Dizzy
# © Copyright 2026 Ave Labs

"""Role assignment and Admin promotion request queue helpers."""

from __future__ import annotations

import asyncio

from pyrogram import Client

from tcbot import cfg
from tcbot import database as db
from tcbot.modules.helper import buttons, messages
from tcbot.modules.helper.guards import banned_target_refusal
from tcbot.modules.helper.locale import locale_for_user
from tcbot.modules.helper.messages import send_log, send_text
from tcbot.utils.dispatch import throw_if_cancelled
from tcbot.utils.i18n import Safe, t, user_ref
from tcbot.utils.logger import get_logger

log = get_logger(__name__)


async def assign_admin(
    bot: Client,
    admin_id: int,
    admin_fname: str,
    target_id: int,
    target_fname: str,
    locale: str | None = None,
) -> tuple[bool, str]:
    """Owner-only path: directly give the target the admin role and log it."""
    try:
        await db.users_roles.add_admin(target_id, admin_id)
    except Exception:
        log.exception("assign_admin failed for target=%d", target_id)
        return False, t("admins.promote.save_fail", locale)
    cleanup_results = await asyncio.gather(
        db.users_cache.upsert_user(target_id, None, target_fname),
        return_exceptions=True,
    )
    throw_if_cancelled(cleanup_results)
    for result in cleanup_results:
        if isinstance(result, BaseException):
            log.warning("assign_admin cleanup failed for %d: %s", target_id, result)
    log_text = messages.promoted(
        target_id, target_fname, "admin", admin_id, admin_fname
    )
    target_locale = await locale_for_user(target_id)
    results = await asyncio.gather(
        send_log(bot, log_text),
        send_text(
            bot,
            target_id,
            t(
                "admins.promote.dm.admin",
                target_locale,
                community=cfg.community_name,
            ),
        ),
        return_exceptions=True,
    )
    throw_if_cancelled(results)
    for result in results:
        if isinstance(result, BaseException):
            log.warning("assign_admin log/DM failed for %d: %s", target_id, result)
    return True, t(
        "admins.promote.done_admin",
        locale,
        user=Safe(user_ref(target_id, target_fname)),
        community=cfg.community_name,
    )


async def assign_subrole(
    bot: Client,
    admin_id: int,
    admin_fname: str,
    target_id: int,
    target_fname: str,
    current_role: str | None,
    role: str,
    locale: str | None = None,
) -> tuple[bool, str]:
    """Owner/Admin path for Developer/Moderator role assignment."""
    if current_role == "admin":
        return False, t(
            "admins.promote.already_admin", locale, role=db.users_roles.role_label(role)
        )
    try:
        await db.users_roles.set_role(target_id, role, admin_id)
    except Exception:
        log.exception("assign_subrole failed for target=%d role=%s", target_id, role)
        return False, t("admins.promote.role_fail", locale)
    try:
        await db.users_cache.upsert_user(target_id, None, target_fname)
    except Exception as exc:
        log.warning("assign_subrole upsert failed for %d: %s", target_id, exc)
    role_label = db.users_roles.role_label(role)
    log_text = messages.promoted(target_id, target_fname, role, admin_id, admin_fname)
    target_locale = await locale_for_user(target_id)
    results = await asyncio.gather(
        send_log(bot, log_text),
        send_text(
            bot,
            target_id,
            t(
                "admins.promote.dm.role",
                target_locale,
                role=role_label,
                community=cfg.community_name,
            ),
        ),
        return_exceptions=True,
    )
    throw_if_cancelled(results)
    for result in results:
        if isinstance(result, BaseException):
            log.warning("assign_subrole log/DM failed for %d: %s", target_id, result)
    return True, t(
        "admins.promote.done_role",
        locale,
        user=Safe(user_ref(target_id, target_fname)),
        community=cfg.community_name,
        role=role_label,
    )


async def request_admin(
    bot: Client,
    admin_id: int,
    target_id: int,
    target_fname: str,
    target_username: str | None = None,
    locale: str | None = None,
) -> tuple[bool, str]:
    """Enqueue an Admin promotion request and notify the Owner."""
    refusal = await banned_target_refusal(
        target_id, locale, log_label="promote request ban-guard"
    )
    if refusal is not None:
        return False, refusal
    try:
        existing = await db.queues_db.get_request(target_id)
    except Exception:
        log.warning("request_admin pre-check failed for %d", target_id)
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
    if isinstance(request_id, db.queues_db.DuplicateKeyError):
        return False, t(
            "admins.promote.pending",
            locale,
            user=Safe(user_ref(target_id, target_fname)),
        )
    if isinstance(request_id, BaseException):
        log.error("Failed to enqueue promotion request: %s", request_id)
        return False, t("admins.promote.queue_fail", locale)
    if isinstance(owner_id, BaseException):
        owner_id = None
    req_text = messages.promote_request_log(
        target_id, target_fname, target_username, request_id
    )
    try:
        owner_locale = await locale_for_user(owner_id) if owner_id else None
    except Exception:
        owner_locale = None
    card_markup = buttons.promo_decision_btn(request_id, owner_locale)
    notified = False
    if owner_id:
        try:
            await send_text(bot, owner_id, req_text, reply_markup=card_markup)
            notified = True
        except Exception as exc:
            log.warning("Owner DM failed, falling back to log: %s", exc)
    if not notified:
        try:
            await send_log(bot, req_text, reply_markup=card_markup)
        except Exception:
            log.exception("Promo request notify failed")
    return True, t("admins.promote.submitted", locale)
