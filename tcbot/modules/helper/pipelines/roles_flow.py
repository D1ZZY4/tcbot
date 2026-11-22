# © Copyright 2024 - 2026 Transsion Core
# © Copyright 2024 - 2026 Dizzy
# © Copyright 2026 Ave Labs

"""Role-change workflow: move an existing staff member between assignable tiers."""

from __future__ import annotations

import asyncio
from typing import TYPE_CHECKING

from telegram.ext import ContextTypes

from tcbot import cfg
from tcbot import database as db
from tcbot.modules.helper import buttons, decorators, messages
from tcbot.modules.helper.guards import (
    action_owner_mismatch,
    banned_target_refusal,
    cancel_owner_mismatch,
    check_callback_executor,
    outranks,
    require_federation_origin,
)
from tcbot.modules.helper.locale import locale_for_update, locale_for_user
from tcbot.modules.helper.messages import (
    callback_args_optional,
    cb_error_edit,
    replies,
    reply_rich,
    safe_edit_cb,
    send_log,
    send_text,
)
from tcbot.modules.helper.pipelines.promote_flow import Promote
from tcbot.modules.helper.targets import resolve_executor_target
from tcbot.utils.dispatch import throw_if_cancelled
from tcbot.utils.i18n import Safe, t, user_ref
from tcbot.utils.logger import get_logger
from tcbot.utils.prefixes import parse_cmd_args

if TYPE_CHECKING:
    from telegram import Bot, Update

log = get_logger(__name__)


def is_role_change_request(
    current_role: str | None, requested_role: str | None, executor_role: str | None
) -> bool:
    """Return True when a promote-style request against a roled target is a change.

    A user who already holds a federation role cannot receive a fresh grant:
    ``Promote.execute`` refuses any rank at or below their current one, and the
    identity refusal used to reject the Admin target before the change could
    run. Such a request is a role change when the requested tier is one the
    executor may grant directly, or when no tier was given (show the picker).
    A tier the executor cannot grant (Admin for an Admin) stays on the
    promotion path so an Admin can still queue an Admin request for the Owner.
    """
    if current_role not in db.users_roles.STAFF_ROLES:
        return False
    if requested_role is None:
        return True
    return requested_role in Promote.available_roles_for(executor_role)


async def change_role_for_staff(
    bot: Bot,
    admin_id: int,
    admin_fname: str,
    target_id: int,
    target_fname: str,
    role: str,
    locale: str | None = None,
) -> tuple[bool, str]:
    """Move an existing staff member to another assignable role.

    Unlike a promotion this accepts a lower target tier, so Admin to
    Moderator and Moderator to Developer are both possible. The Owner is
    never a valid target, the executor must outrank the current role, and a
    banned user cannot hold any federation role. Every role is re-read fresh
    at the mutation point so a demotion or transfer between the prompt and the
    tap cannot still grant the rank the executor held at entry.
    """
    role_results = await asyncio.gather(
        db.users_roles.get_effective_role(admin_id, fresh=True),
        db.users_roles.get_effective_role(target_id, fresh=True),
        return_exceptions=True,
    )
    throw_if_cancelled(role_results)
    executor_result, current_result = role_results
    if isinstance(executor_result, BaseException) or isinstance(
        current_result, BaseException
    ):
        log.warning(
            "change_role lookup failed: executor=%d target=%d", admin_id, target_id
        )
        return False, t("admins.error.role_lookup_failed", locale)
    executor_role, current_role = executor_result, current_result
    target_ref = Safe(user_ref(target_id, target_fname))
    if current_role == "owner":
        return False, t("admins.promote.target_is_owner", locale)
    if not current_role:
        return False, t("admins.role_change.no_role", locale, user=target_ref)
    if role == current_role:
        return False, t(
            "admins.role_change.same_role",
            locale,
            user=target_ref,
            role=db.users_roles.role_label(role),
        )
    if role not in Promote.available_roles_for(executor_role):
        return False, t("admins.promote.no_assign_perms", locale)
    if executor_role != "owner" and not outranks(executor_role, current_role):
        return False, t("admins.role_change.not_outranked", locale)
    refusal = await banned_target_refusal(
        target_id, locale, log_label="change_role ban-guard"
    )
    if refusal is not None:
        return False, refusal
    try:
        await db.users_roles.change_role(target_id, role, admin_id)
    except Exception:
        log.exception("change_role failed for target=%d role=%s", target_id, role)
        return False, t("admins.role_change.fail", locale)
    role_label = db.users_roles.role_label(role)
    target_locale = await locale_for_user(target_id)
    notice = await asyncio.gather(
        send_log(
            bot,
            messages.promoted(target_id, target_fname, role, admin_id, admin_fname),
        ),
        send_text(
            bot,
            target_id,
            t(
                "admins.role_change.dm",
                target_locale,
                role=role_label,
                community=cfg.community_name,
                plain=True,
            ),
        ),
        return_exceptions=True,
    )
    throw_if_cancelled(notice)
    for result in notice:
        if isinstance(result, BaseException):
            log.warning("change_role notice failed for %d: %s", target_id, result)
    return True, t(
        "admins.role_change.done",
        locale,
        user=target_ref,
        role=role_label,
        community=cfg.community_name,
    )


