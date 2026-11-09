# © Copyright 2024 - 2026 Transsion Core
# © Copyright 2024 - 2026 Dizzy
# © Copyright 2026 Ave Labs

"""Admin promotion request queue and founder notification."""

from __future__ import annotations

import asyncio
from typing import TYPE_CHECKING

from pymongo.errors import DuplicateKeyError

from tcbot import cfg
from tcbot import database as db
from tcbot.modules.helper import keyboards, parse_logmsg
from tcbot.utils.dispatch import throw_if_cancelled
from tcbot.utils.formatter import user_ref
from tcbot.utils.i18n import Safe, t
from tcbot.utils.logger import get_logger

if TYPE_CHECKING:
    from telegram import Bot

# * Logger keeps the pre-split name so log output is unchanged.
log = get_logger("tcbot.modules.helper.workflows.promote_flow")


async def request_admin(
    bot: Bot,
    admin_id: int,
    target_id: int,
    target_fname: str,
    target_username: str | None = None,
    locale: str | None = None,
) -> tuple[bool, str]:
    """Enqueue an Admin promotion request and notify the Founder (DM, then fallback to log)."""
    try:
        existing = await db.queues_db.get_request(target_id)
    except Exception:
        # * Transient read blip: fall through to the enqueue below rather
        # * than dying silently. The partial-unique pending index makes
        # * this safe: a lost race surfaces as DuplicateKeyError and gets
        # * the same "already pending" reply as a pre-check hit.
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
    # * Cancellation is never a queue verdict: propagate before the
    # * DuplicateKeyError / generic-error branches below coerce it.
    throw_if_cancelled((request_id, owner_id))
    if isinstance(request_id, DuplicateKeyError):
        # * Lost the insert race: another promote queued first under the
        # * pending-unique index. Report the existing request, not an error.
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
