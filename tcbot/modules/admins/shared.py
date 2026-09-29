# © Copyright 2024 - 2026 Transsion Core
# © Copyright 2024 - 2026 Dizzy
# © Copyright 2026 Ave Labs

"""Shared resolve helpers for promote and demote commands."""

from __future__ import annotations

import asyncio
from typing import TYPE_CHECKING

from tcbot import database as db
from tcbot.modules.helper import extraction, identity, replies
from tcbot.modules.helper.locale import locale_for_update
from tcbot.modules.helper.parse_editmsg import safe_reply
from tcbot.utils.dispatch import throw_if_cancelled
from tcbot.utils.i18n import t
from tcbot.utils.logger import get_logger

if TYPE_CHECKING:
    from telegram import Bot, CallbackQuery, Message, Update

    from tcbot.modules.helper.identity import Identity

log = get_logger(__name__)

# * Admin runtime prose lives in admins.toml [error]/[promote_ui]/
# * [demote]/[transfer]/[list]/[decision]; no string constants stay here.

# * Rate-limiter windows shared by every admins submodule.
_RL_PERIOD_S: int = 30
_RL_PERIOD_LONG_S: int = 60
_RL_PERIOD_BULK_S: int = 300
_RL_CMD_LIMIT: int = 10
_RL_QUERY_LIMIT: int = 5
_RL_BULK_LIMIT: int = 3


# * One owner for the executor-plus-target fetch so a future fix cannot
# * land in one command and miss the other. Gathers stay parallel so the
# * hot path costs one cached round trip, never two serial ones.
async def _resolve_executor_target(
    msg: Message,
    admin_id: int,
    update: Update,
    args: list[str],
    bot: Bot | None,
    *,
    action: str,
    locale: str | None = None,
) -> tuple[str, int, str | None] | None:
    """Fetch executor role and target in parallel, fail closed.

    Returns ``(executor_role, target_id, target_fname)`` or ``None`` when
    the caller must return (retry reply already sent, or a genuinely
    role-less executor denied silently like the decorator would).
    Callers pass their already-resolved locale so the two DB reads behind
    locale resolution do not run twice per command.
    """
    if locale is None:
        locale = await locale_for_update(update)
    _exec_r, _target_r = await asyncio.gather(
        db.users_roles.get_effective_role(admin_id),
        extraction.extract_target(update, args, bot),
        return_exceptions=True,
    )
    throw_if_cancelled((_exec_r, _target_r))
    if isinstance(_exec_r, BaseException):
        # * Fail closed on transient outage instead of going silently dead.
        # * A genuinely role-less caller gets None below; the decorator
        # * denies them properly on retry.
        log.warning("cmd_%s executor role lookup failed: %s", action, _exec_r)
        await safe_reply(
            msg,
            t("admins.error.role_lookup_failed", locale, plain=True),
            log_label=f"cmd_{action} lookup-fail",
            parse_mode=None,
        )
        return None
    executor_role = _exec_r
    if executor_role is None:
        return None
    if isinstance(_target_r, BaseException):
        log.error("extract_target failed during %s: %s", action, _target_r)
        await safe_reply(
            msg,
            replies.err_cannot_resolve(locale, plain=True),
            log_label=f"cmd_{action} no-target",
            parse_mode=None,
        )
        return None
    target_id, target_fname = _target_r
    if not target_id:
        await safe_reply(
            msg,
            replies.err_cannot_resolve(locale, plain=True),
            log_label=f"cmd_{action} no-target-id",
            parse_mode=None,
        )
        return None
    return executor_role, target_id, target_fname


async def _classify_and_load_role(
    bot: Bot,
    admin_id: int,
    target_id: int,
    target_fname: str | None,
    msg: Message,
    *,
    action: str,
    locale: str | None = None,
) -> tuple[Identity, str | None] | None:
    """Classify the target and load its live role in parallel, fail closed.

    Returns ``(ident, current_role)`` or ``None`` when the caller must
    return (retry reply already sent). Cancellation always propagates.
    """
    ident_r, role_r = await asyncio.gather(
        identity.classify(bot, admin_id, target_id, target_fname),
        db.users_roles.get_effective_role(target_id),
        return_exceptions=True,
    )
    throw_if_cancelled((ident_r, role_r))
    if isinstance(ident_r, BaseException):
        log.error(
            "identity.classify failed during %s for target=%d: %s",
            action,
            target_id,
            ident_r,
        )
        await safe_reply(
            msg,
            t("admins.error.classify_failed", locale, plain=True),
            log_label=f"cmd_{action} classify-failed",
            parse_mode=None,
        )
        return None
    if isinstance(role_r, BaseException):
        log.error(
            "target role lookup failed during %s for target=%d: %s",
            action,
            target_id,
            role_r,
        )
        await safe_reply(
            msg,
            t("admins.error.role_lookup_failed", locale, plain=True),
            log_label=f"cmd_{action} role-lookup-failed",
            parse_mode=None,
        )
        return None
    return ident_r, role_r


async def _check_callback_staff(
    admin_id: int, q: CallbackQuery, update: Update
) -> str | None:
    """Re-check Founder/Admin rank alongside ``q.answer()`` in parallel.

    Answers the spinner immediately regardless of DB latency. Returns the
    staff role, or ``None`` after editing the perm-expired notice.
    Cancellation from either branch propagates instead of rendering.
    """
    role_r, answer_r = await asyncio.gather(
        db.users_roles.get_effective_role(admin_id),
        q.answer(),
        return_exceptions=True,
    )
    throw_if_cancelled((role_r, answer_r))
    if isinstance(answer_r, BaseException):
        log.debug("callback answer failed: %s", answer_r)
    if isinstance(role_r, BaseException) or role_r not in ("founder", "admin"):
        try:
            await q.edit_message_text(
                replies.err_perm_expired(await locale_for_update(update), plain=True),
                reply_markup=None,
            )
        except Exception as exc:
            log.debug("callback perm-expired edit failed: %s", exc)
        return None
    return role_r