async def role_change_prompt(
    update: Update,
    *,
    executor_role: str | None,
    target_id: int,
    target_fname: str | None,
    locale: str | None,
) -> None:
    """Show the role-change picker for an already-roled target.

    The command resolves the origin and the target; this workflow owns the
    fresh role read, the protected-target and permission checks, and the
    picker itself. Both ``/tcsetrole`` and the role-change branch of
    ``/tcpromote`` land here so they can never drift apart.
    """
    msg = update.effective_message
    admin = update.effective_user
    if msg is None or admin is None:
        return
    try:
        current_role = await db.users_roles.get_effective_role(target_id, fresh=True)
    except Exception:
        log.warning("role_change_prompt role lookup failed for target=%d", target_id)
        await reply_rich(
            msg,
            t("admins.error.role_lookup_failed", locale, plain=True),
            log_label="role_change_prompt role-lookup",
            parse_mode=None,
        )
        return
    if current_role == "owner":
        await reply_rich(
            msg,
            t("admins.promote.target_is_owner", locale, plain=True),
            log_label="role_change_prompt owner-target",
            parse_mode=None,
        )
        return
    available = Promote.available_roles_for(executor_role)
    if not available:
        await reply_rich(
            msg,
            t("admins.error.no_assign_perms", locale, plain=True),
            log_label="role_change_prompt no-perms",
            parse_mode=None,
        )
        return
    await reply_rich(
        msg,
        t(
            "admins.role_change.picker",
            locale,
            user=Safe(user_ref(target_id, target_fname or str(target_id))),
            role=db.users_roles.role_label(current_role or "moderator"),
        ),
        log_label="role_change_prompt picker",
        reply_markup=buttons.role_change_btn(
            target_id, available, current_role, locale, admin.id
        ),
    )


# ───────────────────────── Role-change command ────────────────────────── #


@decorators.ratelimiter(decorators.THROTTLE_MODERATION)
@decorators.staff_only
@decorators.log_execution
async def cmd_setrole(update: Update, ctx: ContextTypes.DEFAULT_TYPE) -> None:
    """Open the picker that moves an existing staff member to another tier.

    The entry owns the origin and target resolution; the picker and the
    mutation are shared with the role-change branch of ``/tcpromote``.
    """
    admin = update.effective_user
    msg = update.effective_message
    if admin is None or msg is None:
        return
    locale = await locale_for_update(update)
    if not await require_federation_origin(
        msg,
        chat_id=msg.chat.id,
        chat_type=msg.chat.type,
        locale=locale,
        allow_private=True,
        log_label="cmd_setrole origin",
    ):
        return
    resolved = await resolve_executor_target(
        msg,
        admin.id,
        update,
        parse_cmd_args(msg.text),
        ctx.bot,
        action="promote",
        locale=locale,
    )
    if resolved is None:
        return
    executor_role, target_id, target_fname = resolved
    await role_change_prompt(
        update,
        executor_role=executor_role,
        target_id=target_id,
        target_fname=target_fname,
        locale=locale,
    )


# ───────────────────────── Role-change callbacks ───────────────────────── #


@decorators.ratelimiter(decorators.THROTTLE_STAFF)
@decorators.log_execution
async def on_role_change_btn(update: Update, ctx: ContextTypes.DEFAULT_TYPE) -> None:
    """Apply the role chosen in the picker with fresh rank checks."""
    q = update.callback_query
    if q is None:
        return
    args = callback_args_optional(q, 3)
    if args is None:
        await q.answer()
        return
    role, target_id_str = args[0], args[1]
    try:
        target_id = int(target_id_str)
    except ValueError:
        await q.answer()
        return
    if await action_owner_mismatch(q, update, min_parts=3):
        return
    admin = update.effective_user
    if admin is None:
        await q.answer()
        return
    if await check_callback_executor(update, q, admin) is None:
        return
    if role not in db.users_roles.STAFF_ROLES:
        await cb_error_edit(
            q,
            replies.err_unknown_role(await locale_for_update(update), plain=True),
            log_label="on_role_change_btn unknown-role",
            parse_mode=None,
        )
        return
    locale = await locale_for_update(update)
    target_fname = await db.users_cache.get_first_name(target_id, str(target_id))
    _, text = await change_role_for_staff(
        ctx.bot,
        admin.id,
        admin.first_name,
        target_id,
        target_fname,
        role,
        locale,
    )
    await safe_edit_cb(
        q,
        text,
        reply_markup=None,
        log_level="debug",
        log_label="on_role_change_btn result",
        catch_all=True,
    )


@decorators.ratelimiter(decorators.THROTTLE_STAFF)
@decorators.log_execution
async def on_role_change_cancel(update: Update, ctx: ContextTypes.DEFAULT_TYPE) -> None:
    """Dismiss the role-change picker without changing anything."""
    q = update.callback_query
    if q is None:
        return
    if await cancel_owner_mismatch(q, update):
        return
    admin = update.effective_user
    if admin is None:
        await q.answer()
        return
    if await check_callback_executor(update, q, admin) is None:
        return
    await safe_edit_cb(
        q,
        t("admins.error.cancelled", await locale_for_update(update), plain=True),
        reply_markup=None,
        parse_mode=None,
        log_level="debug",
        log_label="on_role_change_cancel",
        catch_all=True,
    )
