# © Copyright 2024 - 2026 Transsion Core
# © Copyright 2024 - 2026 Dizzy
# © Copyright 2026 Ave Labs

"""Set-role command: move an existing staff member between assignable tiers."""

from __future__ import annotations

from typing import TYPE_CHECKING

from telegram.ext import CallbackQueryHandler, ContextTypes, MessageHandler

from tcbot import database as db
from tcbot.modules.helper import buttons, decorators
from tcbot.modules.helper.guards import (
    action_owner_mismatch,
    cancel_owner_mismatch,
    check_callback_executor,
    require_federation_origin,
)
from tcbot.modules.helper.locale import locale_for_update
from tcbot.modules.helper.messages import (
    callback_args_optional,
    cb_error_edit,
    replies,
    reply_rich,
    safe_edit_cb,
)
from tcbot.modules.helper.pipelines.promote_flow import Promote, change_role_for_staff
from tcbot.modules.helper.targets import resolve_executor_target
from tcbot.utils.i18n import Safe, t, user_ref
from tcbot.utils.logger import get_logger
from tcbot.utils.prefixes import build_prefixed_filters, parse_cmd_args

if TYPE_CHECKING:
    from telegram import Update

log = get_logger(__name__)

__module_name__ = None


@decorators.ratelimiter(decorators.THROTTLE_MODERATION)
@decorators.staff_only
@decorators.log_execution
async def cmd_setrole(update: Update, ctx: ContextTypes.DEFAULT_TYPE) -> None:
    """Move an existing staff member to a different assignable role.

    The picker lists every tier the executor may grant except the one the
    target already holds, so Admin to Moderator and Moderator to Developer
    both work. The Owner is never offered as a target or a destination.
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
    args = parse_cmd_args(msg.text)
    resolved = await resolve_executor_target(
        msg, admin.id, update, args, ctx.bot, action="promote", locale=locale
    )
    if resolved is None:
        return
    executor_role, target_id, target_fname = resolved
    try:
        current_role = await db.users_roles.get_effective_role(target_id, fresh=True)
    except Exception:
        log.warning("cmd_setrole role lookup failed for target=%d", target_id)
        await reply_rich(
            msg,
            t("admins.error.role_lookup_failed", locale, plain=True),
            log_label="cmd_setrole role-lookup",
            parse_mode=None,
        )
        return
    if current_role == "owner":
        await reply_rich(
            msg,
            t("admins.promote.target_is_owner", locale, plain=True),
            log_label="cmd_setrole owner-target",
            parse_mode=None,
        )
        return
    available = Promote.available_roles_for(executor_role)
    if not available:
        await reply_rich(
            msg,
            t("admins.error.no_assign_perms", locale, plain=True),
            log_label="cmd_setrole no-perms",
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
        log_label="cmd_setrole picker",
        reply_markup=buttons.role_change_btn(
            target_id, available, current_role, locale, admin.id
        ),
    )


@decorators.ratelimiter(decorators.THROTTLE_STAFF)
@decorators.log_execution
async def on_role_change_btn(update: Update, ctx: ContextTypes.DEFAULT_TYPE) -> None:
    """Apply the role chosen in /tcsetrole with fresh rank checks."""
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


_SETROLE_CMDS = build_prefixed_filters("tcsetrole") | build_prefixed_filters("tcsr")

__handlers__ = [
    MessageHandler(_SETROLE_CMDS, cmd_setrole),
    CallbackQueryHandler(
        on_role_change_btn, pattern=r"^role_change:[a-z]+:\d+(:\d+)?$"
    ),
    CallbackQueryHandler(
        on_role_change_cancel, pattern=r"^role_change_cancel:\d+(:\d+)?$"
    ),
]
